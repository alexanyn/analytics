from __future__ import annotations
import html
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    from . import text_utils as tu
except ImportError:
    import text_utils as tu

CATEGORY_ORDER = [("Геополитика", "🌍"), ("Экономика", "📈"), ("Бизнес", "💼"), ("Технологии", "💻"), ("Энергетика", "⚡"), ("Безопасность", "🛡")]
TG_LIMIT = 32000
FALLBACK_DESC = "Подробности в источнике."
SEPARATOR = "─" * 16

def format_card(a: dict) -> str:
    title_raw = tu.post_process_text(a.get("title_ru") or a.get("title") or "")
    title_raw = tu.strip_source_suffix(title_raw, a.get("source", "")) or (a.get("title") or "")
    if not title_raw.strip(): return ""
    desc_raw = tu.post_process_text(a.get("description") or "") or FALLBACK_DESC
    title = html.escape(title_raw, quote=False)
    desc = html.escape(desc_raw, quote=False)
    url = html.escape((a.get("url") or "").strip(), quote=True)
    src_name = html.escape(a.get("source") or "Источник", quote=False)
    return f"<b>{title}</b>\n\n{desc}\n\n<i><a href=\"{url}\">{src_name}</a></i>"

def build_messages(by_cat: dict) -> list:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    header = f"📊 <b>АНАЛИТИЧЕСКИЙ ДАЙДЖЕСТ</b> — {now:%d.%m.%Y}"
    messages = []
    current = header
    def flush():
        nonlocal current
        if current.strip(): messages.append(current.strip())
        current = ""
    for cat, emoji in CATEGORY_ORDER:
        items = by_cat.get(cat) or []
        if not items: continue
        cat_block = f"\n\n{SEPARATOR}\n\n{emoji} <b>{cat.upper()}</b>\n\n"
        if len(current) + len(cat_block) > TG_LIMIT: flush(); current = f"{emoji} <b>{cat.upper()} (продолжение)</b>\n\n"; first_card = True
        else: current += cat_block; first_card = True
        for a in items:
            card = format_card(a)
            if not card: continue
            if not first_card: card = f"\n\n{SEPARATOR}\n\n" + card
            if len(current) + len(card) > TG_LIMIT: flush(); current = f"{emoji} <b>{cat.upper()} (продолжение)</b>\n\n" + card
            else: current += card
            first_card = False
    flush()
    return messages
