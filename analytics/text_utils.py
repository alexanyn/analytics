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



def is_generic_description(text: str) -> bool:
    """Проверяет, является ли текст мусором (404, футер, общее описание сайта)."""
    if not text:
        return True
    
    t = text.lower().strip()
    
    # 404 и ошибки
    if any(x in t for x in ["we can't find the page", "404", "page not found", "cannot be found", "we are sorry", "не найдена"]):
        return True

    # Футеры и копирайты
    if "©" in t or "copyright" in t or "все права защищены" in t:
        return True
    if t.startswith(("фонд", "развития и поддержки", "поддержки международного", "сетевое издание")):
        return True
    if "зарегистрировано федеральной службой" in t or "роскомнадзор" in t or "свидетельство о регистрации" in t:
        return True

    # Cookie-баннеры
    if "cookie" in t or "файлов cookie" in t or "используя сайт" in t or "политике обработки персональных данных" in t:
        return True

    # Markdown-ссылки в тексте (Jina отдает их как [текст](url)) — это скорее всего меню/баннер
    if "](http" in t or "](https" in t:
        return True

    # Текст начинается с "Используя" или "By using" (cookie-соглашения)
    if t.startswith(("используя", "by using", "продолжая использовать")):
        return True
    if "i\n©" in t or "©" in t[:50]: # Часто в начале футера
        return True
        
    # Общие описания
    generic_markers = [
        "since its founding", "since its inception", "established in", 
        "founded in", "has been the leading forum", "is a leading", 
        "is the leading", "is a global", "is an independent", "is a non-profit", 
        "is a nonprofit", "welcome to", "this is the homepage",
        "try searching our site"
    ]
    for marker in generic_markers:
        if marker in t:
            return True
            
    # Слишком много ссылок или подчёркиваний
    if t.startswith("_") or t.count("http") > 2:
        return True
        
    return False

def fetch_description_from_html(url: str) -> str:
    """Вытаскивает описание из HTML. Обходит редиректы Google News."""
    import requests
    from bs4 import BeautifulSoup

    if not url or not url.startswith("http"):
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    # 1. Пробуем обычный парсинг
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Ищем meta-теги (самый надёжный источник)
            for meta in [soup.find("meta", property="og:description"), 
                         soup.find("meta", attrs={"name": "description"}),
                         soup.find("meta", attrs={"name": "twitter:description"})]:
                if meta and meta.get("content", "").strip():
                    text = meta["content"].strip()
                    if len(text) > 40 and not is_generic_description(text):
                        return text[:900]

            # Ищем абзацы ТОЛЬКО внутри article/main — чтобы не поймать меню
            content_area = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"})
            if content_area:
                for p in content_area.find_all("p"):
                    text = p.get_text().strip()
                    # Отсеиваем меню, ссылки, короткие фрагменты
                    if (len(text) > 80 
                        and not text.startswith(("*", "[", "|", "http"))
                        and "http" not in text[:50]
                        and not is_generic_description(text)):
                        return text[:900]
    except Exception:
        pass

    # 2. Fallback — Jina Reader (обходит Cloudflare и JS-рендеринг)
    try:
        jina_url = f"https://r.jina.ai/{url}"
        resp = requests.get(jina_url, timeout=20)
        if resp.status_code == 200:
            text = resp.text
            if "Markdown Content:" in text:
                content = text.split("Markdown Content:")[-1].strip()
                for p in content.split("\n\n"):
                    p = p.strip()
                    if (len(p) > 80 
                        and not p.startswith(("!", "[", "##", "**", "|", "*", "http"))
                        and "http" not in p[:50]
                        and not is_generic_description(p)):
                        return p[:900]
    except Exception:
        pass

    return ""
