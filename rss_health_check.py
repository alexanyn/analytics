#!/usr/bin/env python3
import json
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import feedparser
import requests
def get_source_name(url):
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "").split("/")[0]
        return domain
    except:
        return url
def get_published_time(entry):
    for field in ['published', 'updated', 'created']:
        if field in entry:
            try:
                import email.utils
                ts = email.utils.parsedate_to_datetime(entry[field])
                return ts.timestamp()
            except:
                pass
    return None
def fetch_feed(url, timeout=15):
    try:
        response = requests.get(url, timeout=timeout, verify=False)
        return feedparser.parse(response.content)
    except:
        return None
def check_one_feed(url):
    source_name = get_source_name(url)
    result = {
        "url": url,
        "source_name": source_name,
        "status": "dead",
        "entries_count": 0,
        "latest_entry_age_days": None,
        "error": None,
    }
    try:
        parsed = fetch_feed(url, timeout=20)
        if not parsed or not getattr(parsed, "entries", None):
            result["error"] = "Empty response or no entries"
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
        result["status"] = "stale" if age_days > 7 else "ok"
    except Exception as e:
        result["error"] = str(e)[:200]
    return result
def main():
    if not os.path.exists("config.json"):
        print("❌ config.json не найден")
        sys.exit(1)
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    rss_feeds = config.get("rss_feeds", [])
    if not rss_feeds:
        print("❌ В config.json нет rss_feeds")
        sys.exit(1)
    print(f"🩺 Проверяем здоровье {len(rss_feeds)} RSS источников...")
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_one_feed, url): url for url in rss_feeds}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                results.append(result)
                if result["status"] != "ok":
                    print(f"  [{i}/{len(rss_feeds)}] ⚠️  {result['source_name']}: {result['status']}")
                else:
                    print(f"  [{i}/{len(rss_feeds)}] ✅ {result['source_name']}")
            except Exception as e:
                print(f"  [{i}/{len(rss_feeds)}] ❌ Ошибка: {e}")
    dead = len([r for r in results if r["status"] == "dead"])
    stale = len([r for r in results if r["status"] == "stale"])
    ok = len(results) - dead - stale
    report = {
        "checked_at": datetime.now().isoformat(),
        "stale_threshold_days": 7,
        "summary": {"total": len(results), "ok": ok, "stale": stale, "dead": dead},
        "details": sorted(results, key=lambda r: ({"dead": 0, "stale": 1, "ok": 2}.get(r["status"], 3), r["source_name"]))
    }
    with open("rss_health.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📊 Итог: OK: {ok}, Stale: {stale}, Dead: {dead}")
    print(f"💾 Отчёт сохранён в rss_health.json")
if __name__ == "__main__":
    main()
