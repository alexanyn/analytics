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
