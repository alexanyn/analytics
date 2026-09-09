import json
import os
from typing import List, Optional
from pydantic import BaseModel, Field
class DedupConfig(BaseModel):
    title_similarity_threshold_same_run: float = 0.50
    title_similarity_threshold_cross_run: float = 0.55
    recent_titles_window_hours: int = 72
class DigestConfig(BaseModel):
    max_items_per_category: int = 5
class CollectionConfig(BaseModel):
    max_fetch_workers: int = 15
class SchedulingConfig(BaseModel):
    max_publish_wait_seconds: int = 600
    publish_grace_seconds: int = 1800
    enabled: bool = True
class AppConfig(BaseModel):
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    collection: CollectionConfig = Field(default_factory=CollectionConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    rss_feeds: List[str] = []
    max_age_days: int = 3
DEFAULT_CONFIG = AppConfig()
def load_config() -> AppConfig:
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                user_data = json.load(f)
            return AppConfig(**user_data)
        except Exception:
            pass
    return DEFAULT_CONFIG
