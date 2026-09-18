# analytics/translators.py
import os
import time
import logging
import requests

logger = logging.getLogger("analytics_digest")


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    """Перевод/суммаризация через Gemini с retry на 429 и fallback на googletrans."""
    if not text or len(text.strip()) < 3:
        return text

    cyrillic = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    if cyrillic / max(len(text), 1) > 0.3:
        return text  # Уже русский

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        if is_summary:
            prompt = (
                "Сделай краткое резюме (1-2 предложения) на русском языке для текста ниже.\n\n"
                "ПРАВИЛА:\n"
                "- Только резюме. Без вступлений, пояснений, комментариев.\n"
                "- НЕ добавляй фразы «Пост опубликован на сайте X», «Сообщение ... впервые появилось на сайте X».\n"
                "- НЕ повторяй название источника.\n"
                "- Игнорируй HTML-теги, изображения и атрибуты.\n"
                "- Соблюдай пробелы после знаков препинания.\n\n"
                f"Текст: {text[:500]}"
            )
        else:
            prompt = (
                "Переведи заголовок на русский язык. Только перевод, без пояснений.\n\n"
                "ПРАВИЛА:\n"
                "- Не добавляй HTML-теги, атрибуты, ссылки.\n"
                "- НЕ добавляй название источника в конце.\n"
                "- Соблюдай пробелы после знаков препинания.\n"
                "- Не оставляй английские слова без перевода, если есть русский аналог.\n\n"
                f"Текст: {text[:300]}"
            )

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("candidates"):
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
                        if parts:
                            translated = parts[0].get("text", "").strip()
                            if translated and translated != text.strip():
                                return translated
                    # Пустой ответ — повторяем
                    logger.debug(f"Gemini empty response (attempt {attempt + 1})")
                elif resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.debug(f"Gemini 429, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    logger.debug(f"Gemini HTTP {resp.status_code}")
                    break
            except requests.exceptions.Timeout:
                logger.debug(f"Gemini timeout (attempt {attempt + 1})")
                time.sleep(1)
            except Exception as e:
                logger.debug(f"Gemini error: {e}")
                break

    # Fallback: googletrans
    try:
        from googletrans import Translator
        translator = Translator()
        translated = translator.translate(text[:500], dest="ru").text
        if translated and translated != text.strip():
            return translated
    except Exception:
        pass

    return text
