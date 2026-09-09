import asyncio
import aiohttp
import feedparser
import time
from typing import List, Tuple, Dict
from .models import Article

async def fetch_feed(session: aiohttp.ClientSession, url: str) -> Tuple[str, List[Article]]:
    try:
        async with session.get(url, timeout=15) as resp:
            print(f"🔍 {url} → HTTP {resp.status}")
            if resp.status != 200:
                print(f"⚠️  {url} вернул статус {resp.status}")
                return url, []
            
            content = await resp.read()
            if not content:
                print(f"⚠️  {url} вернул пустой ответ")
                return url, []
            
            feed = feedparser.parse(content)
            if feed.bozo:
                print(f"⚠️  {url} ошибка парсинга: {feed.bozo_exception}")
            
            articles = []
            for entry in feed.get("entries", [])[:20]:
                published_ts = None
                for key in ("published_parsed", "updated_parsed", "created_parsed"):
                    if key in entry and entry[key]:
                        published_ts = time.mktime(entry[key])
                        break
                article = Article(
                    title=entry.get("title", ""),
                    link=entry.get("link", ""),
                    summary=entry.get("summary", ""),
                    author=entry.get("author", ""),
                    feed_url=url,
                    published_ts=published_ts,
                )
                if article.title and article.link:
                    articles.append(article)
            feed_title = feed.get("feed", {}).get("title", url)
            return feed_title, articles
    except asyncio.TimeoutError:
        print(f"⏰ Таймаут при загрузке {url}")
        return url, []
    except aiohttp.ClientError as e:
        print(f"🌐 Ошибка соединения {url}: {e}")
        return url, []
    except Exception as e:
        print(f"❌ Неизвестная ошибка при загрузке {url}: {e}")
        return url, []

async def collect_articles(rss_feeds: List[str]) -> Dict[str, List[Article]]:
    import logging
    logger = logging.getLogger("analytics_digest")
    logger.info(f"Fetching {len(rss_feeds)} RSS feeds (async)...")
    articles_by_feed = {}
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_feed(session, url) for url in rss_feeds]
        results = await asyncio.gather(*tasks)
        for feed_title, articles in results:
            if articles:
                articles_by_feed[feed_title] = articles
    total = sum(len(a) for a in articles_by_feed.values())
    logger.info(f"Collected {total} articles from {len(articles_by_feed)} feeds")
    return articles_by_feed
