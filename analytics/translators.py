# analytics/translators.py
import os
import time
import logging
import requests

logger = logging.getLogger("analytics_digest")


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _translate_deepl(text: str) -> str:
    """Перевод через DeepL (Free tier: 500k символов/мес)."""
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        return ""
    # Free tier использует api-free.deepl.com, Pro — api.deepl.com
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json={"text": [text[:4500]], "target_lang": "RU"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("translations"):
                return data["translations"][0].get("text", "").strip()
        elif resp.status_code == 456:
            logger.warning("DeepL: квота исчерпана")
        elif resp.status_code == 403:
            logger.warning("DeepL: неверный API-ключ")
        else:
            logger.debug(f"DeepL HTTP {resp.status_code}: {resp.text[:150]}")
    except Exception as e:
        logger.debug(f"DeepL failed: {e}")
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
