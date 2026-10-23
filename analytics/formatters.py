# analytics/formatters.py
import json
import re
from urllib.parse import urlparse
from typing import Dict

from .models import Article
from .text_utils import normalize_for_dedup


def load_source_names() -> Dict[str, str]:
    try:
        with open("sources.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


CANONICAL_NAMES = load_source_names()

EMOJIS = {
    "GEOPOLITICS": "🌍", "ECONOMICS": "📈", "BUSINESS": "💼",
    "TECHNOLOGY": "💻", "ENERGY": "⚡", "SECURITY": "🛡️",
}
NAMES = {
    "GEOPOLITICS": "ГЕОПОЛИТИКА", "ECONOMICS": "ЭКОНОМИКА", "BUSINESS": "БИЗНЕС",
    "TECHNOLOGY": "ТЕХНОЛОГИИ И ИННОВАЦИИ", "ENERGY": "ЭНЕРГЕТИКА И РЕСУРСЫ",
    "SECURITY": "БЕЗОПАСНОСТЬ И КОНФЛИКТЫ",
}

_EXTRA_TITLE_SUFFIXES = [
    "Council on Foreign Relations", "Center for Strategic and International Studies",
    "CSIS |Центр стратегических и международных исследований", "CSIS",
    "Chatham House", "Клуб «Валдай»", "Valdai Club", "МЭА", "IEA",
    "Stockholm International Peace Research Institute", "The Diplomat", "Foreign Affairs"
]


def clean_html(text: str) -> str:
    if not text:
        return ""
    # Удаляем скрипты и стили
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    # Удаляем ВСЕ html-теги
    text = re.sub(r"<[^>]+>", " ", text)
    # Раскодируем entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def post_process_text(text: str) -> str:
    if not text:
        return ""

    # 1. Пробел после знаков препинания
    text = re.sub(r"([.,!?;:])(?=[А-Яа-яЁёA-Za-z0-9])", r"\1 ", text)

    # Склейки строчная+Заглавная в кириллице
    text = re.sub(r"([а-яё])([А-ЯЁ])", r"\1 \2", text)
    text = re.sub(r"(\d)([А-ЯЁ])", r"\1 \2", text)
    text = re.sub(r"([а-яё])(\d)", r"\1 \2", text)

    # Убираем markdown-звездочки и решетки в начале
    text = re.sub(r"\*(?=\S)", " ", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"\s+#+\s+", " ", text)

    # WordPress-хвосты
    text = re.sub(r"\s*[Пп]ост\s+[^:]{1,200}:\s*", " ", text)
    text = re.sub(r"\s+[Пп]ост\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Пп]оявился\s+[Пп]ост\s+[^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Пп]убликация\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Сс]ообщение\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)

    # Убираем рекламу
    text = re.sub(r"Присоединяйтесь к War on the Rocks.*?(\.|$)", "", text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r"«?_CSIS Charts_?» создаётся.*?(\.|$)", "", text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r"Получайте доступ к контенту.*?(\.|$)", "", text, flags=re.IGNORECASE|re.DOTALL)

    # Jamestown
    text = re.sub(r"\s+The\s+(?:Jamestown\s+Foundation)?\s*$", "", text)

    # U.S. -> US
    text = re.sub(r"\bU\.\s*S\.", "US", text)
    text = re.sub(r"\bU\.\s*K\.", "UK", text)

    # Точечные правки
    text = text.replace("Чик-фил-А", "Chick-fil-A")
    text = text.replace("пожарной безопасности", "огневой поддержки")

    # Пробел между латиницей и кириллицей
    text = re.sub(r"([a-zA-Z])([А-Яа-яЁё])", r"\1 \2", text)
    text = re.sub(r"([А-Яа-яЁё])([a-zA-Z])", r"\1 \2", text)

    # Схлопываем пробелы
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)

    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def strip_source_suffix_from_title(title: str, source_name: str = "") -> str:
    if not title:
        return title
    all_names = list(_EXTRA_TITLE_SUFFIXES)
    if source_name:
        all_names.append(source_name)
    all_names.extend(set(CANONICAL_NAMES.values()))

    for name in all_names:
        if not name or len(name) < 3:
            continue
        esc = re.escape(name)
        title = re.sub(rf"[?!.,]?\s*[-–—|:]\s*{esc}\s*\.?\s*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(rf"\s+{esc}\s*\.?\s*$", "", title, flags=re.IGNORECASE).strip()
    return title.strip()


def remove_title_from_summary(title: str, summary: str) -> str:
    if not title or not summary:
        return summary
    t_norm = " ".join(re.sub(r"[^\w\s]", " ", title.lower()).split())
    s_norm = " ".join(re.sub(r"[^\w\s]", " ", summary.lower()).split())
    t_words = t_norm.split()
    s_words = s_norm.split()

    matched = 0
    for tw, sw in zip(t_words, s_words):
        if tw == sw: matched += 1
        else: break

    if matched >= max(3, len(t_words) * 0.6):
        wc = 0
        pos = 0
        for i, ch in enumerate(summary):
            if i == 0 or summary[i - 1].isspace(): wc += 1
            if wc > matched:
                pos = i
                break
        if pos > 0:
            remainder = summary[pos:].lstrip(' .,:;-–—?!«»"\'')
            if len(remainder) > 40:
                summary = remainder
    return summary


def strip_trailing_source(text: str, source_name: str) -> str:
    if not text or not source_name:
        return text
    pattern = r"[\s\-–—.,:]*" + re.escape(source_name) + r"\s*[.!?]*\s*$"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


def truncate_at_sentence(text: str, max_len: int = 900) -> str:
    if not text: return ""
    if len(text) <= max_len: return text
    cut = text[:max_len]
    matches = list(re.finditer(r"[.!?](?:\s|$)", cut))
    if matches:
        last_end = matches[-1].end()
        if last_end >= max_len * 0.4:
            return cut[:last_end].strip()
    last_space = cut.rfind(" ")
    if last_space >= max_len * 0.4:
        return cut[:last_space].rstrip(" ,;:—–-")
    return cut.rstrip()


def get_source_name(feed_url: str) -> str:
    for domain, name in CANONICAL_NAMES.items():
        if domain in feed_url: return name
    try:
        return urlparse(feed_url).netloc.replace("www.", "").split("/")[0]
    except Exception:
        return feed_url


def get_category_emoji(category: str) -> str:
    return EMOJIS.get(category, "📌")


def get_category_russian_name(category: str) -> str:
    return NAMES.get(category, category)


def is_junk_article(article: Article) -> bool:
    title = article.title or ""
    text = (title + " " + (article.summary or "")).lower()
    t_lower = title.strip().lower()

    # Мусорные страницы
    JUNK_WORDS = ["корзина", "bookstore", "книжный магазин", "база данных", "database",
                  "values.php", "armtrade", "login", "sign in", "sign up", "privacy policy",
                  "search results", "страница поиска", "представлено", "presented by"]
    if any(w in t_lower for w in JUNK_WORDS): return True
    if re.search(r"\.(com|org|ru|net|info|io|php|gov|edu)\b", t_lower): return True

    # Подкасты
    if re.search(r"\b(podcast|подкаст|audio|аудио|episode|эпизод|webinar|вебинар)\b", text): return True

    # Выпуски
    if re.match(r"^(volume|vol\.|том|issue|выпуск)\s+\d+", t_lower): return True

    # Имена
    words = title.strip().split()
    if 2 <= len(words) <= 3 and len(title.strip()) < 45:
        clean_words = ["X" if re.match(r"^[А-ЯЁA-Z]\.$", w) else w for w in words]
        if all(w[0].isupper() for w in clean_words if w and w[0].isalpha()):
            if not any(re.search(r"[.,:;!?\-–—()«»&/]", w) for w in clean_words) and not re.search(r"\d", title):
                return True
    return False


def article_to_html(article: Article, cache: dict) -> str:
    # Защита от пустых карточек
    if not article.title or len(article.title.strip()) < 3:
        return ""

    cached = cache.get(normalize_for_dedup(article.title), {})
    title = cached.get("translated_title", article.title)
    summary = cached.get("translated_summary", article.summary)

    title = post_process_text(clean_html(title))
    summary = post_process_text(clean_html(summary))

    source = get_source_name(article.feed_url)
    title = strip_source_suffix_from_title(title, source)
    summary = remove_title_from_summary(title, summary)
    summary = strip_trailing_source(summary, source)
    summary = truncate_at_sentence(summary, max_len=900)

    if summary and title and summary.strip().lower() == title.strip().lower():
        summary = ""

    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    summary = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    source_html = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    link = article.link.strip()
    html = f"<b>{title}</b>"
    if summary:
        html += f"\n\n{summary}\n\n"
    else:
        html += "\n\n"

    if link and (link.startswith("http://") or link.startswith("https://")):
        safe_link = link.replace('"', "&quot;")
        html += f'<i><a href="{safe_link}">{source_html}</a></i>'
    else:
        html += f"<i>{source_html}</i>"
    return html
