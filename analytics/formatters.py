# analytics/formatters.py
import json
import re
from urllib.parse import urlparse
from typing import Dict

from .models import Article


def load_source_names() -> Dict[str, str]:
    try:
        with open("sources.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


CANONICAL_NAMES = load_source_names()

_MONTHS_RU = (
    r"января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря"
)


def clean_html(text: str) -> str:
    """Очищает HTML-теги и атрибуты."""
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "img", "figure", "iframe"]):
            tag.decompose()
        text = soup.get_text()
    except Exception:
        text = re.sub(r"<[^>]+>", "", text)

    text = re.sub(r"<[^>]*>?", "", text)
    text = re.sub(r'target\s*=\s*"_blank"', "", text)
    text = re.sub(r'href\s*=\s*"[^"]*"', "", text)
    text = re.sub(r"\s+", " ", text)
    replacements = {
        "&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"',
        "&#39;": "'", "&nbsp;": " ", "&#8217;": "'",
        "&#8220;": '"', "&#8221;": '"', "&#8211;": "–", "&#8212;": "—",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.strip()


def post_process_text(text: str) -> str:
    """Постобработка: чинит артефакты RSS и перевода."""
    if not text:
        return ""

    # 1. Пробел после знаков препинания перед буквой
    text = re.sub(r"([.,!?;:])(?=[А-Яа-яЁёA-Za-z])", r"\1 ", text)

    # 2. WordPress-хвосты (обоих родов)
    text = re.sub(r"\s*[Пп]ост\s+[^:]{1,200}:\s*", " ", text)
    text = re.sub(
        r"\s*[Пп]убликация\s+[^.]{0,200}?\s+впервые\s+появил(?:ась|ся)\s+на\s+сайте\s+[^.]+\.?\s*$",
        "", text,
    )
    text = re.sub(
        r"\s*впервые\s+появил(?:ась|ся)\s+на\s+сайте\s+[^.]+\.?\s*$",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*The\s+post\s+.+?\s+appeared\s+first\s+on\s+[^.]+\.?\s*$",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*This\s+post\s+.+?\s+appeared\s+first\s+on\s+[^.]+\.?\s*$",
        "", text, flags=re.IGNORECASE,
    )

    # 3. "Комментарий эксперта <Имя> <Дата>"
    text = re.sub(
        r"Комментарий\s+эксперта\s+.{0,80}?\d{1,2}\s+(?:" + _MONTHS_RU + r")\s+\d{4}\s*г?\.?",
        "", text, flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"Комментарий\s+эксперта\s+[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z][а-яёa-z]+\s*",
        "", text, flags=re.IGNORECASE,
    )
    # Отдельные даты формата "10 сентября 2026 г." в начале
    text = re.sub(
        r"^\s*\d{1,2}\s+(?:" + _MONTHS_RU + r")\s+\d{4}\s*г?\.\s*",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*Expert\s+Comment\s+by\s+[^.?!]{1,80}[.?!]?\s*",
        " ", text, flags=re.IGNORECASE,
    )

    # 4. Артефакты Google News
    text = re.sub(r"<а\s*href[^>]*>", "", text)
    text = re.sub(r"<a\s*href[^>]*>", "", text)
    text = re.sub(r'target\s*=\s*"_blank"\s*>?', "", text)
    text = re.sub(r"<изображение[^>]*>?", "", text)
    text = re.sub(r"\bаль\b\s*", " ", text)
    text = re.sub(r"<[^>]*>?", "", text)

    # 5. Маркеры обрезки [ … ] и […]
    text = re.sub(r"\s*\[\s*…\s*\]\s*", " ", text)
    text = re.sub(r"\s*\[\s*\.\.\.\s*\]\s*", " ", text)
    text = re.sub(r"\s*\[\s*…\s*\]", " ", text)

    # 6. Пробел между латиницей и кириллицей при склейке
    text = re.sub(r"([a-zA-Z])([А-Яа-яЁё])", r"\1 \2", text)
    text = re.sub(r"([А-Яа-яЁё])([a-zA-Z])", r"\1 \2", text)

    # 7. Нормализация имён собственных
    text = text.replace("Брейгель", "Bruegel").replace("Брюгель", "Bruegel")
    text = re.sub(r"Carbon\s*Кратко", "Carbon Brief", text)
    text = re.sub(r"CarbonКратко", "Carbon Brief", text)

    # 8. Лишние пробелы и знаки
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([.,!?;:])\1+", r"\1", text)

    return text.strip()


def remove_title_from_summary(title: str, summary: str) -> str:
    """Если summary начинается с заголовка — убирает его."""
    if not title or not summary:
        return summary

    t = title.strip().rstrip("?!.:;, ")
    if len(t) < 15:
        return summary

    def norm(s):
        return re.sub(r"[^\w\s]", "", s.lower()).strip()

    t_n = " ".join(norm(t).split())
    s_n = " ".join(norm(summary).split())
    if not t_n or not s_n:
        return summary

    t_check = t_n[:60]
    if not s_n.startswith(t_check[: min(30, len(t_check))]):
        return summary

    t_words = t_n.split()
    s_words = s_n.split()
    matched = 0
    for tw, sw in zip(t_words, s_words):
        if tw == sw:
            matched += 1
        else:
            break

    if matched < len(t_words) * 0.7:
        return summary

    word_count = 0
    pos = 0
    for i, ch in enumerate(summary):
        if i == 0 or summary[i - 1].isspace():
            word_count += 1
        if word_count > matched:
            pos = i
            break

    if pos > 0:
        remainder = summary[pos:].lstrip(' .,:;-–—?!«»"\'')
        if len(remainder) > 40:
            return remainder

    return summary


def remove_title_from_summary(title: str, summary: str) -> str:
    """Если summary начинается с заголовка (или его части) — убирает его."""
    if not title or not summary:
        return summary

    def norm(s):
        return re.sub(r"[^\w\s]", " ", s.lower())

    t_n = " ".join(norm(title).split())
    s_n = " ".join(norm(summary).split())
    if not t_n or not s_n:
        return summary

    t_words = t_n.split()
    s_words = s_n.split()

    # Ищем максимальное совпадение слов в начале
    matched = 0
    for tw, sw in zip(t_words, s_words):
        if tw == sw:
            matched += 1
        else:
            break

    # Если совпало больше 60% слов заголовка — убираем
    if matched < max(3, len(t_words) * 0.6):
        return summary

    # Находим позицию в оригинальном summary после matched слов
    word_count = 0
    pos = 0
    for i, ch in enumerate(summary):
        if i == 0 or summary[i - 1].isspace():
            word_count += 1
        if word_count > matched:
            pos = i
            break

    if pos > 0:
        remainder = summary[pos:].lstrip(' .,:;-–—?!«»"\'')
        if len(remainder) > 40:
            return remainder

    return summary


def strip_source_suffix_from_title(title: str, source_name: str) -> str:
    """Убирает название источника из заголовка (суффикс через тире, пайп, двоеточие)."""
    if not title or not source_name:
        return title
    escaped = re.escape(source_name)
    patterns = [
        rf"\s*[-–—|]\s*{escaped}\s*$",
        rf"\s*:\s*{escaped}\s*$",
        rf"\s+{escaped}\s*$",
    ]
    for p in patterns:
        title = re.sub(p, "", title, flags=re.IGNORECASE).strip()
    # Дополнительно: полные варианты названий для Google News
    extra_names = [
        "Council on Foreign Relations", "Council on Foreign Relations (CFR)",
        "Совет по международным отношениям",
    ]
    for name in extra_names:
        title = re.sub(rf"\s*[-–—|:]\s*{re.escape(name)}\s*$", "", title, flags=re.IGNORECASE).strip()
    return title


def strip_trailing_source(text: str, source_name: str) -> str:
    """Убирает название источника в конце текста."""
    if not text or not source_name:
        return text
    pattern = r"[\s\-–—.,:]*" + re.escape(source_name) + r"\s*[.!?]*\s*$"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def truncate_at_sentence(text: str, max_len: int = 600) -> str:
    """Обрезает текст до последнего целого предложения."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text

    cut = text[:max_len]

    matches = list(re.finditer(r"[.!?](?:\s|$)", cut))
    if matches:
        last_end = matches[-1].end()
        if last_end >= max_len * 0.5:
            return cut[:last_end].strip()

    last_space = cut.rfind(" ")
    if last_space >= max_len * 0.5:
        result = cut[:last_space].rstrip(" ,;:—–-")
        return result + "…"

    return cut.rstrip() + "…"


def get_source_name(feed_url: str) -> str:
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
        "GEOPOLITICS_WORLD": "🌍", "GEOPOLITICS_RUSSIA": "🇷🇺",
        "ECONOMICS_WORLD": "📈", "ECONOMICS_RUSSIA": "📊",
        "TECHNOLOGY_WORLD": "💻", "TECHNOLOGY_RUSSIA": "🖥️",
        "ENERGY_WORLD": "⚡", "ENERGY_RUSSIA": "🔋",
        "SECURITY_WORLD": "🛡️", "SECURITY_RUSSIA": "⚔️",
        "PR_WORLD": "📢", "PR_RUSSIA": "📣",
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

    title = post_process_text(clean_html(title))
    summary = post_process_text(clean_html(summary))

    source = get_source_name(article.feed_url)

    title = strip_source_suffix_from_title(title, source)
    summary = remove_title_from_summary(title, summary)
    summary = strip_trailing_source(summary, source)

    summary = truncate_at_sentence(summary, max_len=600)

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
