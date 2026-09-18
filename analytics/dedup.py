# analytics/dedup.py
import hashlib
import json
import logging
import os
import time
from difflib import SequenceMatcher
from typing import Dict, List

from .config import load_config
from .models import Article
from .text_utils import normalize_for_dedup, looks_translated

logger = logging.getLogger("analytics_digest")
config = load_config()

CROSS_RUN_THRESHOLD = 0.65
SAME_RUN_THRESHOLD = 0.55


def title_hash(title: str) -> str:
    return hashlib.md5(normalize_for_dedup(title).encode("utf-8")).hexdigest()


def _migrate_and_filter(data: dict) -> dict:
    """Нормализует ключи и отбрасывает записи с провалившимся переводом."""
    result = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        normalized = normalize_for_dedup(k)
        if not normalized:
            continue
        # Проверяем флаг или сами значения
        ok = v.get("translation_ok", True)
        if ok:
            orig = v.get("original_title", k)
            trans = v.get("translated_title", "")
            if orig and trans and not looks_translated(orig, trans):
                ok = False
        if not ok:
            continue
        v["translation_ok"] = True
        result[normalized] = v
    return result


def load_recent_titles() -> Dict[str, dict]:
    recent = {}
    if not os.path.exists("recent_titles.json"):
        return recent
    try:
        with open("recent_titles.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        data = _migrate_and_filter(data)
        cutoff = time.time() - config.dedup.recent_titles_window_hours * 3600
        for k, v in data.items():
            if v.get("timestamp", 0) > cutoff:
                recent[k] = v
    except Exception as e:
        logger.warning(f"Ошибка загрузки recent_titles.json: {e}")
    return recent


def add_to_cache(recent_titles: Dict[str, dict], article: Article,
                 translated_title: str, translated_summary: str, translation_ok: bool = True):
    normalized = normalize_for_dedup(article.title)
    if not normalized:
        return
    recent_titles[normalized] = {
        "timestamp": time.time(),
        "category": article.category,
        "translated_title": translated_title,
        "translated_summary": translated_summary,
        "original_title": article.title,
        "translation_ok": translation_ok,
    }


def get_from_cache(recent_titles: Dict[str, dict], article_title: str) -> dict:
    return recent_titles.get(normalize_for_dedup(article_title), {})


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def deduplicate(articles: List[Article], recent_titles: Dict[str, dict]) -> List[Article]:
    deduped = []
    added_hashes = set()
    added_normalized = set()
    recent_keys = list(recent_titles.keys())

    for article in articles:
        normalized = normalize_for_dedup(article.title)
        if not normalized:
            continue
        h = title_hash(article.title)

        if normalized in recent_titles:
            continue
        if h in added_hashes:
            continue

        is_dup = False
        for cached_norm in recent_keys:
            if _similar(normalized, cached_norm) > CROSS_RUN_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            continue
        for added_norm in added_normalized:
            if _similar(normalized, added_norm) > SAME_RUN_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            continue

        added_normalized.add(normalized)
        added_hashes.add(h)
        deduped.append(article)

    logger.info(f"Dedup: {len(articles)} → {len(deduped)}")
    return deduped
