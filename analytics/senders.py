# analytics/senders.py
import time
import requests
import logging
from typing import List, Dict

from .models import Article
from .formatters import article_to_html, get_category_emoji, get_category_russian_name
from .classifiers import CATEGORY_ORDER

logger = logging.getLogger("analytics_digest")

SEPARATOR = "─" * 16


def _pack_lines_into_chunks(text: str, limit: int = 32000) -> List[str]:
    lines = text.split("\n")
    chunks = []
    current = []
    for line in lines:
        if len(line) > limit:
            line = line[: limit - 3] + "..."
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
            logger.warning(f"Сетевая ошибка (попытка {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            continue
    return False


def send_to_telegram(articles_by_category: Dict[str, List[Article]], token: str, chat_id: str, cache: dict) -> bool:
    if not articles_by_category:
        return False

    full_html = "📊 <b>АНАЛИТИЧЕСКИЙ ДАЙДЖЕСТ</b>\n\n"
    first_category = True

    # Итерируемся в фиксированном порядке, пропуская пустые категории
    for category in CATEGORY_ORDER:
        if category not in articles_by_category:
            continue
        articles = articles_by_category[category]
        if not articles:
            continue

        emoji = get_category_emoji(category)
        cat_display = get_category_russian_name(category)

        if not first_category:
            full_html += "\n" + SEPARATOR + "\n\n"
        full_html += f"{emoji} <b>{cat_display}</b>\n\n"

        articles = articles[:5]
        for i, article in enumerate(articles):
            full_html += article_to_html(article, cache)
            if i < len(articles) - 1:
                full_html += "\n\n" + SEPARATOR + "\n\n"
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
        logger.error("Some chunks failed")
    return all_ok
