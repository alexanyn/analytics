#!/usr/bin/env python3
"""
Еженедельная проверка здоровья RSS-источников.
Использует aiohttp + User-Agent — как и основной сборщик дайджеста.
"""
import asyncio
import json
import os
import sys
import time
import urllib3
from datetime import datetime

import aiohttp
import feedparser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

STALE_THRESHOLD_DAYS = 7
HEALTH_FILE = "rss_health.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def get_source_name(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "").split("/")[0]
    except Exception:
        return url


def get_published_time(entry) -> float | None:
    # Сначала пробуем feedparser-парсер
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        if field in entry and entry[field]:
            try:
                return time.mktime(entry[field])
            except Exception:
                pass
    # Потом сырые строки
    for field in ("published", "updated", "created"):
        if field in entry:
            try:
                import email.utils
                ts = email.utils.parsedate_to_datetime(entry[field])
                if ts:
                    return ts.timestamp()
            except Exception:
                pass
    return None


async def check_one_feed(session: aiohttp.ClientSession, url: str) -> dict:
    result = {
        "url": url,
        "source_name": get_source_name(url),
        "status": "dead",
        "entries_count": 0,
        "latest_entry_age_days": None,
        "http_status": None,
        "error": None,
    }
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            result["http_status"] = resp.status
            if resp.status != 200:
                result["error"] = f"HTTP {resp.status}"
                return result
            content = await resp.read()
            if not content:
                result["error"] = "Empty response body"
                return result
            parsed = feedparser.parse(content)
            if not getattr(parsed, "entries", None):
                detail = None
                if getattr(parsed, "bozo", False):
                    detail = str(parsed.bozo_exception)[:150]
                result["error"] = f"No entries ({detail or 'silent'})"
                return result
            result["entries_count"] = len(parsed.entries)

            latest_ts = None
            for entry in parsed.entries[:10]:
                ts = get_published_time(entry)
                if ts and (latest_ts is None or ts > latest_ts):
                    latest_ts = ts

            if latest_ts is None:
                result["status"] = "ok"
                return result

            age_days = (time.time() - latest_ts) / 86400
            result["latest_entry_age_days"] = round(age_days, 1)
            result["status"] = "stale" if age_days > STALE_THRESHOLD_DAYS else "ok"
    except asyncio.TimeoutError:
        result["error"] = "Timeout"
    except aiohttp.ClientError as e:
        result["error"] = f"Connection: {str(e)[:150]}"
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


async def main_async():
    if not os.path.exists("config.json"):
        print("❌ config.json не найден")
        sys.exit(1)
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    rss_feeds = config.get("rss_feeds", [])
    if not rss_feeds:
        print("❌ В config.json нет rss_feeds")
        sys.exit(1)

    print(f"🩺 Проверяем здоровье {len(rss_feeds)} RSS-источников...")

    connector = aiohttp.TCPConnector(ssl=False)
    results = []
    async with aiohttp.ClientSession(connector=connector, headers=HEADERS) as session:
        tasks = [check_one_feed(session, url) for url in rss_feeds]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            r = await coro
            results.append(r)
            icon = "✅" if r["status"] == "ok" else ("⏳" if r["status"] == "stale" else "💀")
            extra = ""
            if r["status"] != "ok":
                info = r.get("error") or (
                    f"{r.get('latest_entry_age_days')} дн." if r.get("latest_entry_age_days") else ""
                )
                extra = f" — {info}"
            print(f"  [{i}/{len(rss_feeds)}] {icon} {r['source_name']}{extra}")

    dead = sum(1 for r in results if r["status"] == "dead")
    stale = sum(1 for r in results if r["status"] == "stale")
    ok = len(results) - dead - stale

    report = {
        "checked_at": datetime.now().isoformat(),
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "summary": {"total": len(results), "ok": ok, "stale": stale, "dead": dead},
        "details": sorted(
            results,
            key=lambda r: ({"dead": 0, "stale": 1, "ok": 2}.get(r["status"], 3), r["source_name"]),
        ),
    }
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Итог: OK: {ok}, Stale: {stale}, Dead: {dead}")
    print(f"💾 Отчёт сохранён в {HEALTH_FILE}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
