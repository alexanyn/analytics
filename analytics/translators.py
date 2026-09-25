# analytics/translators.py
import os
import time
import logging
import requests

logger = logging.getLogger("analytics_digest")

_STATS = {"deepl_ok": 0, "gemini_ok": 0, "googletrans_ok": 0, "fail": 0}


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _is_russian(text: str) -> bool:
    return _cyrillic_ratio(text) > 0.3


def _translate_deepl(text: str) -> str:
    """DeepL Free tier — основной переводчик."""
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        return ""
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    chunk = text[:5000]

    for attempt in range(2):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"DeepL-Auth-Key {api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": [chunk], "target_lang": "RU", "preserve_formatting": False},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("translations"):
                    t = data["translations"][0].get("text", "").strip()
                    if t:
                        return t
                return ""
            elif resp.status_code == 456:
                logger.warning("DeepL: квота исчерпана")
                return ""
            elif resp.status_code == 403:
                logger.warning("DeepL: неверный API-ключ")
                return ""
            elif resp.status_code == 429:
                time.sleep(2 ** attempt + 1)
                continue
            elif resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            else:
                logger.debug(f"DeepL HTTP {resp.status_code}: {resp.text[:150]}")
                return ""
        except Exception as e:
            logger.debug(f"DeepL error: {e}")
            return ""
    return ""


def _translate_gemini(text: str, is_summary: bool = False) -> str:
    """Gemini — fallback."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ""
    if is_summary:
        prompt = (
            "Переведи на русский язык (кратко, 1-2 предложения). Без markdown. "
            "Только чистый текст.\n\n" f"{text[:800]}"
        )
    else:
        prompt = (
            "Переведи заголовок на русский язык. Без markdown, без транслитерации, "
            "без названия источника. Только чистый перевод.\n\n" f"{text[:300]}"
        )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.8-flash:generateContent?key={api_key}"
    )
    for attempt in range(2):
        try:
            resp = requests.post(
                url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("candidates"):
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            elif resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 + attempt * 2)
                continue
            else:
                return ""
        except Exception:
            return ""
    return ""


def _translate_googletrans(text: str) -> str:
    """googletrans — последний fallback."""
    try:
        from googletrans import Translator
        t = Translator().translate(text[:4000], dest="ru").text
        return t.strip() if t else ""
    except Exception as e:
        logger.debug(f"googletrans failed: {e}")
        return ""


def _translate(text: str, is_summary: bool = False) -> str:
    """Пробует DeepL → Gemini → googletrans."""
    if not text or len(text.strip()) < 3:
        return ""

    # DeepL
    t = _translate_deepl(text)
    if t:
        _STATS["deepl_ok"] += 1
        return t

    # Gemini
    t = _translate_gemini(text, is_summary=is_summary)
    if t:
        _STATS["gemini_ok"] += 1
        return t

    # googletrans
    t = _translate_googletrans(text)
    if t:
        _STATS["googletrans_ok"] += 1
        return t

    _STATS["fail"] += 1
    return ""


def translate_article(title: str, summary: str) -> tuple[str, str]:
    """Переводит title и summary. Возвращает (t_title, t_summary)."""
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
    """Совместимость со старым API."""
    if not text or len(text.strip()) < 3:
        return text
    if _is_russian(text):
        return text
    return _translate(text, is_summary=is_summary) or text
