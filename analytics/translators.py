# analytics/translators.py
import os
import time
import logging
import requests

logger = logging.getLogger("analytics_digest")

# Статистика для диагностики
_DEEPL_STATS = {"ok": 0, "empty": 0, "quota": 0, "error": 0}


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _translate_deepl(text: str) -> str:
    """Перевод через DeepL Free (500k символов/мес). С retry и логированием."""
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        return ""
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"

    # Обрезаем слишком длинные тексты (DeepL free имеет лимит ~5000 символов на запрос)
    chunk = text[:5000]

    for attempt in range(3):
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
                        _DEEPL_STATS["ok"] += 1
                        return t
                _DEEPL_STATS["empty"] += 1
                return ""
            elif resp.status_code == 456:
                _DEEPL_STATS["quota"] += 1
                logger.warning("DeepL: квота исчерпана (500k/мес)")
                return ""
            elif resp.status_code == 403:
                logger.error("DeepL: неверный API-ключ")
                return ""
            elif resp.status_code == 429:
                wait = 2 ** attempt + 1
                logger.debug(f"DeepL rate limit, waiting {wait}s... (attempt {attempt+1})")
                time.sleep(wait)
                continue
            elif resp.status_code >= 500:
                wait = 2 ** attempt
                logger.debug(f"DeepL HTTP {resp.status_code}, waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                logger.warning(f"DeepL HTTP {resp.status_code}: {resp.text[:200]} for text: {chunk[:80]}")
                return ""
        except requests.exceptions.Timeout:
            logger.debug(f"DeepL timeout (attempt {attempt+1})")
            time.sleep(2)
        except Exception as e:
            _DEEPL_STATS["error"] += 1
            logger.warning(f"DeepL exception: {e}")
            return ""
    return ""


def _translate_gemini(text: str, is_summary: bool = False) -> str:
    """Fallback — Gemini."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ""
    if is_summary:
        prompt = (
            "Сделай краткое резюме (1-2 предложения) на русском языке. "
            "Без markdown, без транслитерации. Только чистый текст.\n\n"
            f"Текст: {text[:800]}"
        )
    else:
        prompt = (
            "Переведи заголовок на русский язык. "
            "Без markdown, без транслитерации, без названия источника. "
            "Только чистый перевод.\n\n"
            f"Текст: {text[:300]}"
        )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.8-flash:generateContent?key={api_key}"
    )
    for attempt in range(2):
        try:
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
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
        except Exception as e:
            logger.debug(f"Gemini failed: {e}")
            return ""
    return ""


def translate_article(title: str, summary: str) -> tuple[str, str]:
    """Переводит через DeepL → Gemini fallback."""
    t_cyr = _cyrillic_ratio(title) > 0.3
    s_cyr = _cyrillic_ratio(summary) > 0.3 if summary else True

    if t_cyr and s_cyr:
        return title, summary

    final_title = title
    final_summary = summary

    if not t_cyr:
        final_title = _translate_deepl(title) or _translate_gemini(title, is_summary=False) or title

    if not s_cyr and summary:
        final_summary = _translate_deepl(summary) or _translate_gemini(summary, is_summary=True) or summary

    return final_title, final_summary


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    """Совместимость со старым API."""
    if not text or len(text.strip()) < 3:
        return text
    if _cyrillic_ratio(text) > 0.3:
        return text
    return _translate_deepl(text) or _translate_gemini(text, is_summary) or text
