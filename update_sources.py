#!/usr/bin/env python3
import json
import requests
import os
REMOTE_URL = "https://gist.githubusercontent.com/gyri11212-art/.../raw/sources.json"
def update_sources():
    try:
        resp = requests.get(REMOTE_URL, timeout=10)
        resp.raise_for_status()
        new_feeds = resp.json()
        if not isinstance(new_feeds, list):
            raise ValueError("Remote data is not a list")
        config = {}
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        config["rss_feeds"] = new_feeds
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✅ Обновлено {len(new_feeds)} источников.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
if __name__ == "__main__":
    update_sources()
