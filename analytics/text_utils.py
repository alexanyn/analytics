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


def _fetch_via_jina(url: str) -> str:
    """Jina Reader — бесплатный API для извлечения текста из любой страницы.
    Обходит Cloudflare, Google News редиректы и пейволлы (иногда)."""
    import requests
    try:
        # Jina Reader ожидает URL в конце пути
        jina_url = f"https://r.jina.ai/{url}"
        resp = requests.get(jina_url, timeout=15)
        if resp.status_code != 200:
            return ""

        text = resp.text
        if "Markdown Content:" in text:
            # Отрезаем мета-данные Jina (Title, URL Source, Published Time)
            content = text.split("Markdown Content:")[-1].strip()
            # Ищем первый содержательный абзац
            for p in content.split("\n\n"):
                p = p.strip()
                if len(p) > 50 and not p.startswith(("!", "[", "##", "**", "|")):
                    return p[:1000]
    except Exception as e:
        import logging
        logging.getLogger("analytics_digest").debug(f"Jina failed: {e}")
    return ""


def fetch_description_from_html(url: str) -> str:
    """Вытаскивает описание из HTML. Если URL — Google News, идёт через Jina."""
    import requests
    from bs4 import BeautifulSoup

    if not url or not url.startswith("http"):
        return ""

    # 1. Google News ссылки не содержат описания — только редирект.
    #    Jina Reader умеет следовать редиректу и парсить конечную статью.
    if "news.google.com" in url:
        return _fetch_via_jina(url)

    # 2. Обычные сайты — пробуем стандартный парсинг
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(url, headers=headers, timeout=8, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            og = soup.find("meta", property="og:description")
            if og and og.get("content", "").strip():
                return og["content"].strip()

            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content", "").strip():
                return desc["content"].strip()

            # Если нет meta — берём первый абзац
            for p in soup.find_all("p"):
                text = p.get_text().strip()
                if len(text) > 50:
                    return text
    except Exception:
        pass

    # 3. Если стандартный парсинг не сработал (Cloudflare, редирект, JS) — Jina
    return _fetch_via_jina(url)
