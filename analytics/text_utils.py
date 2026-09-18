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
