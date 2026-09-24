# analytics/translators.py
import os
import time
import threading
import logging
import requests

logger = logging.getLogger("analytics_digest")

# ============ Rate limiter для deep-translator ============
_TRANSLATE_LOCK = threading.Lock()
_LAST_CALL = [0.0]
_MIN_INTERVAL = 0.35  # ~2.85 запроса/сек — с запасом под лимит Google 5/сек


def _rate_limit():
    """Блокирует поток, пока не пройдёт минимальный интервал между запросами."""
    with _TRANSLATE_LOCK:
        elapsed = time.time() - _LAST_CALL[0]
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _LAST_CALL[0] = time.time()


def _cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    cyr = sum(1 for c in text if "а" <= c.lower() <= "я" or c == "ё")
    return cyr / len(text)


def _translate_via_deeptranslator(text: str) -> str:
    """Перевод через deep-translator с глобальным rate limit и retry."""
    from deep_translator import GoogleTranslator

    chunk = text[:4500]
    for attempt in range(3):
        _rate_limit()
        try:
            translated = GoogleTranslator(source="auto", target="ru").translate(chunk)
            if translated and translated.strip() and translated.strip() != chunk.strip():
                return translated.strip()
        except Exception as e:
            err = str(e).lower()
            if "too many requests" in err or "server error" in err:
                wait = 2 ** attempt + 1
                logger.debug(f"deep-translator rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            logger.debug(f"deep-translator failed: {e}")
            return ""
    return ""


def _translate_combined_via_deeptranslator(title: str, summary: str) -> tuple[str, str]:
    """Переводит title + summary одним запросом через разделитель."""
    SEP = "\n||||\n"
    combined = f"{title}{SEP}{summary}" if summary else title
    translated = _translate_via_deeptranslator(combined)
    if not translated:
        return "", ""
    if SEP.strip() in translated:
        parts = translated.split(SEP.strip(), 1)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    # Модель потеряла разделитель — вернём всё как title, summary пустой
    return translated.strip(), ""


def translate_and_summarize(text: str, is_summary: bool = False) -> str:
    """Устаревшая функция для совместимости. Использует только deep-translator."""
    if not text or len(text.strip()) < 3:
        return text
    if _cyrillic_ratio(text) > 0.3:
        return text
    translated = _translate_via_deeptranslator(text)
    return translated if translated else text


def translate_article(title: str, summary: str) -> tuple[str, str]:
    """Основной API: переводит title и summary одним запросом. Возвращает (t_title, t_summary)."""
    t_cyr = _cyrillic_ratio(title) > 0.3
    s_cyr = _cyrillic_ratio(summary) > 0.3 if summary else True

    if t_cyr and s_cyr:
        return title, summary  # всё уже на русском

    t_title, t_summary = _translate_combined_via_deeptranslator(
        title if not t_cyr else "",
        summary if not s_cyr else "",
    )

    # Если один из блоков был уже русским — вернём оригинал
    final_title = title if t_cyr else (t_title or title)
    final_summary = summary if s_cyr else (t_summary or summary)

    return final_title, final_summary
