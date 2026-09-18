# analytics/text_utils.py
import re


def normalize_for_dedup(title: str) -> str:
    """Нормализует заголовок для дедупликации: убирает суффикс источника,
    пунктуацию, приводит к нижнему регистру."""
    if not title:
        return ""
    s = title.lower().strip()
    # Убираем хвостовой суффикс источника: " - CSIS", " | Центр...", " – Features. csis. org"
    s = re.sub(r"\s+[-–—|]\s+[^\s].{0,80}$", "", s)
    # Только буквы, цифры, пробелы
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s
