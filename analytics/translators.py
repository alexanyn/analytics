import os
import requests
import logging
from typing import Optional
logger = logging.getLogger("analytics_digest")
def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not text or len(text.strip()) < 10:
        return text
    cyrillic = sum(1 for c in text if 'а' <= c.lower() <= 'я' or c == 'ё')
    if cyrillic / len(text) > 0.3:
        return text
    if is_summary:
        prompt = f"""Сделай краткое резюме (1-2 предложения) на русском языке для следующего текста.
Если текст на английском, переведи и сократи. Только результат, без пояснений.
Текст: {text[:500]}"""
    else:
        prompt = f"""Переведи следующий текст на русский язык. Только перевод, без пояснений.
Текст: {text[:300]}"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("candidates"):
                result = data["candidates"][0].get("content", {}).get("parts", [])
                if result:
                    return result[0].get("text", text).strip()
    except Exception as e:
        logger.debug(f"Gemini failed: {e}")
    try:
        from googletrans import Translator
        translator = Translator()
        translated = translator.translate(text[:500], dest='ru').text
        return translated
    except:
        return text
