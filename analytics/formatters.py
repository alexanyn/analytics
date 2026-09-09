import json
import re
from urllib.parse import urlparse
from typing import Dict
from .models import Article
def load_source_names() -> Dict[str, str]:
    with open("sources.json", "r", encoding="utf-8") as f:
        return json.load(f)
CANONICAL_NAMES = load_source_names()
def clean_html(text: str) -> str:
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, 'html.parser')
        for script in soup(['script', 'style']):
            script.decompose()
        text = soup.get_text()
    except:
        text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text.strip()
def get_source_name(feed_url: str) -> str:
    for domain, name in CANONICAL_NAMES.items():
        if domain in feed_url:
            return name
    domain = urlparse(feed_url).netloc.replace("www.", "")
    return domain.split("/")[0]
def get_category_emoji(category: str) -> str:
    emojis = {
        "GEOPOLITICS_WORLD": "🌍",
        "GEOPOLITICS_RUSSIA": "🇷🇺",
        "ECONOMICS_WORLD": "📈",
        "ECONOMICS_RUSSIA": "📊",
        "TECHNOLOGY_WORLD": "💻",
        "TECHNOLOGY_RUSSIA": "🖥️",
        "ENERGY_WORLD": "⚡",
        "ENERGY_RUSSIA": "🔋",
        "SECURITY_WORLD": "🛡️",
        "SECURITY_RUSSIA": "⚔️",
        "PR_WORLD": "📢",
        "PR_RUSSIA": "📣",
    }
    return emojis.get(category, "📌")
def get_category_russian_name(category: str) -> str:
    names = {
        "GEOPOLITICS_WORLD": "ГЕОПОЛИТИКА | МИР",
        "GEOPOLITICS_RUSSIA": "ГЕОПОЛИТИКА | РОССИЯ",
        "ECONOMICS_WORLD": "ЭКОНОМИКА | МИР",
        "ECONOMICS_RUSSIA": "ЭКОНОМИКА | РОССИЯ",
        "TECHNOLOGY_WORLD": "ТЕХНОЛОГИИ | МИР",
        "TECHNOLOGY_RUSSIA": "ТЕХНОЛОГИИ | РОССИЯ",
        "ENERGY_WORLD": "ЭНЕРГЕТИКА | МИР",
        "ENERGY_RUSSIA": "ЭНЕРГЕТИКА | РОССИЯ",
        "SECURITY_WORLD": "БЕЗОПАСНОСТЬ | МИР",
        "SECURITY_RUSSIA": "БЕЗОПАСНОСТЬ | РОССИЯ",
        "PR_WORLD": "PR & КОММУНИКАЦИИ | МИР",
        "PR_RUSSIA": "PR & КОММУНИКАЦИИ | РОССИЯ",
    }
    return names.get(category, category)
def article_to_html(article: Article, cache: dict) -> str:
    cached = cache.get(article.title, {})
    title = cached.get("translated_title", article.title)
    summary = cached.get("translated_summary", article.summary)
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    summary = clean_html(summary)[:600]
    if len(summary) == 600 and summary[-1] not in '. ,!?':
        summary = summary.rsplit(' ', 1)[0] + '...'
    link = article.link.strip()
    source = get_source_name(article.feed_url).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"<b>{title}</b>"
    if summary:
        html += f"\n\n{summary}"
    html += "\n\n"
    if link and (link.startswith("http://") or link.startswith("https://")):
        safe_link = link.replace('"', "&quot;")
        html += f"<i><a href=\"{safe_link}\">{source}</a></i>"
    else:
        html += f"<i>{source}</i>"
    return html
