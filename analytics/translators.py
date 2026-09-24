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
                "Сделай краткое резюме (1-2 предложения) на русском языке.\n\n"
                "ЖЁСТКИЕ ПРАВИЛА (соблюдать обязательно):\n"
                "1. Только чистый текст. Без markdown (** _ # `).\n"
                "2. НЕ добавляй транслитерацию в скобках.\n"
                "3. НЕ добавляй оригинал в скобках.\n"
                "4. НЕ добавляй фразы «Пост опубликован на сайте X», «впервые появилось на сайте X».\n"
                "5. НЕ повторяй название источника.\n"
                "6. НЕ добавляй пояснений, вступлений, комментариев.\n"
                "7. Игнорируй HTML-теги, изображения и атрибуты.\n"
                "8. Соблюдай пробелы после знаков препинания.\n\n"
                f"Текст: {text[:500]}"
            )
        else:
            prompt = (
                "Переведи заголовок на русский язык.\n\n"
                "ЖЁСТКИЕ ПРАВИЛА (соблюдать обязательно):\n"
                "1. Только чистый текст перевода. Без markdown (** _ # `), без кавычек-обёрток.\n"
                "2. НЕ добавляй транслитерацию в скобках типа (Privet, mir!).\n"
                "3. НЕ добавляй оригинал в скобках после перевода.\n"
                "4. НЕ добавляй название источника в конце.\n"
                "5. НЕ добавляй HTML-теги, атрибуты, ссылки.\n"
                "6. НЕ добавляй пояснений, комментариев, вступлений.\n"
                "7. Соблюдай пробелы после знаков препинания.\n"
                "8. Названия компаний и брендов (Google, OpenAI, NATO) не переводи.\n\n"
                f"Текст: {text[:300]}"
            )

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.8-flash:generateContent?key={api_key}"
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
