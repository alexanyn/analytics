from __future__ import annotations
import json, logging, os, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import requests
try:
    from . import formatters, text_utils as tu, translators
except ImportError:
    import formatters, text_utils as tu, translators

log = logging.getLogger("analytics")
ROOT = Path(__file__).resolve().parent.parent
MAX_PER_CATEGORY = int(os.environ.get("MAX_PER_CATEGORY", "5"))
MAX_PER_SOURCE = int(os.environ.get("MAX_PER_SOURCE", "3"))
RESOLVE_WORKERS = int(os.environ.get("RESOLVE_WORKERS", "4"))
TRANSLATE_WORKERS = int(os.environ.get("TRANSLATE_WORKERS", "3"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
FALLBACK_DESC = "Подробности в источнике."

def _read_json(name: str, default):
    try: return json.loads((ROOT / name).read_text(encoding="utf-8"))
    except Exception: return default

def load_sources() -> list:
    config = _read_json("config.json", {})
    sources_map = _read_json("sources.json", {})
    out = []
    if isinstance(config, dict) and isinstance(config.get("rss_feeds"), list):
        for u in config["rss_feeds"]:
            name = ""
            for domain, n in sources_map.items():
                if domain in u:
                    name = n
                    break
            out.append({"url": u, "name": name, "category": None})
    return out

def load_extra_keywords() -> dict:
    data = _read_json("categories.json", {})
    if isinstance(data, dict) and isinstance(data.get("categories"), dict): data = data["categories"]
    if not isinstance(data, dict): return {}
    return {k: v for k, v in data.items() if isinstance(v, list) and all(isinstance(w, str) for w in v)}

def load_recent():
    data = _read_json("recent_titles.json", [])
    if isinstance(data, dict) and isinstance(data.get("titles"), list): return [str(t) for t in data["titles"]], "dict"
    if isinstance(data, list): return [t if isinstance(t, str) else str(t.get("title", "")) for t in data], "list"
    return [], "list"

def save_recent(titles: list, shape: str) -> None:
    titles = titles[-1000:]
    payload = {"titles": titles} if shape == "dict" else titles
    try: (ROOT / "recent_titles.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception: pass

def collect_articles(sources: list) -> list:
    def one(s):
        try: return tu.parse_entries(s["url"], s.get("name", ""), s.get("category"))
        except Exception: return []
    with ThreadPoolExecutor(max_workers=10) as ex: results = list(ex.map(one, sources))
    return [a for chunk in results for a in chunk]

def deduplicate(articles: list, recent_titles: list) -> list:
    seen = [tu.title_tokens(t) for t in recent_titles]
    out = []
    for a in articles:
        tok = tu.title_tokens(a["title"])
        if tu.is_duplicate(tok, seen): continue
        seen.append(tok); out.append(a)
    return out

def classify_articles(articles: list, extra_kw: dict) -> dict:
    floor = datetime.min.replace(tzinfo=timezone.utc)
    articles.sort(key=lambda a: a["published"] or floor, reverse=True)
    pool = {c: [] for c in tu.CATEGORIES}
    for a in articles:
        cat = tu.classify(a["title"], a["summary"], a.get("hint"), extra_kw)
        a["category"] = cat
        pool[cat].append(a)
    return pool

def resolve_article(a: dict) -> dict:
    a["source_text"] = ""
    a["origin"] = "title"
    try:
        if tu.is_google_news(a["url"]): a["url"] = tu.decode_google_news_url(a["url"])
        if tu.is_non_article(a["url"], a["title"]): a["drop"] = "не статья"; return a
        text = a.get("summary", "")
        if text: a["origin"] = "rss"
        elif not tu.is_google_news(a["url"]):
            j_title, j_text = tu.fetch_via_jina(a["url"])
            j_title = tu.strip_source_suffix(j_title, a.get("source", ""))
            if j_title and tu.is_non_article(a["url"], j_title, split_site=True): a["drop"] = "не статья (Jina)"; return a
            text = tu.post_process_text(j_text)
            if tu.is_generic_description(text) or tu.is_weak_description(text, a.get("source", "")): text = ""
            if text: a["origin"] = "jina"
        a["source_text"] = text
    except Exception: pass
    return a

def final_select(pool: dict) -> dict:
    by_cat = {}
    seen_urls = set()
    for c in tu.CATEGORIES:
        items = []
        for a in pool[c]:
            if a.get("drop") or a["url"] in seen_urls: continue
            seen_urls.add(a["url"])
            items.append(a)
            if len(items) >= MAX_PER_CATEGORY: break
        by_cat[c] = items
    return by_cat

def translate_article(a: dict) -> dict:
    title = a["title"]
    src = a.get("source_text", "")
    t_ru, desc, method = title, "", "error"
    try:
        card = translators.make_russian_card(title, src)
        t_ru, desc, method = card["title_ru"], tu.post_process_text(card["description"]), card["method"]
        if desc and tu.is_generic_description(desc, strict_only=True):
            card2 = translators.make_russian_card(title, "")
            t_ru, desc, method = card2["title_ru"], tu.post_process_text(card2["description"]), card2["method"]
        # Если заголовок всё ещё на английском, принудительно переводим
        if not tu.has_cyrillic(t_ru):
            card2 = translators.make_russian_card(title, "")
            t_ru = card2["title_ru"]
            if not desc or desc == FALLBACK_DESC:
                desc = card2["description"]
            method = f"{method}+retry"

        if (method == "raw" or not desc or not tu.has_cyrillic(desc) or tu.is_generic_description(desc, strict_only=True)):
            desc, method = FALLBACK_DESC, "fallback"
    except Exception: desc, method = FALLBACK_DESC, "fallback"
    a["title_ru"] = tu.strip_source_suffix(tu.post_process_text(t_ru), a.get("source", "")) or title
    a["description"] = desc
    a["method"] = f"{a.get('origin', 'title')}→{method}"
    return a

def _tg(method: str, payload: dict) -> requests.Response:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    return requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=30)

def send_to_telegram(messages: list) -> int:
    if DRY_RUN:
        for m in messages: print("─" * 60 + "\n" + m)
        return len(messages)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id or not os.environ.get("TELEGRAM_BOT_TOKEN"): return 0
    sent = 0
    for m in messages:
        html_for_api = m.replace("\n", "<br>")
        payload = {"chat_id": chat_id, "rich_message": {"html": html_for_api}}
        for _ in range(3):
            try:
                r = _tg("sendRichMessage", payload)
                if r.status_code == 200: sent += 1; break
                if r.status_code == 429: time.sleep(5); continue
                log.error("Telegram %s: %s", r.status_code, r.text[:200])
                break
            except Exception: time.sleep(3)
        time.sleep(1)
    return sent

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sources = load_sources()
    log.info("Источников: %d", len(sources))
    if not sources: return 1
    articles = collect_articles(sources)
    log.info("Собрано записей: %d", len(articles))
    recent, shape = load_recent()
    articles = deduplicate(articles, recent)
    pool = classify_articles(articles, load_extra_keywords())
    candidates = [a for c in tu.CATEGORIES for a in pool[c]]
    log.info("Кандидатов: %d", len(candidates))
    if not candidates: return 0
    with ThreadPoolExecutor(max_workers=RESOLVE_WORKERS) as ex: list(ex.map(resolve_article, candidates))
    dropped = Counter(a["drop"] for a in candidates if a.get("drop"))
    if dropped: log.info("Отсеяно: %s", dict(dropped))
    by_cat = final_select(pool)
    chosen = [a for c in tu.CATEGORIES for a in by_cat[c]]
    log.info("К публикации: %d (%s)", len(chosen), {c: len(by_cat[c]) for c in tu.CATEGORIES})
    if not chosen: return 0
    with ThreadPoolExecutor(max_workers=TRANSLATE_WORKERS) as ex: list(ex.map(translate_article, chosen))
    log.info("Способы получения описаний: %s", dict(Counter(a["method"] for a in chosen)))
    messages = formatters.build_messages(by_cat)
    sent = send_to_telegram(messages)
    log.info("Отправлено сообщений: %d из %d", sent, len(messages))
    if sent: save_recent(recent + [a["title"] for a in chosen], shape)
    return 0 if sent == len(messages) else 1

if __name__ == "__main__":
    sys.exit(main())
