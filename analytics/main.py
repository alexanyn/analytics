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
