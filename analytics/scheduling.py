import datetime
import time
import logging
from .config import load_config
logger = logging.getLogger("analytics_digest")
MOSCOW_OFFSET = datetime.timedelta(hours=3)
MOSCOW_TZ = datetime.timezone(MOSCOW_OFFSET)
def now_moscow():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(MOSCOW_TZ)
def wait_until_publish_time():
    config = load_config().scheduling
    if not config.enabled:
        return
    max_wait = config.max_publish_wait_seconds
    now = now_moscow()
    target = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now > target:
        target += datetime.timedelta(days=1)
    wait = (target - now).total_seconds()
    if wait <= 0:
        return
    if wait > max_wait:
        logger.warning(f"Публикуем раньше расписания: до цели {int(wait)}с > {max_wait}с")
        return
    logger.info(f"Ждём до {target.strftime('%H:%M:%S МСК')} ({int(wait)}с)")
    time.sleep(wait)
