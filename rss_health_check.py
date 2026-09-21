#!/usr/bin/env python3
"""
Еженедельная проверка здоровья RSS-источников.
Использует aiohttp + User-Agent, чинит невалидный XML,
знает про "known blocked" (Cloudflare / paywall).
"""
import asyncio
import json
import os
import re
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
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

# Домены, которые заведомо блокируют ботов — не считаем проблемой
KNOWN_BLOCKED = {
    "economist.com",
    "ft.com",
    "theinformation.com",
    "semianalysis.com",
    "ben-evans.com",
    "brookings.edu",
    "carnegieendowment.org",
    "provokemedia.com",
}


def get_source_name(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "").split("/")[0]
    except Exception:
        return url


def fix_xml(content: bytes) -> bytes:
    """Чинит типичные проблемы RSS: entities, control-символы, одиночные & < >."""
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    # Заменяем необъявленные entities вроде &nbsp; &hellip;
    content = re.sub(
        rb"&(?!(?:#\d+|#x[0-9a-fA-F]+|amp|lt|gt|quot|apos);)([a-zA-Z]+);",
        rb"\1",
        content,
    )
    # Одиночные & → &amp;
    content = re.sub(rb"&(?!(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);)", b"&amp;", content)
    # Control-символы
    content = re.sub(rb"[\x00-\x08\x0B\x0C\x0E-\x1F]", b"", content)
    # Одиночные < не в составе тега → &lt;
    content = re.sub(rb"<(?![a-zA-Z/!?])", b"&lt;", content)
    return content


def get_published_time(entry) -> float | None:
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        if field in entry and entry[field]:
            try:
                return time.mktime(entry[field])
            except Exception:
                pass
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


async def fetch_feed(session: aiohttp.ClientSession, url: str):
    """Возвращает (status_code, raw_bytes_or_None, error_str_or_None)."""
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                if resp.status == 429:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt + 1)
                        continue
                    return resp.status, None, "HTTP 429 (rate limit)"
                if resp.status != 200:
                    return resp.status, None, f"HTTP {resp.status}"
                raw = await resp.read()
                return resp.status, raw, None
        except asyncio.TimeoutError:
            if attempt < 2:
                await asyncio.sleep(2)
                continue
            return None, None, "Timeout"
        except aiohttp.ClientError as e:
            return None, None, f"Connection: {str(e)[:120]}"
        except Exception as e:
            return None, None, str(e)[:150]
    return None, None, "Unknown"


async def check_one_feed(session: aiohttp.ClientSession, url: str) -> dict:
    result = {
        "url": url,
        "source_name": get_source_name(url),
        "status": "dead",
        "entries_count": 0,
        "latest_entry_age_days": None,
        "http_status": None,
        "error": None,
        "known_blocked": any(b in url for b in KNOWN_BLOCKED),
    }

    http_status, raw, error = await fetch_feed(session, url)
    result["http_status"] = http_status

    if error:
        result["error"] = error
        return result

    if not raw:
        result["error"] = "Empty response body"
        return result

    # Сначала пробуем как есть
    parsed = feedparser.parse(raw)
    # Если 0 entries или bozo — чиним XML и пробуем ещё раз
    if not getattr(parsed, "entries", None):
        fixed = fix_xml(raw)
        parsed = feedparser.parse(fixed)

    if not getattr(parsed, "entries", None):
        detail = "silent"
        if getattr(parsed, "bozo", False) and parsed.bozo_exception:
            detail = str(parsed.bozo_exception)[:120]
        result["error"] = f"No entries ({detail})"
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
            if r["status"] == "ok":
                icon = "✅"
            elif r["status"] == "stale":
                icon = "⏳"
            elif r["known_blocked"]:
                icon = "🚫"
            else:
                icon = "💀"
            extra = ""
            if r["status"] != "ok":
                info = r.get("error") or (
                    f"{r.get('latest_entry_age_days')} дн."
                    if r.get("latest_entry_age_days") else "?"
                )
                extra = f" — {info}"
            print(f"  [{i}/{len(rss_feeds)}] {icon} {r['source_name']}{extra}")

    dead = sum(1 for r in results if r["status"] == "dead" and not r["known_blocked"])
    stale = sum(1 for r in results if r["status"] == "stale")
    blocked = sum(1 for r in results if r["status"] == "dead" and r["known_blocked"])
    ok = len(results) - dead - stale - blocked

    report = {
        "checked_at": datetime.now().isoformat(),
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "summary": {
            "total": len(results),
            "ok": ok,
            "stale": stale,
            "dead": dead,
            "blocked": blocked,
        },
        "details": sorted(
            results,
            key=lambda r: (
                {"dead": 0, "stale": 1, "ok": 2}.get(r["status"], 3),
                r["source_name"],
            ),
        ),
    }
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Итог: OK: {ok}, Stale: {stale}, Dead: {dead}, Known blocked: {blocked}")
    print(f"💾 Отчёт сохранён в {HEALTH_FILE}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
