# analytics/translators.py
import os
import time
import threading
import logging
import requests

logger = logging.getLogger("analytics_digest")

_STATS = {"googletrans_ok": 0, "deepl_ok": 0, "gemini_ok": 0, "fail": 0}

# Rate limiter для googletrans (Google Translate: 5 запросов/сек лимит)
_LOCK = threading.Lock()
_LAST_CALL = [0.0]
_MIN_INTERVAL = 0.35  # ~2.85 запроса/сек

# Флаги доступности внешних сервисов (если упали — не тратим время)
_DEEPL_AVAILABLE = [True]
_GEMINI_AVAILABLE = [True]


def _rate_limit():
    with _LOCK:
        elapsed = time.time() - _LAST_CALL[0]
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _LAST_CALL[0] = time.time()


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _is_russian(text: str) -> bool:
    return _cyrillic_ratio(text) > 0.3


# =============== 1. GOOGLETRANS (основной) ===============

def _translate_googletrans(text: str) -> str:
    """Google Translate через googletrans — работает из GitHub Actions."""
    if not text:
        return ""
    try:
        from googletrans import Translator
        for attempt in range(3):
            _rate_limit()
            try:
                t = Translator().translate(text[:4500], dest="ru").text
                if t and t.strip() and t.strip() != text.strip():
                    return t.strip()
                return ""
            except Exception as e:
                err = str(e).lower()
                if "too many" in err or "429" in err:
                    time.sleep(2 ** attempt)
                    continue
                logger.debug(f"googletrans inner: {e}")
                return ""
    except Exception as e:
        logger.debug(f"googletrans import/fatal: {e}")
    return ""


# =============== 2. DEEPL (если работает) ===============

def _translate_deepl(text: str) -> str:
    """DeepL — может не работать из GitHub Actions (IP-блок)."""
    if not _DEEPL_AVAILABLE[0]:
        return ""
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        _DEEPL_AVAILABLE[0] = False
        return ""

    host = "api-free.deepl.com" if api_key.strip().endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    chunk = text[:5000]

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"DeepL-Auth-Key {api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={"text": [chunk], "target_lang": "RU", "preserve_formatting": False},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("translations"):
                t = data["translations"][0].get("text", "").strip()
                if t:
                    return t
            return ""
        if resp.status_code == 403:
            _DEEPL_AVAILABLE[0] = False
            logger.warning("DeepL: 403 (IP-блок или неверный ключ). Отключаю DeepL до конца прогона.")
            return ""
        if resp.status_code == 456:
            _DEEPL_AVAILABLE[0] = False
            logger.warning("DeepL: квота исчерпана. Отключаю DeepL.")
            return ""
        logger.debug(f"DeepL HTTP {resp.status_code}")
    except Exception as e:
        logger.debug(f"DeepL exception: {e}")
    return ""


# =============== 3. GEMINI (крайний fallback) ===============

def _translate_gemini(text: str, is_summary: bool = False) -> str:
    if not _GEMINI_AVAILABLE[0]:
        return ""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        _GEMINI_AVAILABLE[0] = False
        return ""

    prompt = (
        "Переведи на русский язык (кратко, 1-2 предложения). Без markdown. Только чистый текст.\n\n"
        if is_summary
        else "Переведи заголовок на русский язык. Без markdown, без транслитерации, без названия источника. Только чистый перевод.\n\n"
    ) + f"Текст: {text[:500]}"

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.8-flash:generateContent?key={api_key}"
    )
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("candidates"):
                parts = data["candidates"][0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
        elif resp.status_code in (429, 503):
            _GEMINI_AVAILABLE[0] = False
            logger.warning(f"Gemini: {resp.status_code} — отключаю Gemini до конца прогона")
    except Exception as e:
        logger.debug(f"Gemini: {e}")
    return ""


# =============== Оркестратор ===============

def _translate(text: str, is_summary: bool = False) -> str:
    """googletrans → DeepL → Gemini."""
    if not text or len(text.strip()) < 3:
        return ""

    # 1. googletrans (основной — работает из GitHub)
    t = _translate_googletrans(text)
    if t:
        _STATS["googletrans_ok"] += 1
        return t

    # 2. DeepL (может не работать, но не тратим время если упал)
    t = _translate_deepl(text)
    if t:
        _STATS["deepl_ok"] += 1
        return t

    # 3. Gemini
    t = _translate_gemini(text, is_summary=is_summary)
    if t:
        _STATS["gemini_ok"] += 1
        return t

    _STATS["fail"] += 1
    return ""


def translate_article(title: str, summary: str) -> tuple[str, str]:
    t_cyr = _is_russian(title)
    s_cyr = _is_russian(summary) if summary else True
    if t_cyr and s_cyr:
        return title, summary

    final_title = title
    final_summary = summary

    if not t_cyr:
        translated = _translate(title, is_summary=False)
        if translated:
            final_title = translated

    if not s_cyr and summary:
        translated = _translate(summary, is_summary=True)
        if translated:
            final_summary = translated

    return final_title, final_summary


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    if not text or len(text.strip()) < 3:
        return text
    if _is_russian(text):
        return text
    return _translate(text, is_summary=is_summary) or text
