import json
import os
import logging
from datetime import datetime
from typing import List, Optional
logger = logging.getLogger("analytics_digest")
def log_metrics(status: str, article_count: int = 0, category_count: int = 0,
                errors: Optional[List[str]] = None, duration: Optional[float] = None):
    metrics_file = "metrics.jsonl"
    try:
        metric = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "articles": article_count,
            "categories": category_count,
            "errors": errors or [],
        }
        if duration is not None:
            metric["duration_seconds"] = round(duration, 1)
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Не удалось записать метрику: {e}")
def send_alert(status: str, errors: List[str] = None):
    if status not in ("crashed", "send_failed"):
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    icon = "🔴" if status == "crashed" else "🟡"
    status_text = {"crashed": "необработанный сбой", "send_failed": "ошибка отправки"}.get(status, status)
    lines = [f"{icon} <b>АЛЕРТ дайджеста:</b> {status_text}"]
    if errors:
        lines.append("Детали: " + "; ".join(errors)[:300])
    alert_text = "\n".join(lines)
    try:
        from .senders import _send_one_chunk
        _send_one_chunk(chat_id, alert_text, token)
        logger.info(f"Алерт отправлен ({status})")
    except Exception as e:
        logger.warning(f"Не удалось отправить алерт: {e}")
