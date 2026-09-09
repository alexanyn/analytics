from dataclasses import dataclass
from typing import Optional
@dataclass
class Article:
    title: str
    link: str
    summary: str = ""
    author: str = ""
    feed_url: str = ""
    category: Optional[str] = None
    published_ts: Optional[float] = None
