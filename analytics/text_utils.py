import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# analytics/text_utils.py
import re


def normalize_for_dedup(title: str) -> str:
    """Нормализует заголовок для дедупликации."""
    if not title:
        return ""
    s = title.lower().strip()
    s = re.sub(r"\s+[-–—|]\s+[^\s].{0,80}$", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def looks_translated(original: str, translated: str) -> bool:
    """True если перевод выглядит успешным (появилась кириллица или текст не менялся)."""
    if not translated or not original:
        return False
    if translated.strip() == original.strip():
        return False
    o_ratio = _cyrillic_ratio(original)
    t_ratio = _cyrillic_ratio(translated)
    # Оригинал не русский, а перевод всё ещё без кириллицы → провал
    if o_ratio < 0.3 and t_ratio < 0.3:
        return False
    return True


def fetch_description_from_html(url: str) -> str:
    """Вытаскивает og:description или meta description из HTML страницы."""
    import requests
    from bs4 import BeautifulSoup

    if not url or not url.startswith("http"):
        return ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. og:description
        og = soup.find("meta", property="og:description")
        if og and og.get("content") and len(og["content"].strip()) > 30:
            return og["content"].strip()

        # 2. name="description"
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content") and len(desc["content"].strip()) > 30:
            return desc["content"].strip()

        # 3. twitter:description
        tw = soup.find("meta", attrs={"name": "twitter:description"})
        if tw and tw.get("content") and len(tw["content"].strip()) > 30:
            return tw["content"].strip()

    except Exception:
        pass
    return ""
