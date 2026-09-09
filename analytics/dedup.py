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
