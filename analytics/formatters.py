# analytics/formatters.py
import json
import re
from urllib.parse import urlparse
from typing import Dict

from .models import Article


def load_source_names() -> Dict[str, str]:
    """Загружает канонические названия источников из sources.json."""
    try:
        with open("sources.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


CANONICAL_NAMES = load_source_names()


def clean_html(text: str) -> str:
    """Очищает HTML-теги и атрибуты из текста."""
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "img", "figure"]):
            tag.decompose()
        text = soup.get_text()
    except Exception:
        text = re.sub(r"<[^>]+>", "", text)

    # Остатки незакрытых тегов и атрибутов
    text = re.sub(r"<[^>]*>?", "", text)
    text = re.sub(r'target\s*=\s*"_blank"', "", text)
    text = re.sub(r'href\s*=\s*"[^"]*"', "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


def post_process_text(text: str) -> str:
    """Постобработка: чинит артефакты RSS и перевода."""
    if not text:
        return ""

    # 1. Пробел после знаков препинания перед буквой
    text = re.sub(r"([.,!?;:])(?=[А-Яа-яЁёA-Za-z])", r"\1 ", text)

    # 2. WordPress-хвосты (русская и английская версии)
    text = re.sub(r"\s*[Пп]ост\s+[^:]{1,200}:\s*", " ", text)
    text = re.sub(
        r"\s*впервые\s+появился\s+на\s+сайте\s+[^.]+\.?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*The\s+post\s+.+?\s+appeared\s+first\s+on\s+[^.]+\.?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 3. Фразы «Комментарий эксперта X» и англ. аналог
    text = re.sub(r"\s*Комментарий\s+эксперта\s+\S+\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*Expert\s+Comment\s+by\s+\S+\s*", " ", text, flags=re.IGNORECASE)

    # 4. HTML-артефакты Google News
    text = re.sub(r"<а\s*href[^>]*>", "", text)
    text = re.sub(r"<a\s*href[^>]*>", "", text)
    text = re.sub(r'target\s*=\s*"_blank"\s*>?', "", text)
    text = re.sub(r"<изображение[^>]*>?", "", text)
    text = re.sub(r"\bаль\b\s*", " ", text)
    text = re.sub(r"<[^>]*>?", "", text)

    # 5. Пробел между латиницей и кириллицей при склейке
    text = re.sub(r"([a-zA-Z])([А-Яа-яЁё])", r"\1 \2", text)
    text = re.sub(r"([А-Яа-яЁё])([a-zA-Z])", r"\1 \2", text)

    # 6. Нормализация имён собственных, которые Gemini коверкает
    text = text.replace("Брейгель", "Bruegel").replace("Брюгель", "Bruegel")
    text = re.sub(r"Carbon\s*Кратко", "Carbon Brief", text)
    text = re.sub(r"CarbonКратко", "Carbon Brief", text)

    # 7. Лишние пробелы и знаки
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([.,!?;:])\1+", r"\1", text)

    return text.strip()


def strip_trailing_source(text: str, source_name: str) -> str:
    """Убирает название источника в конце текста (оно и так идёт под текстом)."""
    if not text or not source_name:
        return text
    pattern = r"[\s\-–—.,:]*" + re.escape(source_name) + r"\s*[.!?]*\s*$"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def get_source_name(feed_url: str) -> str:
    """Возвращает каноническое название источника по URL фида."""
    for domain, name in CANONICAL_NAMES.items():
        if domain in feed_url:
            return name
    try:
        domain = urlparse(feed_url).netloc.replace("www.", "")
        return domain.split("/")[0]
    except Exception:
        return feed_url


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
    """Форматирует статью в HTML-блок для Telegram."""
    cached = cache.get(article.title, {})
    title = cached.get("translated_title", article.title)
    summary = cached.get("translated_summary", article.summary)

    title = post_process_text(clean_html(title))
    summary = post_process_text(clean_html(summary))

    source = get_source_name(article.feed_url)
    summary = strip_trailing_source(summary, source)

    summary = summary[:600]
    if len(summary) == 600 and summary[-1] not in ". ,!?":
        summary = summary.rsplit(" ", 1)[0] + "..."

    # Экранирование HTML
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    summary = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    source_html = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    link = article.link.strip()

    html = f"<b>{title}</b>"
    if summary:
        html += f"\n\n{summary}"
    html += "\n\n"
    if link and (link.startswith("http://") or link.startswith("https://")):
        safe_link = link.replace('"', "&quot;")
        html += f'<i><a href="{safe_link}">{source_html}</a></i>'
    else:
        html += f"<i>{source_html}</i>"
    return html
