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
from .formatters import is_junk_article

logger = logging.getLogger("analytics_digest")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

MAX_WORKERS = 5

def translate_one(article):
    from .formatters import strip_source_suffix_from_title, get_source_name, clean_html, remove_title_from_summary, strip_trailing_source
    
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

    # 6. ЖЕСТКАЯ ГАРАНТИЯ: если пусто, генерируем через Groq
    if not t_summary or len(t_summary.strip()) < 15:
        t_summary = generate_description_groq(clean_title)
        if not t_summary:
            t_summary = "Подробности в источнике."

    if not t_title:
        t_title = clean_title

    return article, t_title, t_summary, True

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
