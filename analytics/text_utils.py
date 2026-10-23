"""text_utils.py — RSS, Google News, Jina Reader, очистка, фильтры мусора, классификация."""
from __future__ import annotations
import html, logging, os, re, threading, time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse
import feedparser, requests

log = logging.getLogger("analytics")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
JINA_BASE = "https://r.jina.ai/"
CATEGORIES = ["Геополитика", "Экономика", "Бизнес", "Технологии", "Энергетика", "Безопасность"]
MIN_DESC_LEN = 30

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CYR_RE = re.compile(r"[а-яёА-ЯЁ]")
_LAT_RE = re.compile(r"[a-zA-Z]")
_LITERAL_ESC_RE = re.compile(r"\\[nrt]")

def clean_html(text) -> str:
    if not text: return ""
    text = str(text)
    text = _LITERAL_ESC_RE.sub(" ", text)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()

_TAIL_PATTERNS = [
    re.compile(r"\s*(?:Статья|Пост|Публикация|Сообщение|Запись)\s+[«\"“„'].{0,400}?[»\"”“'’]?\s*(?:впервые|первым)\b.*$", re.I | re.S),
    re.compile(r"\s*The (?:post|article)\b.{0,400}?\b(?:first\s+)?appeared\s+(?:first\s+)?on\b.*$", re.I | re.S),
    re.compile(r"\s*(?:Читать далее|Read more|Continue reading)\b.{0,80}$", re.I | re.S),
    re.compile(r"\s*\[\s*(?:…|\.\.\.|&#8230;|&hellip;)\s*\]\s*$"),
]

def post_process_text(text) -> str:
    t = clean_html(text)
    if not t: return ""
    for p in _TAIL_PATTERNS: t = p.sub("", t)
    t = re.sub(r"\[\s*EN\s*\]", "", t, flags=re.I)
    return _WS_RE.sub(" ", t).strip(" \t-–—|")

def has_cyrillic(text: str) -> bool: return bool(_CYR_RE.search(text or ""))
def is_russian(text: str) -> bool:
    if not text: return False
    cyr, lat = len(_CYR_RE.findall(text)), len(_LAT_RE.findall(text))
    return cyr > 0 and cyr >= lat * 2

SOURCE_NAMES = [
    "European", "Европейский", "European Council on Foreign Relations", "Европейский совет по международным отношениям", "ECFR",
    "CSIS", "Center for Strategic and International Studies", "Centre for Strategic and International Studies",
    "Центр стратегических и международных исследований", "Chatham House", "Чатем-Хаус",
    "CEPR", "Centre for Economic Policy Research", "Центр исследований экономической политики",
    "IEA", "МЭА", "МЭА - Международное энергетическое агентство", "МЭА — Международное энергетическое агентство",
    "Международное энергетическое агентство", "International Energy Agency", "Carbon Brief", "PR Daily", "Spin Sucks",
    "Brookings", "Brookings Institution", "Carnegie Endowment for International Peace", "Reuters", "Bloomberg", "Financial Times", "The Economist",
]

@lru_cache(maxsize=64)
def _suffix_re(extra: str):
    names = {n for n in SOURCE_NAMES if n}
    if extra: names.add(extra)
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    sep = r"(?:\s+[-–—•·]\s+|\s*\|\s*|\s*::\s*)"
    return re.compile(rf"{sep}(?:{alt})\s*[.…]?\s*$", re.I)

def strip_source_suffix(title: str, source_name: str = "") -> str:
    t = clean_html(title)
    rx = _suffix_re((source_name or "").strip())
    for _ in range(3):
        n = rx.sub("", t).strip()
        if not n or n == t: break
        t = n
    return t

def is_source_only(desc: str, source_name: str = "") -> bool:
    d = (desc or "").lower()
    names = {n.lower() for n in SOURCE_NAMES}
    if source_name: names.add(source_name.lower())
    for n in sorted(names, key=len, reverse=True): d = d.replace(n, " ")
    d = re.sub(r"[\W_]+", " ", d).strip()
    return len(d) < 15

def is_weak_description(desc: str, source_name: str = "") -> bool:
    d = clean_html(desc)
    if len(d) < MIN_DESC_LEN: return True
    if is_source_only(d, source_name): return True
    return False

_STRICT_RE = re.compile(r"\b(?:GMT|UTC|BST)\b|аноним\w*\s*\(\s*не\s+подтвержд\w*\s*\)|anonymous\s*\(\s*unverified\s*\)", re.I)
_SOFT_RE = re.compile(r"онлайн|\bonline (?:event|webinar|briefing|session|panel)|вебинар|\bwebinar", re.I)

def is_generic_description(text: str, strict_only: bool = False) -> bool:
    if not text: return False
    head = text[:500]
    if _STRICT_RE.search(head): return True
    if strict_only: return False
    return bool(_SOFT_RE.search(head))

_BAD_URL_PARTS = ("/author/", "/authors/", "/profile/", "/profiles/", "/people/", "/person/", "/cart/", "/search/", "/solr/", "/bookstore/")

def is_non_article(url: str, title: str = "", split_site: bool = False) -> bool:
    u = (url or "").lower()
    if any(p in u for p in _BAD_URL_PARTS): return True

    t = title.strip()
    t_low = t.lower()
    
    # Отсекаем базы данных, корзины и поиск
    if "cart" in t_low or "корзина" in t_low or "solr" in t_low or "поиск" in t_low or "search" in t_low:
        return True
    if ".org" in t_low or ".com" in t_low or "база данных" in t_low:
        return True

    # Отсекаем профили авторов (2-3 слова с заглавной буквы)
    words = t.split()
    if 2 <= len(words) <= 3:
        if all(w[0].isupper() for w in words if w and w[0].isalpha()):
            if not re.search(r"[0-9:;,!?\"«»()—–|]", t):
                return True

    return False

_gn_lock = threading.Lock()
def is_google_news(url: str) -> bool: return "news.google.com" in (url or "")
def decode_google_news_url(url: str) -> str:
    if not is_google_news(url): return url
    try:
        from googlenewsdecoder import gnewsdecoder
        with _gn_lock: res = gnewsdecoder(url, interval=0.5)
        if isinstance(res, dict) and res.get("status") and res.get("decoded_url"): return res["decoded_url"]
    except Exception: pass
    return url

_BLOCK_RE = re.compile(r"just a moment|enable javascript|access denied|attention required|verify you are human|captcha|returned error (4|5)\d\d|checking your browser", re.I)
def _is_blocked(raw: str) -> bool: return bool(_BLOCK_RE.search(raw[:1000])) and len(raw) < 4000

def extract_jina_title(raw: str) -> str:
    m = re.search(r"^Title:\s*(.+)$", raw or "", re.M)
    return clean_html(m.group(1)) if m else ""

def extract_article_text(raw: str, max_chars: int = 3000) -> str:
    if not raw or _is_blocked(raw): return ""
    body = raw.split("Markdown Content:", 1)[-1]
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"https?://\S+", "", body)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body)]
    good = [p for p in paragraphs if len(p) >= 80 and not p.startswith(("#", "|", "*", "-", "["))]
    text = " ".join(good) if good else " ".join(paragraphs)
    return _WS_RE.sub(" ", text).strip()[:max_chars]

def fetch_via_jina(url: str, timeout: int = 40) -> tuple:
    key = os.environ.get("JINA_API_KEY", "").strip()
    headers = {"User-Agent": UA, "Accept": "text/plain", "X-Return-Format": "markdown", "X-Timeout": "25"}
    if key: headers["Authorization"] = f"Bearer {key}"
    for attempt in range(2):
        try:
            r = requests.get(JINA_BASE + url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                raw = r.text
                if _is_blocked(raw): return "", ""
                return extract_jina_title(raw), extract_article_text(raw)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            return "", ""
        except Exception: pass
    return "", ""

def _entry_dt(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t: return None
    try: return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception: return None

def fetch_feed(feed_url: str, timeout: int = 20):
    try:
        r = requests.get(feed_url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception: return None

def parse_entries(feed_url: str, name: str = "", hint: Optional[str] = None, max_entries: int = 15, max_age_hours: int = 72) -> list:
    feed = fetch_feed(feed_url)
    if not feed: return []
    now = datetime.now(timezone.utc)
    out = []
    for e in feed.entries[:max_entries]:
        try:
            title = clean_html(e.get("title"))
            link = (e.get("link") or "").strip()
            if not title or not link: continue
            published = _entry_dt(e)
            if published and (now - published).total_seconds() > max_age_hours * 3600: continue
            source = name
            if is_google_news(link):
                summary = ""
                src = e.get("source")
                if isinstance(src, dict) and src.get("title"): source = src["title"]
                suffix = f" - {source}" if source else ""
                if suffix and title.endswith(suffix): title = title[: -len(suffix)].strip()
                elif " - " in title: title = title.rsplit(" - ", 1)[0].strip()
            else:
                summary = post_process_text(e.get("summary") or e.get("description") or "")
                if not summary and e.get("content"): summary = post_process_text(e["content"][0].get("value", ""))
                if is_weak_description(summary, source) or is_generic_description(summary): summary = ""
            title = strip_source_suffix(title, source)
            if is_non_article(link, title): continue
            out.append({"title": title, "url": link, "summary": summary, "published": published, "source": source, "hint": hint})
        except Exception: pass
    return out

def title_tokens(title: str) -> frozenset: return frozenset(re.findall(r"\w+", (title or "").lower()))

def is_duplicate(tokens: frozenset, seen: list, threshold: float = 0.8) -> bool:
    if not tokens: return False
    for s in seen:
        if tokens == s: return True
        union = len(tokens | s)
        if union and len(tokens & s) / union >= threshold: return True
    return False

def host_of(url: str) -> str:
    try: return urlparse(url).netloc or url
    except Exception: return url

_ALIASES = [
    ("геополит", "Геополитика"), ("geopolit", "Геополитика"), ("политик", "Геополитика"), ("международ", "Геополитика"), ("world", "Геополитика"), ("russia", "Геополитика"),
    ("эконом", "Экономика"), ("финанс", "Экономика"), ("econom", "Экономика"), ("financ", "Экономика"),
    ("бизнес", "Бизнес"), ("business", "Бизнес"), ("маркет", "Бизнес"), ("market", "Бизнес"),
    ("технолог", "Технологии"), ("tech", "Технологии"), ("ии", "Технологии"), ("ai", "Технологии"),
    ("энерг", "Энергетика"), ("energy", "Энергетика"), ("нефт", "Энергетика"),
    ("безопас", "Безопасность"), ("secur", "Безопасность"), ("кибер", "Безопасность"), ("оборон", "Безопасность"), ("defen", "Безопасность"),
]
_EXACT = {"pr": "Бизнес", "коммуникации": "Бизнес", "communications": "Бизнес"}

KEYWORDS = {
    "Геополитика": ["санкц", "sanction", "nato", "нато", "переговор", "дипломат", "выбор", "election", "война", "war", "ukraine", "украин", "china", "китай", "russia", "россия", "евросоюз", "summit", "саммит", "treaty", "договор"],
    "Экономика": ["inflation", "инфляц", "gdp", "ввп", "central bank", "центробанк", "ключевая ставка", "interest rate", "recession", "рецесс", "tariff", "пошлин", "бюджет", "budget", "trade", "торгов", "currency", "валют", "рубл", "доллар", "dollar"],
    "Бизнес": ["merger", "слияни", "acquisition", "поглощен", "ipo", "earnings", "прибыл", "выручк", "revenue", "startup", "стартап", "ceo", "инвест", "invest", "company", "компани", "shares", "акци"],
    "Технологии": ["ai ", " ии", "искусственн", "openai", "nvidia", "chip", "чип", "semiconductor", "полупроводник", "software", "cloud", "облак", "robot", "робот", "quantum", "квант", "llm"],
    "Энергетика": ["oil", "нефт", "gas", "газ", "opec", "опек", "lng", "спг", "nuclear", "атом", "renewable", "возобновл", "solar", "солнечн", "электро", "энерг", "energy", "pipeline"],
    "Безопасность": ["cyber", "кибер", "attack", "атак", "hack", "взлом", "defense", "оборон", "military", "военн", "missile", "ракет", "drone", "дрон", "terror", "террор", "security", "безопасн", "ядерн", "эбола", "вирус", "intelligence", "разведк"],
}

def normalize_category(name: Optional[str]) -> Optional[str]:
    if not name: return None
    n = str(name).strip().lower()
    if n in _EXACT: return _EXACT[n]
    for cat in CATEGORIES:
        if n == cat.lower(): return cat
    for needle, cat in _ALIASES:
        if len(needle) <= 2:
            if n == needle: return cat
        elif needle in n: return cat
    return None

def classify(title: str, summary: str = "", hint: Optional[str] = None, extra: Optional[dict] = None) -> str:
    cat = normalize_category(hint)
    if cat: return cat
    text = f" {title} {summary} ".lower()
    kw = {c: list(w) for c, w in KEYWORDS.items()}
    for name, words in (extra or {}).items():
        c = normalize_category(name)
        if c and isinstance(words, list): kw[c] += [str(w).lower() for w in words if isinstance(w, str)]
    best, best_score = None, 0
    for c, words in kw.items():
        score = sum(1 for w in words if w in text)
        if score > best_score: best, best_score = c, score
    return best or "Геополитика"
