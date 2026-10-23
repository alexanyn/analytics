#!/usr/bin/env python3
import asyncio
import re
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
from .translators import translate_article
from .senders import send_to_telegram
from .scheduling import wait_until_publish_time
from .metrics import log_metrics, send_alert
from .text_utils import normalize_for_dedup, looks_translated, fetch_description_from_html
from .formatters import is_junk_article

logger = logging.getLogger("analytics_digest")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# 4 воркера × 2.85 запроса/сек ≈ 11 запросов/сек — но rate limiter удержит в пределах 3/сек
MAX_TRANSLATE_WORKERS = 5


def _clean_summary_before_translation(title: str, summary: str, source: str) -> str:
    """Очищает summary от дубля заголовка и названия источника."""
    if not summary:
        return ""

    s = summary.strip()
    
    def norm(x):
        return " ".join(x.lower().split())

    t_norm = norm(title)
    s_norm = norm(s)
    
    # Если summary совпадает с заголовком или начинается с него — отрезаем
    if t_norm and (s_norm == t_norm or s_norm.startswith(t_norm)):
        s = s[len(title):].strip(" .,:;-–—|")
        s_norm = norm(s)
        if len(s) < 30:
            return ""

    # Убираем название источника (в начале или конце)
    if source:
        for pattern in [
            rf"\s*[-–—|:]\s*{re.escape(source)}.*$",
            rf"\s*{re.escape(source)}\s*[-–—|:].*$",
            rf"^\s*{re.escape(source)}\s*[-–—|:]?\s*",
        ]:
            s = re.sub(pattern, "", s, flags=re.IGNORECASE).strip(" .,:;-–—|")

    if len(s) < 20:
        return ""

    return s


def translate_one(article):
    from .formatters import strip_source_suffix_from_title, get_source_name
    try:
        source = get_source_name(article.feed_url)
        clean_title = strip_source_suffix_from_title(article.title, source) or article.title
    except Exception:
        clean_title = article.title

    # 1. Берем описание из RSS
    clean_summary = article.summary or ""
    if normalize_for_dedup(clean_title) == normalize_for_dedup(clean_summary):
        clean_summary = ""

    # 2. Идем в Jina
    if not clean_summary:
        clean_summary = fetch_description_from_html(article.link)

    # 3. Если Jina вернула мусор (меньше 80 символов) — сбрасываем
    if clean_summary and len(clean_summary.strip()) < 80:
        clean_summary = ""

    # 4. Переводим
    t_title, t_summary = translate_article(clean_title, clean_summary)

    # 5. ЖЕСТКАЯ ГАРАНТИЯ ОПИСАНИЯ: если пусто или слишком коротко — генерируем через Groq
    if not t_summary or len(t_summary.strip()) < 15:
        t_summary = generate_description_groq(clean_title)
        if not t_summary:
            t_summary = "Подробности в источнике." # Абсолютный фолбэк

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
