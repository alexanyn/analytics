# analytics/classifiers.py
import json
import logging
import re
from typing import List, Dict

from .models import Article

logger = logging.getLogger("analytics_digest")

CATEGORY_ORDER = ["GEOPOLITICS", "ECONOMICS", "BUSINESS", "TECHNOLOGY", "ENERGY", "SECURITY"]

DEFAULT_CATEGORY = "GEOPOLITICS"


def load_categories() -> Dict[str, List[str]]:
    with open("categories.json", "r", encoding="utf-8") as f:
        return json.load(f)


CATEGORY_KEYWORDS = load_categories()

# Предкомпилированные паттерны с word boundary (исправляет ложные срабатывания)
CATEGORY_PATTERNS = {
    cat: [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words]
    for cat, words in CATEGORY_KEYWORDS.items()
}


def classify_articles(articles: List[Article]) -> Dict[str, List[Article]]:
    """Классифицирует статьи по ключевым словам с учётом границ слов."""
    categorized = {}
    for article in articles:
        text = (article.title + " " + article.summary).lower()
        best_category = None
        max_matches = 0
        for category, patterns in CATEGORY_PATTERNS.items():
            matches = sum(1 for p in patterns if p.search(text))
            if matches > max_matches:
                max_matches = matches
                best_category = category
        if not best_category:
            best_category = DEFAULT_CATEGORY
        article.category = best_category
        categorized.setdefault(best_category, []).append(article)
    logger.info(f"Classified {len(articles)} into {len(categorized)} categories")
    return categorized
