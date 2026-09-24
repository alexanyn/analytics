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

_MONTHS_RU = (
    r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|"
    r"сентябр|октябр|ноябр|декабр"
)

EMOJIS = {
    "GEOPOLITICS": "🌍", "ECONOMICS": "📈", "BUSINESS": "💼",
    "TECHNOLOGY": "💻", "ENERGY": "⚡", "SECURITY": "🛡️",
}

NAMES = {
    "GEOPOLITICS": "ГЕОПОЛИТИКА",
    "ECONOMICS": "ЭКОНОМИКА",
    "BUSINESS": "БИЗНЕС",
    "TECHNOLOGY": "ТЕХНОЛОГИИ И ИННОВАЦИИ",
    "ENERGY": "ЭНЕРГЕТИКА И РЕСУРСЫ",
    "SECURITY": "БЕЗОПАСНОСТЬ И КОНФЛИКТЫ",
}

# Расширенный список суффиксов, которые добавляют RSS-агрегаторы
_EXTRA_TITLE_SUFFIXES = [
    "Council on Foreign Relations",
    "Council on Foreign Relations (CFR)",
    "Совет по международным отношениям",
    "Peterson Institute for International Economics",
    "Center for Strategic and International Studies",
    "Center for Strategic & International Studies",
    "CSIS |Центр стратегических и международных исследований",
    "CSIS | Центр стратегических и международных исследований",
    "CSIS",
    "Chatham House",
    "ЦСМИ",
    "Институт изучения войны",
    "Institute for the Study of War",
    "Фонд Джеймстауна",
    "Jamestown Foundation",
    "The New York Times",
    "The Washington Post",
    "The Wall Street Journal",
    "Financial Times",
    "The Economist",
    "Bloomberg",
    "Reuters",
    "Associated Press",
    "MIT Technology Review",
    "Project Syndicate",
    "War on the Rocks",
    "World Politics Review",
    "Foreign Affairs",
    "The Diplomat",
    "RAND Corporation",
    "Carnegie Endowment",
    "Brookings Institution",
    "Bruegel",
    "ECFR",
    "SWP Berlin",
    "DGAP",
    "MERICS",
    "OSW",
    "PONARS Eurasia",
    "Russia in Global Affairs",
    "Valdai Club",
    "Ragan Communications",
    "PR Daily",
    "PRovoke Media",
    "Spin Sucks",
    "O'Dwyer's",
    "Carbon Brief",
    "BloombergNEF",
    "IEA",
    "Oxford Institute for Energy Studies",
    "Wood Mackenzie",
]

_DOMAIN_TLD = r"(?:com|org|net|ru|io|edu|gov|uk|de|fr|pl|cn|jp|info|eu|co)"


def clean_html(text: str) -> str:
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
    if not text:
        return ""

    text = re.sub(r"([.,!?;:])(?=[А-Яа-яЁёA-Za-z])", r"\1 ", text)

    # WordPress-хвосты
    text = re.sub(r"\s*[Пп]ост\s+[^:]{1,200}:\s*", " ", text)
    text = re.sub(r"\s+[Пп]ост\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Пп]оявился\s+[Пп]ост\s+[^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Пп]убликация\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)
    text = re.sub(r"\s+[Сс]ообщение\s+[А-ЯЁA-Z][^.!?]{5,250}\s*$", " ", text)
    text = re.sub(
        r"\s*[Пп]убликация\s+[^.]{0,200}?\s+впервые\s+появил(?:ась|ся)\s+на\s+сайте\s+[^.]+\.?\s*$",
        " ", text,
    )
    text = re.sub(
        r"\s*[Сс]ообщение\s+.+?\s+впервые\s+появил(?:ась|ся)\s+на\s+сайте.*$",
        " ", text, flags=re.DOTALL,
    )
    text = re.sub(
        r"\s*впервые\s+появил(?:ась|ся)\s+на\s+сайте\s+[^.]+\.?\s*$",
        " ", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*[A-Za-z]+\s+post\s+.+?\s+appeared\s+first\s+on\s+[^.]+\.?\s*$",
        " ", text, flags=re.IGNORECASE,
    )

    # Event-маркеры
    text = re.sub(r"\s*Анонимно\s*\(\s*не\s+проверено\s*\)\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*Anonymous\s*\(\s*not\s+verified\s*\)\s*", " ", text, flags=re.IGNORECASE)

    # Дата + временной диапазон (анонсы)
    text = re.sub(
        r"\s*\d{1,2}\s+(?:" + _MONTHS_RU + r")[а-яё]*\s+\d{4}\s*г?\.?\s*"
        r"[-–—]?\s*с\s*\d{1,2}:\d{2}\s+до\s+\d{1,2}:\d{2}[^.]*\.",
        " ", text, flags=re.IGNORECASE,
    )

    # Хвостовые названия источников (RU + EN)
    text = re.sub(
        r"\s*Чатем[\s-]?Хаус\s*(?:Описание|и\s+Интернет|и\s+Интернет\.?)?\s*\.?\s*$",
        " ", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*Chatham\s+House\s+(?:Description|and\s+Internet)\s*\.?\s*$",
        " ", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*[-–—]?\s*(?:Фонд\s+Джеймстауна|Институт\s+изучения\s+войны|Jamestown\s+Foundation|Institute\s+for\s+the\s+Study\s+of\s+War)\s*\.?\s*$",
        " ", text, flags=re.IGNORECASE,
    )
    # "Тейлор рассказал Рэгану" и подобные концовки от PR Daily / Ragan
    text = re.sub(r"\s+\S+\s+рассказал\s+[А-ЯЁA-Z][а-яёa-z]+\s*\.?\s*$", " ", text)
    text = re.sub(r"\s+\S+\s+told\s+[A-Z][a-z]+\s*\.?\s*$", " ", text)

    # Jamestown-специфика
    text = re.sub(r"^\s*Краткое\s+содержание:\s*", "", text)
    text = re.sub(r"\s*\(\s*[A-ZА-ЯЁ][\w\-]{1,15}\s+Пост\s*$", " ", text)
    text = re.sub(r"\s+Пост\s*$", " ", text)

    # HTML артефакты
    text = re.sub(r"<а\s*href[^>]*>", "", text)
    text = re.sub(r"<a\s*href[^>]*>", "", text)
    text = re.sub(r'target\s*=\s*"_blank"\s*>?', "", text)
    text = re.sub(r"<изображение[^>]*>?", "", text)
    text = re.sub(r"\bаль\b\s*", " ", text)
    text = re.sub(r"<[^>]*>?", "", text)

    # Маркеры обрезки
    text = re.sub(r"\s*\[\s*(?:…|\.\.\.)\s*\]\s*", " ", text)

    # Пробел между латиницей и кириллицей
    text = re.sub(r"([a-zA-Z])([А-Яа-яЁё])", r"\1 \2", text)
    text = re.sub(r"([А-Яа-яЁё])([a-zA-Z])", r"\1 \2", text)

    # Тире без пробелов
    text = re.sub(r"([А-Яа-яЁёA-Za-z])[–—]([А-ЯЁA-Z])", r"\1 — \2", text)

    # Нормализация имён
    text = text.replace("Брейгель", "Bruegel").replace("Брюгель", "Bruegel")
    text = re.sub(r"Carbon\s*Кратко", "Carbon Brief", text)
    text = re.sub(r"CarbonКратко", "Carbon Brief", text)
    text = text.replace("пожарной безопасности", "огневой поддержки")

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([.,!?;:])\1+", r"\1", text)

    # Markdown-артефакты от Gemini
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)   # **bold** → bold
    text = re.sub(r"__(.+?)__", r"\1", text)         # __italic__
    text = re.sub(r"\*(.+?)\*", r"\1", text)         # *italic*
    text = re.sub(r"`(.+?)`", r"\1", text)           # `code`
    text = re.sub(r"^#+\s*", "", text)               # # header

    # Транслитерация в скобках: (Privet, mir!)
    text = re.sub(r"\s*\([A-Z][a-z]+(?:[,\s]+[a-z]+)+\)", "", text)

    text = text.strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def strip_source_suffix_from_title(title: str, source_name: str = "") -> str:
    """Убирает суффикс источника из заголовка."""
    if not title:
        return title

    # Собираем все известные названия
    all_names = list(_EXTRA_TITLE_SUFFIXES)
    if source_name:
        all_names.append(source_name)
    all_names.extend(set(CANONICAL_NAMES.values()))

    # Убираем каждый известный суффикс
    for name in all_names:
        if not name or len(name) < 3:
            continue
        esc = re.escape(name)
        # С разделителем
        title = re.sub(rf"[?!.,]?\s*[-–—|:]\s*{esc}\s*\.?\s*$", "", title, flags=re.IGNORECASE).strip()
        # С пробелом в конце (без разделителя)
        title = re.sub(rf"\s+{esc}\s*\.?\s*$", "", title, flags=re.IGNORECASE).strip()

    # Универсально: " - Xxx Yyy Zzz" — 2-6 слов с заглавных
    title = re.sub(
        r"[?!.,]?\s*[-–—]\s+[A-ZА-ЯЁ][a-zа-яё]+"
        r"(?:\s+[A-ZА-ЯЁ][a-zа-яё]+){0,5}\.?\s*$",
        "", title,
    ).strip()

    # CSIS-стиль: "CSIS |Центр..."
    title = re.sub(
        r"\s*[-–—|]?\s*[A-ZА-ЯЁ][^|]{1,80}\|.{0,120}$",
        "", title,
    ).strip()

    # Домены: " - features. csis. org"
    title = re.sub(
        r"\s*[-–—]\s*[A-Za-zА-ЯЁа-яё0-9\s\.]{1,60}\b" + _DOMAIN_TLD + r"\s*$",
        "", title, flags=re.IGNORECASE,
    ).strip()

    return title.strip()


def remove_title_from_summary(title: str, summary: str) -> str:
    """Если summary начинается с заголовка или содержит его — убирает дубль."""
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

    # Совпадение в начале
    matched = 0
    for tw, sw in zip(t_words, s_words):
        if tw == sw:
            matched += 1
        else:
            break

    if matched >= max(3, len(t_words) * 0.6):
        wc = 0
        pos = 0
        for i, ch in enumerate(summary):
            if i == 0 or summary[i - 1].isspace():
                wc += 1
            if wc > matched:
                pos = i
                break
        if pos > 0:
            remainder = summary[pos:].lstrip(' .,:;-–—?!«»"\'')
            if len(remainder) > 40:
                summary = remainder

    # Совпадение в конце
    summary_n = " ".join(norm(summary).split())
    if t_n in summary_n and len(t_words) >= 4:
        words = summary.split()
        n = len(words)
        tw_count = len(t_words)
        for i in range(max(0, n - tw_count - 5), n):
            candidate = " ".join(norm(" ".join(words[i:])).split())
            if candidate.startswith(t_n[:40]):
                summary = " ".join(words[:i]).rstrip(" .,:;-–—")
                break

    return summary


def strip_trailing_source(text: str, source_name: str) -> str:
    if not text or not source_name:
        return text
    pattern = r"[\s\-–—.,:]*" + re.escape(source_name) + r"\s*[.!?]*\s*$"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def truncate_at_sentence(text: str, max_len: int = 600) -> str:
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
        return cut[:last_space].rstrip(" ,;:—–-") + "…"
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
    return EMOJIS.get(category, "📌")


def get_category_russian_name(category: str) -> str:
    return NAMES.get(category, category)


def is_junk_article(article: Article) -> bool:
    """Отсеивает анонсы, тесты и статьи-однофамильцы."""
    title = article.title or ""
    text = (title + " " + (article.summary or "")).lower()
    t_stripped = title.strip()

    # Тесты
    if re.match(r"^(?:отсечной|контрольный)\s+тест\b", t_stripped.lower()):
        return True
    if re.match(r"^(?:cutoff|control)\s+test\b", t_stripped.lower()):
        return True

    # Анонсы с датой+временем
    has_time = re.search(r"\d{1,2}:\d{2}\s*(?:[-–—]|до)\s*\d{1,2}:\d{2}", text)
    has_date = re.search(
        r"\d{1,2}\s+(?:" + _MONTHS_RU + r")[а-яё]*\s+\d{4}", text, flags=re.IGNORECASE,
    )
    if has_time and has_date:
        return True

    # Серии
    if re.match(r"^серия\s+[«\"]", t_stripped.lower()):
        return True

    if "анонимно (не проверено)" in text or "anonymous (not verified)" in text:
        return True
    if "чатем-хаус и интернет" in text or "chatham house and internet" in text:
        return True

    # Заголовок — только имя автора (2-3 слова, все с заглавной, без глаголов и пунктуации)
    words = t_stripped.split()
    if 2 <= len(words) <= 3 and len(t_stripped) < 40:
        if all(w[0].isupper() for w in words if w):
            if not re.search(r"[.,:;!?\-–—]", t_stripped):
                # Нет глагольных маркеров
                if not re.search(r"\b(?:is|are|was|were|has|have|will|can|about|over|with|from|of|in|on|to)\b", t_stripped.lower()):
                    return True

    return False


def article_to_html(article: Article, cache: dict) -> str:
    cached = cache.get(normalize_for_dedup(article.title), {})
    title = cached.get("translated_title", article.title)
    summary = cached.get("translated_summary", article.summary)

    title = post_process_text(clean_html(title))
    summary = post_process_text(clean_html(summary))

    source = get_source_name(article.feed_url)

    title = strip_source_suffix_from_title(title, source)
    summary = remove_title_from_summary(title, summary)
    summary = strip_trailing_source(summary, source)
    summary = truncate_at_sentence(summary, max_len=600)

    # Если summary на английском — убираем полностью (не показываем английский текст)
    if summary and len(summary) > 20:
        latin = sum(1 for c in summary if "a" <= c.lower() <= "z")
        cyr = sum(1 for c in summary if "а" <= c.lower() <= "я" or c == "ё")
        total = max(len(summary), 1)
        if latin / total > 0.7 and cyr / total < 0.15:
            summary = ""

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
