#!/bin/bash
set -e
echo "🔄 Начинаю обновление Analytics Digest..."
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r analytics.py config.json metrics.jsonl recent_titles.json rss_health.json dashboard.html generate_dashboard.py rss_health_check.py "$BACKUP_DIR" 2>/dev/null || true
echo "✅ Бэкап создан в $BACKUP_DIR"
rm -f analytics.py
mkdir -p analytics
cat > analytics/__init__.py << 'INNER'
# Analytics Digest Package
INNER
cat > analytics/models.py << 'INNER'
from dataclasses import dataclass
from typing import Optional
@dataclass
class Article:
    title: str
    link: str
    summary: str = ""
    author: str = ""
    feed_url: str = ""
    category: Optional[str] = None
    published_ts: Optional[float] = None
INNER
cat > analytics/config.py << 'INNER'
import json
import os
from typing import List, Optional
from pydantic import BaseModel, Field
class DedupConfig(BaseModel):
    title_similarity_threshold_same_run: float = 0.50
    title_similarity_threshold_cross_run: float = 0.55
    recent_titles_window_hours: int = 72
class DigestConfig(BaseModel):
    max_items_per_category: int = 5
class CollectionConfig(BaseModel):
    max_fetch_workers: int = 15
class SchedulingConfig(BaseModel):
    max_publish_wait_seconds: int = 600
    publish_grace_seconds: int = 1800
    enabled: bool = True
class AppConfig(BaseModel):
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    collection: CollectionConfig = Field(default_factory=CollectionConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    rss_feeds: List[str] = []
    max_age_days: int = 3
DEFAULT_CONFIG = AppConfig()
def load_config() -> AppConfig:
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                user_data = json.load(f)
            return AppConfig(**user_data)
        except Exception:
            pass
    return DEFAULT_CONFIG
INNER
cat > analytics/collectors.py << 'INNER'
import asyncio
import aiohttp
import feedparser
import time
from typing import List, Tuple, Dict
from .models import Article
async def fetch_feed(session: aiohttp.ClientSession, url: str) -> Tuple[str, List[Article]]:
    try:
        async with session.get(url, timeout=15) as resp:
            content = await resp.read()
            feed = feedparser.parse(content)
            articles = []
            for entry in feed.get("entries", [])[:20]:
                published_ts = None
                for key in ("published_parsed", "updated_parsed", "created_parsed"):
                    if key in entry and entry[key]:
                        published_ts = time.mktime(entry[key])
                        break
                article = Article(
                    title=entry.get("title", ""),
                    link=entry.get("link", ""),
                    summary=entry.get("summary", ""),
                    author=entry.get("author", ""),
                    feed_url=url,
                    published_ts=published_ts,
                )
                if article.title and article.link:
                    articles.append(article)
            feed_title = feed.get("feed", {}).get("title", url)
            return feed_title, articles
    except Exception:
        return url, []
async def collect_articles(rss_feeds: List[str]) -> Dict[str, List[Article]]:
    import logging
    logger = logging.getLogger("analytics_digest")
    logger.info(f"Fetching {len(rss_feeds)} RSS feeds (async)...")
    articles_by_feed = {}
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in rss_feeds]
        results = await asyncio.gather(*tasks)
        for feed_title, articles in results:
            if articles:
                articles_by_feed[feed_title] = articles
    total = sum(len(a) for a in articles_by_feed.values())
    logger.info(f"Collected {total} articles from {len(articles_by_feed)} feeds")
    return articles_by_feed
INNER
cat > analytics/dedup.py << 'INNER'
import os
import json
import time
import hashlib
from typing import List, Dict
from difflib import SequenceMatcher
from .models import Article
from .config import load_config
config = load_config()
def normalize_title(title: str) -> str:
    s = title.lower().strip()
    s = ''.join(ch for ch in s if ch.isalnum() or ch.isspace())
    return ' '.join(s.split())
def title_hash(title: str) -> str:
    return hashlib.md5(normalize_title(title).encode()).hexdigest()
def load_recent_titles() -> Dict[str, dict]:
    recent = {}
    if os.path.exists("recent_titles.json"):
        try:
            with open("recent_titles.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                cutoff = time.time() - config.dedup.recent_titles_window_hours * 3600
                recent = {k: v for k, v in data.items() if v.get("timestamp", 0) > cutoff}
        except:
            pass
    return recent
def title_similarity(t1: str, t2: str) -> float:
    return SequenceMatcher(None, t1.lower(), t2.lower()).ratio()
def deduplicate(articles: List[Article], recent_titles: Dict[str, dict]) -> List[Article]:
    import logging
    logger = logging.getLogger("analytics_digest")
    deduped = []
    added_hashes = set()
    for article in articles:
        h = title_hash(article.title)
        is_recent_dup = any(
            title_similarity(article.title, recent_title) > config.dedup.title_similarity_threshold_cross_run
            for recent_title in recent_titles.keys()
        )
        if is_recent_dup:
            continue
        if h in added_hashes:
            continue
        batch_dup = False
        for a in deduped:
            if title_similarity(article.title, a.title) > config.dedup.title_similarity_threshold_same_run:
                batch_dup = True
                break
        if not batch_dup:
            added_hashes.add(h)
            deduped.append(article)
    logger.info(f"Dedup: {len(articles)} → {len(deduped)}")
    return deduped
INNER
cat > analytics/classifiers.py << 'INNER'
import json
import logging
from typing import List, Dict
from .models import Article
def load_categories() -> Dict[str, List[str]]:
    with open("categories.json", "r", encoding="utf-8") as f:
        return json.load(f)
CATEGORY_KEYWORDS = load_categories()
def classify_articles(articles: List[Article]) -> Dict[str, List[Article]]:
    logger = logging.getLogger("analytics_digest")
    categorized = {}
    for article in articles:
        text = (article.title + " " + article.summary).lower()
        best_category = None
        max_matches = 0
        for category, words in CATEGORY_KEYWORDS.items():
            matches = sum(1 for word in words if word in text)
            if matches > max_matches:
                max_matches = matches
                best_category = category
        if not best_category:
            best_category = "GEOPOLITICS_WORLD"
        article.category = best_category
        categorized.setdefault(best_category, []).append(article)
    logger.info(f"Classified {len(articles)} into {len(categorized)} categories")
    return categorized
INNER
cat > analytics/translators.py << 'INNER'
import os
import requests
import logging
from typing import Optional
logger = logging.getLogger("analytics_digest")
def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not text or len(text.strip()) < 10:
        return text
    cyrillic = sum(1 for c in text if 'а' <= c.lower() <= 'я' or c == 'ё')
    if cyrillic / len(text) > 0.3:
        return text
    if is_summary:
        prompt = f"""Сделай краткое резюме (1-2 предложения) на русском языке для следующего текста.
Если текст на английском, переведи и сократи. Только результат, без пояснений.
Текст: {text[:500]}"""
    else:
        prompt = f"""Переведи следующий текст на русский язык. Только перевод, без пояснений.
Текст: {text[:300]}"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("candidates"):
                result = data["candidates"][0].get("content", {}).get("parts", [])
                if result:
                    return result[0].get("text", text).strip()
    except Exception as e:
        logger.debug(f"Gemini failed: {e}")
    try:
        from googletrans import Translator
        translator = Translator()
        translated = translator.translate(text[:500], dest='ru').text
        return translated
    except:
        return text
INNER
cat > analytics/formatters.py << 'INNER'
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
INNER
cat > analytics/senders.py << 'INNER'
import time
import requests
import logging
from typing import List, Dict
from .models import Article
from .formatters import article_to_html, get_category_emoji, get_category_russian_name
logger = logging.getLogger("analytics_digest")
def _pack_lines_into_chunks(text, limit=32000):
    lines = text.split("\n")
    chunks = []
    current = []
    for line in lines:
        if len(line) > limit:
            line = line[:limit-3] + "..."
        if current and len("\n".join(current + [line])) > limit:
            chunks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks
def _send_one_chunk(chat_id, chunk, token: str) -> bool:
    if not chunk.strip():
        return False
    html_for_api = chunk.replace("\n", "<br>")
    url = f"https://api.telegram.org/bot{token}/sendRichMessage"
    payload = {"chat_id": chat_id, "rich_message": {"html": html_for_api}}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, timeout=30)
            try:
                data = response.json()
            except ValueError:
                wait_time = 5 * (attempt + 1)
                logger.warning(f"Telegram нераспознаваемый ответ, ждём {wait_time}с...")
                time.sleep(wait_time)
                continue
            if response.status_code == 200 and data.get("ok"):
                return True
            if response.status_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 5)
                wait_time = min(retry_after, 60)
                logger.warning(f"Rate limit, ждём {wait_time}с...")
                time.sleep(wait_time)
                continue
            if response.status_code >= 500:
                wait_time = min(5 * (2 ** attempt), 30)
                logger.warning(f"Серверная ошибка {response.status_code}, ждём {wait_time}с...")
                time.sleep(wait_time)
                continue
            logger.error(f"Telegram ошибка {response.status_code}: {data.get('description', data)}")
            return False
        except requests.exceptions.Timeout:
            wait_time = 5 * (attempt + 1)
            logger.warning(f"Timeout, ждём {wait_time}с...")
            time.sleep(wait_time)
            continue
        except requests.exceptions.RequestException as e:
            wait_time = 3 * (attempt + 1)
            logger.warning(f"Сетевая ошибка (попытка {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            continue
    return False
def send_to_telegram(articles_by_category: Dict[str, List[Article]], token: str, chat_id: str, cache: dict) -> bool:
    if not articles_by_category:
        return False
    full_html = "📊 <b>АНАЛИТИЧЕСКИЙ ДАЙДЖЕСТ</b>\n\n"
    first_category = True
    for category in sorted(articles_by_category.keys()):
        emoji = get_category_emoji(category)
        cat_display = get_category_russian_name(category)
        if not first_category:
            full_html += "\n" + "─" * 30 + "\n\n"
        full_html += f"{emoji} <b>{cat_display}</b>\n\n"
        articles = articles_by_category[category][:5]
        for i, article in enumerate(articles):
            full_html += article_to_html(article, cache)
            if i < len(articles) - 1:
                full_html += "\n\n" + "─" * 30 + "\n\n"
        first_category = False
    if not full_html.strip():
        logger.error("Empty digest HTML")
        return False
    if len(full_html) <= 32000:
        return _send_one_chunk(chat_id, full_html, token)
    chunks = _pack_lines_into_chunks(full_html, limit=32000)
    all_ok = True
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(1)
        chunk_ok = _send_one_chunk(chat_id, chunk, token)
        all_ok = chunk_ok and all_ok
    if all_ok:
        logger.info(f"Sent {len(chunks)} messages, {sum(len(a) for a in articles_by_category.values())} articles")
    else:
        logger.error(f"Some chunks failed")
    return all_ok
INNER
cat > analytics/scheduling.py << 'INNER'
import datetime
import time
import logging
from .config import load_config
logger = logging.getLogger("analytics_digest")
MOSCOW_OFFSET = datetime.timedelta(hours=3)
MOSCOW_TZ = datetime.timezone(MOSCOW_OFFSET)
def now_moscow():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(MOSCOW_TZ)
def wait_until_publish_time():
    config = load_config().scheduling
    if not config.enabled:
        return
    max_wait = config.max_publish_wait_seconds
    now = now_moscow()
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now > target:
        target += datetime.timedelta(days=1)
    wait = (target - now).total_seconds()
    if wait <= 0:
        return
    if wait > max_wait:
        logger.warning(f"Публикуем раньше расписания: до цели {int(wait)}с > {max_wait}с")
        return
    logger.info(f"Ждём до {target.strftime('%H:%M:%S МСК')} ({int(wait)}с)")
    time.sleep(wait)
INNER
cat > analytics/metrics.py << 'INNER'
import json
import os
import logging
from datetime import datetime
from typing import List, Optional
logger = logging.getLogger("analytics_digest")
def log_metrics(status: str, article_count: int = 0, category_count: int = 0,
                errors: Optional[List[str]] = None, duration: Optional[float] = None):
    metrics_file = "metrics.jsonl"
    try:
        metric = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "articles": article_count,
            "categories": category_count,
            "errors": errors or [],
        }
        if duration is not None:
            metric["duration_seconds"] = round(duration, 1)
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Не удалось записать метрику: {e}")
def send_alert(status: str, errors: List[str] = None):
    if status not in ("crashed", "send_failed"):
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    icon = "🔴" if status == "crashed" else "🟡"
    status_text = {"crashed": "необработанный сбой", "send_failed": "ошибка отправки"}.get(status, status)
    lines = [f"{icon} <b>АЛЕРТ дайджеста:</b> {status_text}"]
    if errors:
        lines.append("Детали: " + "; ".join(errors)[:300])
    alert_text = "\n".join(lines)
    try:
        from .senders import _send_one_chunk
        _send_one_chunk(chat_id, alert_text, token)
        logger.info(f"Алерт отправлен ({status})")
    except Exception as e:
        logger.warning(f"Не удалось отправить алерт: {e}")
INNER
cat > analytics/main.py << 'INNER'
#!/usr/bin/env python3
import asyncio
import time
import logging
import sys
import os
import json
from .config import load_config
from .collectors import collect_articles
from .dedup import deduplicate, load_recent_titles
from .classifiers import classify_articles
from .translators import translate_and_summarize
from .senders import send_to_telegram
from .scheduling import wait_until_publish_time
from .metrics import log_metrics, send_alert
logger = logging.getLogger("analytics_digest")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
async def main_async():
    start_time = time.time()
    config = load_config()
    rss_feeds = config.rss_feeds
    if not rss_feeds:
        logger.error("Нет RSS-источников в конфиге")
        log_metrics("empty_no_candidates")
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Missing Telegram credentials")
        send_alert("crashed", ["No token/chat_id"])
        return
    articles_by_feed = await collect_articles(rss_feeds)
    all_articles = [a for articles in articles_by_feed.values() for a in articles]
    if not all_articles:
        log_metrics("empty_no_candidates")
        return
    if config.max_age_days:
        now = time.time()
        all_articles = [a for a in all_articles if a.published_ts is None or (now - a.published_ts) <= config.max_age_days * 86400]
    recent_titles = load_recent_titles()
    deduped = deduplicate(all_articles, recent_titles)
    if not deduped:
        log_metrics("empty_no_deduplicated")
        return
    categorized = classify_articles(deduped)
    for article in deduped:
        if article.title in recent_titles:
            continue
        translated_title = translate_and_summarize(article.title, is_summary=False)
        translated_summary = translate_and_summarize(article.summary, is_summary=True)
        recent_titles[article.title] = {
            "timestamp": time.time(),
            "category": article.category,
            "translated_title": translated_title,
            "translated_summary": translated_summary,
        }
    wait_until_publish_time()
    success = send_to_telegram(categorized, token, chat_id, cache=recent_titles)
    with open("recent_titles.json", "w", encoding="utf-8") as f:
        json.dump(recent_titles, f, ensure_ascii=False, indent=2)
    duration = time.time() - start_time
    if success:
        log_metrics("success", len(deduped), len(categorized), duration=duration)
        logger.info(f"Success: {len(deduped)} articles in {len(categorized)} categories")
    else:
        log_metrics("send_failed", duration=duration)
        send_alert("send_failed")
def main():
    try:
        asyncio.run(main_async())
    except Exception as e:
        logger.error(f"Crashed: {e}", exc_info=True)
        log_metrics("crashed")
        send_alert("crashed", [str(e)[:200]])
        sys.exit(1)
if __name__ == "__main__":
    main()
INNER
cat > categories.json << 'INNER'
{
  "GEOPOLITICS_WORLD": ["foreign affairs", "ecfr", "csis", "chatham house", "carnegie", "geopolitics", "foreign policy", "diplomacy", "international"],
  "GEOPOLITICS_RUSSIA": ["russia in global affairs", "ponars", "imemo", "russian council", "valdai", "россия", "москва", "кремль", "политика", "украина"],
  "ECONOMICS_WORLD": ["financial times", "economist", "peterson", "bruegel", "voxeu", "cepr", "economy", "market", "trade", "finance"],
  "ECONOMICS_RUSSIA": ["econs", "forecast.ru", "цмакп", "gaidar", "iep", "экономика", "рынок", "бизнес", "финансы"],
  "TECHNOLOGY_WORLD": ["stratechery", "information", "semianalysis", "mit tech", "benedict evans", "ai", "tech", "software", "chip"],
  "TECHNOLOGY_RUSSIA": ["data insight", "исиэз", "hse", "технология", "цифр", "программ"],
  "ENERGY_WORLD": ["iea", "oxford energy", "bloombergnef", "wood mackenzie", "carbon brief", "energy", "oil", "gas", "renewable"],
  "ENERGY_RUSSIA": ["инэи", "energyland", "vygon", "энергетическая политика", "skolkovo", "энергия", "газ", "нефть"],
  "SECURITY_WORLD": ["war on rocks", "isw", "rand", "iiss", "sipri", "military", "defense", "security", "conflict", "nato"],
  "SECURITY_RUSSIA": ["cast", "jamestown", "osw", "bmpd", "lawfare", "безопасность", "военн", "оборон", "конфликт"],
  "PR_WORLD": ["edelman", "provoke", "arthur w. page", "institute for pr", "drum", "pr", "communication", "media", "brand"],
  "PR_RUSSIA": ["medialogia", "brand analytics", "акос", "пресс", "реклам", "медиа", "коммуникац"]
}
INNER
cat > sources.json << 'INNER'
{
  "foreignaffairs.com": "Foreign Affairs",
  "ecfr.eu": "ECFR",
  "csis.org": "CSIS",
  "chathamhouse.org": "Chatham House",
  "carnegieendowment.org": "Carnegie Endowment",
  "eng.globalaffairs.ru": "Russia in Global Affairs",
  "globalaffairs.ru": "Russia in Global Affairs",
  "ponarseurasia.org": "PONARS Eurasia",
  "imemo.ru": "ИМЭМО РАН",
  "russiancouncil.ru": "Russian Council",
  "valdaiclub.com": "Valdai Club",
  "ft.com": "Financial Times",
  "economist.com": "The Economist",
  "piie.com": "Peterson Institute",
  "bruegel.org": "Bruegel",
  "cepr.org": "CEPR",
  "voxeu.org": "VoxEU",
  "econs.online": "Econs",
  "forecast.ru": "ЦМАКП",
  "iep.ru": "Gaidar Institute",
  "stratechery.com": "Stratechery",
  "theinformation.com": "The Information",
  "semianalysis.com": "SemiAnalysis",
  "technologyreview.com": "MIT Technology Review",
  "ben-evans.com": "Benedict Evans",
  "datainsight.ru": "Data Insight",
  "issek.hse.ru": "ИСИЭЗ ВШЭ",
  "iea.org": "IEA",
  "oxfordenergy.org": "Oxford Institute for Energy Studies",
  "bnef.com": "BloombergNEF",
  "about.bnef.com": "BloombergNEF",
  "woodmac.com": "Wood Mackenzie",
  "carbonbrief.org": "Carbon Brief",
  "eriras.ru": "ИНЭИ РАН",
  "energyland.info": "EnergyLand.info",
  "vygon.consulting": "VYGON Consulting",
  "energypolicy.ru": "Энергетическая политика",
  "energy.skolkovo.ru": "HSE Energy Centre",
  "warontherocks.com": "War on the Rocks",
  "understandingwar.org": "ISW",
  "rand.org": "RAND Corporation",
  "iiss.org": "IISS",
  "sipri.org": "SIPRI",
  "cast.ru": "CAST",
  "jamestown.org": "Jamestown Foundation",
  "osw.waw.pl": "OSW",
  "bmpd.livejournal.com": "BMPD",
  "lawfaremedia.org": "Lawfare",
  "edelman.com": "Edelman Trust Institute",
  "provokemedia.com": "PRovoke Media",
  "page.org": "Arthur W. Page Society",
  "instituteforpr.org": "Institute for Public Relations",
  "thedrum.com": "The Drum",
  "medialogia.ru": "Medialogia",
  "br-analytics.ru": "Brand Analytics",
  "akospr.ru": "АКОС"
}
INNER
cat > update_sources.py << 'INNER'
#!/usr/bin/env python3
import json
import requests
import os
REMOTE_URL = "https://gist.githubusercontent.com/gyri11212-art/.../raw/sources.json"
def update_sources():
    try:
        resp = requests.get(REMOTE_URL, timeout=10)
        resp.raise_for_status()
        new_feeds = resp.json()
        if not isinstance(new_feeds, list):
            raise ValueError("Remote data is not a list")
        config = {}
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        config["rss_feeds"] = new_feeds
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✅ Обновлено {len(new_feeds)} источников.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
if __name__ == "__main__":
    update_sources()
INNER
chmod +x update_sources.py
cat > requirements.txt << 'INNER'
requests
feedparser
beautifulsoup4
aiohttp
pydantic
googletrans==4.0.0-rc1
pre-commit
INNER
cat > .pre-commit-config.yaml << 'INNER'
repos:
  - repo: https://github.com/psf/black
    rev: 23.11.0
    hooks:
      - id: black
  - repo: https://github.com/pycqa/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        args: [--max-line-length=120]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.6.1
    hooks:
      - id: mypy
        args: [--ignore-missing-imports]
INNER
cat > rss_health_check.py << 'INNER'
#!/usr/bin/env python3
import json
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import feedparser
import requests
def get_source_name(url):
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "").split("/")[0]
        return domain
    except:
        return url
def get_published_time(entry):
    for field in ['published', 'updated', 'created']:
        if field in entry:
            try:
                import email.utils
                ts = email.utils.parsedate_to_datetime(entry[field])
                return ts.timestamp()
            except:
                pass
    return None
def fetch_feed(url, timeout=15):
    try:
        response = requests.get(url, timeout=timeout, verify=False)
        return feedparser.parse(response.content)
    except:
        return None
def check_one_feed(url):
    source_name = get_source_name(url)
    result = {
        "url": url,
        "source_name": source_name,
        "status": "dead",
        "entries_count": 0,
        "latest_entry_age_days": None,
        "error": None,
    }
    try:
        parsed = fetch_feed(url, timeout=20)
        if not parsed or not getattr(parsed, "entries", None):
            result["error"] = "Empty response or no entries"
            return result
        result["entries_count"] = len(parsed.entries)
        latest_ts = None
        for entry in parsed.entries[:10]:
            ts = get_published_time(entry)
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
        if latest_ts is None:
            result["status"] = "ok"
            return result
        age_days = (time.time() - latest_ts) / 86400
        result["latest_entry_age_days"] = round(age_days, 1)
        result["status"] = "stale" if age_days > 7 else "ok"
    except Exception as e:
        result["error"] = str(e)[:200]
    return result
def main():
    if not os.path.exists("config.json"):
        print("❌ config.json не найден")
        sys.exit(1)
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    rss_feeds = config.get("rss_feeds", [])
    if not rss_feeds:
        print("❌ В config.json нет rss_feeds")
        sys.exit(1)
    print(f"🩺 Проверяем здоровье {len(rss_feeds)} RSS источников...")
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_one_feed, url): url for url in rss_feeds}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                results.append(result)
                if result["status"] != "ok":
                    print(f"  [{i}/{len(rss_feeds)}] ⚠️  {result['source_name']}: {result['status']}")
                else:
                    print(f"  [{i}/{len(rss_feeds)}] ✅ {result['source_name']}")
            except Exception as e:
                print(f"  [{i}/{len(rss_feeds)}] ❌ Ошибка: {e}")
    dead = len([r for r in results if r["status"] == "dead"])
    stale = len([r for r in results if r["status"] == "stale"])
    ok = len(results) - dead - stale
    report = {
        "checked_at": datetime.now().isoformat(),
        "stale_threshold_days": 7,
        "summary": {"total": len(results), "ok": ok, "stale": stale, "dead": dead},
        "details": sorted(results, key=lambda r: ({"dead": 0, "stale": 1, "ok": 2}.get(r["status"], 3), r["source_name"]))
    }
    with open("rss_health.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📊 Итог: OK: {ok}, Stale: {stale}, Dead: {dead}")
    print(f"💾 Отчёт сохранён в rss_health.json")
if __name__ == "__main__":
    main()
INNER
pip install --upgrade pip
pip install -r requirements.txt
pre-commit install
echo "✅ Обновление завершено!"
echo "📌 Теперь запускайте дайджест командой: python -m analytics.main"
echo "📌 Для проверки здоровья: python rss_health_check.py"
echo "📌 Для обновления источников: python update_sources.py"
