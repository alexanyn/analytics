# analytics/dedup.py
import hashlib
import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
from typing import Dict, List

from .config import load_config
from .models import Article
from .text_utils import normalize_for_dedup

logger = logging.getLogger("analytics_digest")
config = load_config()

CROSS_RUN_THRESHOLD = 0.65
SAME_RUN_THRESHOLD = 0.55


def title_hash(title: str) -> str:
    return hashlib.md5(normalize_for_dedup(title).encode("utf-8")).hexdigest()


def _migrate_old_cache(data: dict) -> dict:
    """Миграция старого формата: нормализует ключи."""
    migrated = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        if re.search(r"[A-ZА-ЯЁ]|[^\w\s]", k):
            normalized = normalize_for_dedup(k)
        else:
            normalized = k
        if normalized:
            migrated[normalized] = v
    return migrated


def load_recent_titles() -> Dict[str, dict]:
    """Загружает кеш с миграцией старого формата."""
    recent = {}
    if os.path.exists("recent_titles.json"):
        try:
            with open("recent_titles.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            data = _migrate_old_cache(data)
            cutoff = time.time() - config.dedup.recent_titles_window_hours * 3600
            for k, v in data.items():
                if isinstance(v, dict) and v.get("timestamp", 0) > cutoff:
                    recent[k] = v
        except Exception as e:
            logger.warning(f"Ошибка загрузки recent_titles.json: {e}")
    return recent


def add_to_cache(recent_titles: Dict[str, dict], article: Article,
                 translated_title: str, translated_summary: str):
    """Добавляет статью в кеш под нормализованным ключом."""
    normalized = normalize_for_dedup(article.title)
    if not normalized:
        return
    recent_titles[normalized] = {
        "timestamp": time.time(),
        "category": article.category,
        "translated_title": translated_title,
        "translated_summary": translated_summary,
        "original_title": article.title,
    }


def get_from_cache(recent_titles: Dict[str, dict], article_title: str) -> dict:
    """Возвращает запись кеша по нормализованному заголовку."""
    normalized = normalize_for_dedup(article_title)
    return recent_titles.get(normalized, {})


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def deduplicate(articles: List[Article], recent_titles: Dict[str, dict]) -> List[Article]:
    """Дедуплицирует с учётом нормализованного кеша за 7 дней."""
    deduped = []
    added_hashes = set()
    added_normalized = set()
    recent_keys = list(recent_titles.keys())

    for article in articles:
        normalized = normalize_for_dedup(article.title)
        if not normalized:
            continue

        h = title_hash(article.title)

        # 1. Точное совпадение нормализованного с кешем
        if normalized in recent_titles:
            continue

        # 2. Точное совпадение внутри батча
        if h in added_hashes:
            continue

        # 3. Fuzzy-сравнение с кешем
        is_dup = False
        for cached_norm in recent_keys:
            if _similar(normalized, cached_norm) > CROSS_RUN_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            continue

        # 4. Fuzzy внутри батча
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
