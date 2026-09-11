# analytics/translators.py
import os
import logging
import requests

logger = logging.getLogger("analytics_digest")


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    """Переводит и/или суммаризирует текст через Gemini с fallback на googletrans."""
    if not text or len(text.strip()) < 10:
        return text

    # Проверка: если больше 30% кириллицы — считаем русским
    cyrillic = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    if cyrillic / len(text) > 0.3:
        return text

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            if is_summary:
                prompt = (
                    "Сделай краткое резюме (1-2 предложения) на русском языке для текста ниже.\n\n"
                    "ПРАВИЛА:\n"
                    "- Только резюме. Без вступлений, пояснений, комментариев.\n"
                    "- НЕ добавляй фразы типа «Пост опубликован на сайте X», «впервые появился на сайте X».\n"
                    "- НЕ повторяй название источника.\n"
                    "- Игнорируй HTML-теги, изображения и атрибуты.\n"
                    "- Соблюдай пробелы после знаков препинания.\n"
                    "- Не оставляй английские слова без перевода, если есть русский аналог.\n"
                    "- Если текст уже на русском — просто сократи.\n\n"
                    f"Текст: {text[:500]}"
                )
            else:
                prompt = (
                    "Переведи текст на русский язык. Только перевод, без пояснений.\n\n"
                    "ПРАВИЛА:\n"
                    "- Не добавляй HTML-теги, атрибуты и ссылки.\n"
                    "- Соблюдай пробелы после знаков препинания.\n"
                    "- Не переводи названия СМИ и компаний (оставляй как есть).\n\n"
                    f"Текст: {text[:300]}"
                )

            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash:generateContent?key={api_key}"
            )
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("candidates"):
                    result = data["candidates"][0].get("content", {}).get("parts", [])
                    if result:
                        return result[0].get("text", text).strip()
        except Exception as e:
            logger.debug(f"Gemini failed: {e}")

    # Fallback: googletrans
    try:
        from googletrans import Translator
        translator = Translator()
        translated = translator.translate(text[:500], dest="ru").text
        return translated
    except Exception:
        return text
