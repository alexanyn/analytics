#!/usr/bin/env python3
import asyncio
import time
import logging
import sys
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import load_config
from .collectors import collect_articles
from .dedup import deduplicate, load_recent_titles, add_to_cache
from .classifiers import classify_articles
from .translators import translate_article, generate_description_groq, _STATS
from .senders import send_to_telegram
from .scheduling import wait_until_publish_time
from .metrics import log_metrics, send_alert
from .text_utils import normalize_for_dedup, fetch_description_from_html
from .formatters import (
    is_junk_article, clean_html, remove_title_from_summary, 
    strip_trailing_source, strip_source_suffix_from_title, get_source_name
)

logger = logging.getLogger("analytics_digest")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

MAX_WORKERS = 5

def translate_one(article):
    try:
        source = get_source_name(article.feed_url)
        clean_title = strip_source_suffix_from_title(article.title, source) or article.title
    except Exception:
        source = ""
        clean_title = article.title

    # 1. Очищаем RSS-описание от HTML
    clean_summary = clean_html(article.summary or "")
    
    # 2. Убираем дубли заголовка и названия источника
    clean_summary = remove_title_from_summary(clean_title, clean_summary)
    clean_summary = strip_trailing_source(clean_summary, source)
    
    # 3. Если после очистки остался огрызок (меньше 30 символов) — идем в Jina
    if not clean_summary or len(clean_summary.strip()) < 30:
        clean_summary = fetch_description_from_html(article.link)

    # 4. Проверяем снова, если Jina вернула мусор
    if clean_summary and len(clean_summary.strip()) < 30:
        clean_summary = ""

    # 5. Переводим
    t_title, t_summary = translate_article(clean_title, clean_summary)

    # 6. ЖЕСТКАЯ ГАРАНТИЯ: если пусто или дубль — генерируем через Groq
    if not t_summary or len(t_summary.strip()) < 15 or t_summary.strip().lower() == t_title.strip().lower():
        t_summary = generate_description_groq(clean_title)
        if not t_summary:
            t_summary = "Подробности в источнике."

    if not t_title:
        t_title = clean_title

    return article, t_title, t_summary, True


async def main_async():
    start_time = time.time()
    config = load_config()
    
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Missing Telegram credentials")
        return

    articles_by_feed = await collect_articles(config.rss_feeds)
    all_articles = [a for arts in articles_by_feed.values() for a in arts]
    if not all_articles:
        log_metrics("empty_no_candidates")
        return

    if config.max_age_days:
        now = time.time()
        all_articles = [a for a in all_articles if a.published_ts is None or (now - a.published_ts) <= config.max_age_days * 86400]

    recent_titles = load_recent_titles()
    logger.info(f"Cache loaded: {len(recent_titles)} entries")
    
    deduped = deduplicate(all_articles, recent_titles)
    
    before_junk = len(deduped)
    deduped = [a for a in deduped if not is_junk_article(a)]
    if before_junk != len(deduped):
        logger.info(f"Junk filter: {before_junk} → {len(deduped)}")
        
    categorized = classify_articles(deduped)
    
    max_per_cat = config.digest.max_items_per_category
    for cat in list(categorized.keys()):
        categorized[cat] = categorized[cat][:max_per_cat]

    final_articles = [a for arts in categorized.values() for a in arts]
    logger.info(f"Final digest: {len(final_articles)} articles")

    to_translate = [a for a in final_articles if normalize_for_dedup(a.title) not in recent_titles]

    if to_translate:
        logger.info(f"Translating {len(to_translate)} articles with {MAX_WORKERS} workers...")
        t_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(translate_one, a) for a in to_translate]
            for future in as_completed(futures):
                try:
                    article, t_title, t_summary, ok = future.result()
                    add_to_cache(recent_titles, article, t_title, t_summary, translation_ok=ok)
                except Exception as e:
                    logger.debug(f"Future error: {e}")
        logger.info(f"Translation done in {time.time() - t_start:.1f}s")
        logger.info(f"Stats: {_STATS}")

    wait_until_publish_time()
    success = send_to_telegram(categorized, token, chat_id, cache=recent_titles)

    with open("recent_titles.json", "w", encoding="utf-8") as f:
        json.dump(recent_titles, f, ensure_ascii=False, indent=2)

    duration = time.time() - start_time
    if success:
        log_metrics("success", len(final_articles), len(categorized), duration=duration)
        logger.info(f"Success: {len(final_articles)} articles in {len(categorized)} categories")
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
