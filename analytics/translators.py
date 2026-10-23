"""translators.py — генерация русских карточек через Groq."""
from __future__ import annotations
import logging, os, re, requests
from typing import Dict, Any
try:
    from . import text_utils as tu
except ImportError:
    import text_utils as tu

log = logging.getLogger("analytics")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def groq_chat(prompt: str, system: str = "Ты редактор аналитического дайджеста.") -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key: return ""
    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
    for model in models:
        try:
            r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"}, json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.3
            }, timeout=20)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception: pass
    return ""

def gemini_generate(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key: return ""
    try:
        r = requests.post(f"{GEMINI_URL}?key={key}", json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception: pass
    return ""

def make_russian_card(title: str, source_text: str = "") -> Dict[str, Any]:
    if not source_text:
        prompt = f"Заголовок: {title}\n\nНапиши краткое описание (1-2 предложения) на русском языке, раскрывающее суть этого заголовка. Не выдумывай конкретные цифры и имена. Также переведи заголовок на русский.\n\nОтвет строго в формате:\nЗАГОЛОВОК: <заголовок>\nОПИСАНИЕ: <текст>"
    else:
        prompt = f"Заголовок: {title}\n\nТекст: {source_text[:2000]}\n\n1) Переведи заголовок на русский.\n2) Напиши краткое описание (1-2 предложения) на русском языке, раскрывающее суть статьи.\n\nОтвет строго в формате:\nЗАГОЛОВОК: <заголовок>\nОПИСАНИЕ: <текст>"
    raw = groq_chat(prompt) or gemini_generate(prompt)
    if not raw: return {"title_ru": title, "description": "", "method": "raw"}
    m = re.search(r"ЗАГОЛОВОК:\s*(.+?)\s*\n+\s*ОПИСАНИЕ:\s*(.+)", raw, re.S | re.I)
    if m: return {"title_ru": m.group(1).strip(), "description": m.group(2).strip(), "method": "llm"}
    m2 = re.search(r"ОПИСАНИЕ:\s*(.+)", raw, re.S | re.I)
    if m2: return {"title_ru": title, "description": m2.group(1).strip(), "method": "llm"}
    return {"title_ru": title, "description": raw, "method": "llm"}
