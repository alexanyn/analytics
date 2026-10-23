# analytics/text_utils.py
import re
import os
import logging
import requests
import urllib3
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("analytics_digest")

def normalize_for_dedup(title: str) -> str:
    if not title: return ""
    s = title.lower().strip()
    s = re.sub(r"\s+[-–—|]\s+[^\s].{0,80}$", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

def _cyrillic_ratio(text: str) -> float:
    if not text: return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)

def looks_translated(original: str, translated: str) -> bool:
    if not translated or not original: return False
    if translated.strip() == original.strip(): return False
    return True  # Если текст изменился — перевод был!

def fetch_description_from_html(url: str) -> str:
    """Достаем описание. Для Google News сначала расшифровываем ссылку."""
    jina_key = os.environ.get("JINA_API_KEY")
    if not jina_key:
        return ""

    # Расшифровка Google News
    real_url = url
    if "news.google.com" in url:
        try:
            decoded = gnewsdecoder(url, interval=1)
            if decoded.get("status") and decoded.get("decoded_url"):
                real_url = decoded["decoded_url"]
        except Exception as e:
            logger.debug(f"Google News decode failed: {e}")

    headers = {
        "Authorization": f"Bearer {jina_key}",
        "Accept": "text/plain",
        "X-With-Generated-Alt": "true"
    }
    
    try:
        jina_url = f"https://r.jina.ai/{real_url}"
        resp = requests.get(jina_url, headers=headers, timeout=20)
        
        if resp.status_code != 200 or "Target URL returned error" in resp.text:
            return ""

        text = resp.text
        if "Markdown Content:" in text:
            content = text.split("Markdown Content:")[-1].strip()
        else:
            content = text.strip()

        for p in content.split("\n\n"):
            p = p.strip()
            if (len(p) > 80 
                and not p.startswith(("!", "[", "##", "**", "|", "*", "http", "-"))
                and "](" not in p
                and "cookie" not in p.lower()):
                return p[:1000]
    except Exception as e:
        logger.debug(f"Jina fetch failed: {e}")
    return ""
