# analytics/translators.py
import os
import logging
import requests

logger = logging.getLogger("analytics_digest")
_STATS = {"groq_ok": 0, "deepl_ok": 0, "googletrans_ok": 0, "generated": 0, "fail": 0}

def _call_groq(prompt: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key: return ""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
    
    for model in models:
        try:
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return ""

def generate_description_groq(title: str) -> str:
    """Если текста нет вообще — просим ИИ написать описание по заголовку."""
    prompt = f"Напиши краткое описание (1-2 предложения) на русском языке, раскрывающее суть этого заголовка: {title}. Не выдумывай конкретные цифры и имена."
    res = _call_groq(prompt)
    if res: _STATS["generated"] += 1
    return res

def _translate_groq(text: str, is_summary: bool = False) -> str:
    prompt = "Переведи этот текст на русский язык. Верни ТОЛЬКО перевод:\n\n" + text[:2500]
    return _call_groq(prompt)

def _translate_deepl(text: str) -> str:
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key: return ""
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    try:
        resp = requests.post(f"https://{host}/v2/translate", 
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json={"text": [text[:5000]], "target_lang": "RU"}, timeout=10)
        if resp.status_code == 200:
            return resp.json()["translations"][0]["text"].strip()
    except Exception: pass
    return ""

def _translate_googletrans(text: str) -> str:
    try:
        from googletrans import Translator
        return Translator().translate(text[:4500], dest="ru").text
    except Exception: return ""

def translate_article(title: str, summary: str) -> tuple[str, str]:
    t_cyr = sum(1 for c in title if 'а' <= c.lower() <= 'я' or c == 'ё') / max(len(title), 1) > 0.3
    
    final_title = title
    if not t_cyr:
        for name, func in [("groq", _translate_groq), ("deepl", _translate_deepl), ("googletrans", _translate_googletrans)]:
            t = func(title)
            if t: 
                final_title = t
                _STATS[f"{name}_ok"] += 1
                break

    final_summary = summary
    if summary:
        s_cyr = sum(1 for c in summary if 'а' <= c.lower() <= 'я' or c == 'ё') / max(len(summary), 1) > 0.3
        if not s_cyr:
            for name, func in [("groq", _translate_groq), ("deepl", _translate_deepl), ("googletrans", _translate_googletrans)]:
                t = func(summary)
                if t:
                    final_summary = t
                    _STATS[f"{name}_ok"] += 1
                    break
                    
    return final_title, final_summary
