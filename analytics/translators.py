# analytics/translators.py
import os
import time
import logging
import requests

logger = logging.getLogger("analytics_digest")

# Глобальный rate limit для Gemini (минимум 15 сек между запросами на free tier)
_LAST_GEMINI_CALL = [0.0]
_GEMINI_MIN_INTERVAL = 15.0


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _translate_via_deeptranslator(text: str) -> str:
    """Основной переводчик — deep-translator (Google Translate, без ключа)."""
    try:
        from deep_translator import GoogleTranslator
        # Ограничение длины — Google Translate не принимает слишком длинные куски
        chunk = text[:4500]
        translated = GoogleTranslator(source="auto", target="ru").translate(chunk)
        if translated and translated.strip() and translated.strip() != chunk.strip():
            return translated.strip()
    except Exception as e:
        logger.debug(f"deep-translator failed: {e}")
    return ""


def _translate_via_gemini(text: str, is_summary: bool) -> str:
    """Резервный переводчик — Gemini. С глобальным rate limit."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ""

    # Rate limit: выдерживаем паузу между запросами
    elapsed = time.time() - _LAST_GEMINI_CALL[0]
    if elapsed < _GEMINI_MIN_INTERVAL:
        time.sleep(_GEMINI_MIN_INTERVAL - elapsed)
    _LAST_GEMINI_CALL[0] = time.time()

    if is_summary:
        prompt = (
            "Сделай краткое резюме (1-2 предложения) на русском языке.\n\n"
            "ЖЁСТКИЕ ПРАВИЛА:\n"
            "1. Только чистый текст без markdown.\n"
            "2. НЕ добавляй транслитерацию или оригинал в скобках.\n"
            "3. НЕ повторяй название источника.\n"
            "4. Соблюдай пробелы после знаков препинания.\n\n"
            f"Текст: {text[:800]}"
        )
    else:
        prompt = (
            "Переведи заголовок на русский язык.\n\n"
            "ЖЁСТКИЕ ПРАВИЛА:\n"
            "1. Только чистый перевод, без markdown.\n"
            "2. НЕ добавляй транслитерацию в скобках.\n"
            "3. НЕ добавляй название источника.\n"
            "4. Названия компаний (Google, OpenAI, NATO) не переводи.\n\n"
            f"Текст: {text[:300]}"
        )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.8-flash:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("candidates"):
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        translated = parts[0].get("text", "").strip()
                        if translated and translated != text.strip():
                            return translated
            elif resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(3)
                continue
            else:
                logger.debug(f"Gemini HTTP {resp.status_code}")
                break
        except Exception as e:
            logger.debug(f"Gemini error: {e}")
            break
    return ""


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    """Переводит через deep-translator, при неудаче — Gemini."""
    if not text or len(text.strip()) < 3:
        return text

    # Уже на русском?
    if _cyrillic_ratio(text) > 0.3:
        return text

    # Основной путь
    translated = _translate_via_deeptranslator(text)
    if translated:
        return translated

    # Резерв
    translated = _translate_via_gemini(text, is_summary)
    if translated:
        return translated

    return text
