#!/usr/bin/env python3
"""
Генерирует HTML-дашборд мониторинга аналитического дайджеста.
Читает metrics.jsonl и rss_health.json, создаёт dashboard.html.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta


CATEGORIES = [
    "Геополитика", "Экономика", "Бизнес",
    "Технологии", "Энергетика", "Безопасность",
]


def load_metrics(filename="metrics.jsonl"):
    if not os.path.exists(filename):
        return []
    rows = []
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def load_rss_health(filename="rss_health.json"):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def filter_last_week(metrics):
    cutoff = datetime.now() - timedelta(days=7)
    result = []
    for m in metrics:
        try:
            ts = datetime.fromisoformat(m.get("timestamp", ""))
            if ts >= cutoff:
                result.append(m)
        except Exception:
            pass
    return sorted(result, key=lambda x: x.get("timestamp", ""))


def compute_stats(metrics):
    if not metrics:
        return {"runs": 0, "success": 0, "rate": 0, "avg": 0, "total": 0}
    success = sum(1 for m in metrics if m.get("status") == "success")
    total = sum(m.get("articles", 0) for m in metrics)
    return {
        "runs": len(metrics),
        "success": success,
        "rate": round(success / len(metrics) * 100) if metrics else 0,
        "avg": round(total / len(metrics), 1) if metrics else 0,
        "total": total,
    }


def group_by_day(metrics):
    by_day = defaultdict(int)
    for m in metrics:
        try:
            ts = datetime.fromisoformat(m["timestamp"])
            by_day[ts.strftime("%d.%m")] += m.get("articles", 0)
        except Exception:
            pass
    days = sorted(by_day.keys(), key=lambda d: datetime.strptime(d, "%d.%m"))
    return days, [by_day[d] for d in days]


def format_runs_table(metrics, limit=15):
    rows = []
    for m in reversed(metrics[-limit:]):
        ts = m.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            t_str = dt.strftime("%d.%m %H:%M")
        except Exception:
            t_str = ts

        status = m.get("status", "unknown")
        if status == "success":
            tag = '<span class="tag tag-ok">Отправлен</span>'
        elif status == "send_failed":
            tag = '<span class="tag tag-bad">Ошибка отправки</span>'
        elif status.startswith("empty"):
            tag = '<span class="tag tag-warn">Нет статей</span>'
        else:
            tag = f'<span class="tag tag-warn">{status}</span>'

        errors = m.get("errors", [])
        err_text = "; ".join(errors)[:80] if errors else "—"
        dur = m.get("duration_seconds")
        dur_text = f"{dur:.0f}с" if dur else "—"

        rows.append(
            f"<tr><td class='mono'>{t_str}</td><td>{tag}</td>"
            f"<td class='mono num'>{m.get('articles', 0)}</td>"
            f"<td class='mono num'>{dur_text}</td>"
            f"<td class='dim'>{err_text}</td></tr>"
        )
    return "\n".join(rows)


def format_health(health):
    if not health:
        return ""
    summary = health.get("summary", {})
    details = health.get("details", [])
    dead = [d for d in details if d.get("status") == "dead"]
    stale = [d for d in details if d.get("status") == "stale"]

    def rows(items, key):
        if not items:
            return '<div class="dim">нет</div>'
        return "".join(
            f'<div class="src-row"><span class="mono">{d.get("source_name", "?")}</span>'
            f'<span class="dim"> — {d.get(key, "?")}</span></div>'
            for d in items[:15]
        )

    blocked = [d for d in details if d.get("status") == "dead" and d.get("known_blocked")]
    return f"""
  <section class="panel">
    <h2><span class="eyebrow">04</span> Здоровье RSS-источников</h2>
    <div class="health-grid">
      <div class="health-col">
        <div class="health-stat">
          <span class="mono big">{summary.get('ok', 0)}/{summary.get('total', 0)}</span>
          <span class="dim">источников в норме</span>
        </div>
        <h3>Мертвы ({summary.get('dead', 0)})</h3>
        {rows(dead, "error")}
        <h3>Протухли ({summary.get('stale', 0)})</h3>
        {rows(stale, "latest_entry_age_days")}
        <h3>Заблокированы ботозащитой ({summary.get('blocked', 0)})</h3>
        <div class="dim small">Эти источники защищены Cloudflare/пейволлом — блокировка ожидаема, не считается проблемой.</div>
      </div>
    </div>
  </section>"""


def generate():
    metrics = load_metrics()
    recent = filter_last_week(metrics)
    stats = compute_stats(recent)
    days, counts = group_by_day(recent)
    runs_html = format_runs_table(metrics)
    health = load_rss_health()
    health_html = format_health(health)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Analytics Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{ --bg:#0B0E14; --panel:#131822; --line:#262D3B; --fg:#EDEAE2; --dim:#8993A6; --amber:#F0A83C; --red:#E15241; --green:#52B8C4; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,'IBM Plex Sans',sans-serif; }}
  .mono {{ font-family:'SF Mono',Menlo,monospace; }}
  .dim {{ color:var(--dim); }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  header {{ padding:24px 32px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }}
  h1 {{ margin:0; font-size:18px; letter-spacing:.06em; text-transform:uppercase; }}
  .meta {{ color:var(--dim); font-size:13px; }}
  .strip {{ display:flex; border-bottom:1px solid var(--line); }}
  .strip .cell {{ flex:1; padding:22px 28px; border-right:1px solid var(--line); }}
  .strip .cell:last-child {{ border-right:none; }}
  .strip .big {{ display:block; font-family:'SF Mono',monospace; font-weight:700; font-size:30px; color:var(--amber); }}
  .strip .label {{ display:block; margin-top:6px; font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:var(--dim); }}
  main {{ max-width:1180px; margin:0 auto; padding:0 32px; }}
  section {{ padding:40px 0; border-bottom:1px solid var(--line); }}
  section:last-child {{ border-bottom:none; }}
  h2 {{ font-size:15px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; margin:0 0 20px 0; display:flex; align-items:baseline; gap:10px; }}
  h3 {{ font-size:13px; font-weight:600; margin:16px 0 6px 0; }}
  .eyebrow {{ font-family:'SF Mono',monospace; color:var(--amber); font-size:13px; }}
  .chart-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:4px; padding:20px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--dim); padding:8px 10px; border-bottom:1px solid var(--line); font-weight:500; }}
  th.num {{ text-align:right; }}
  td {{ padding:9px 10px; border-bottom:1px solid var(--line); }}
  tr:hover {{ background:var(--panel); }}
  .tag {{ font-family:'SF Mono',monospace; font-size:11px; padding:2px 8px; border-radius:3px; border:1px solid; }}
  .tag-ok {{ color:var(--amber); border-color:rgba(240,168,60,.35); background:rgba(240,168,60,.08); }}
  .tag-warn {{ color:#D8B948; border-color:rgba(216,185,72,.35); background:rgba(216,185,72,.08); }}
  .tag-bad {{ color:var(--red); border-color:rgba(225,82,65,.4); background:rgba(225,82,65,.1); }}
  .health-stat {{ margin-bottom:8px; }}
  .health-stat .big {{ font-family:'SF Mono',monospace; font-size:22px; color:var(--green); margin-right:8px; }}
  .src-row {{ font-size:13px; padding:3px 0; }}
  footer {{ max-width:1180px; margin:0 auto; padding:24px 32px; color:var(--dim); font-size:12px; }}
  @media (max-width:860px) {{ .strip {{ flex-direction:column; }} .strip .cell {{ border-right:none; border-bottom:1px solid var(--line); }} }}
</style></head>
<body>
<header>
  <h1>Analytics · Мониторинг</h1>
  <div class="meta">Обновлено {now} МСК</div>
</header>

<div class="strip">
  <div class="cell"><span class="big mono">{stats['runs']}</span><span class="label">Прогонов за 7 дней</span></div>
  <div class="cell"><span class="big mono">{stats['rate']}%</span><span class="label">Успешных</span></div>
  <div class="cell"><span class="big mono">{stats['avg']}</span><span class="label">Ср. статей / дайджест</span></div>
  <div class="cell"><span class="big mono">{stats['total']}</span><span class="label">Всего статей</span></div>
</div>

<main>
  <section>
    <h2><span class="eyebrow">01</span> Объём дайджестов</h2>
    <div class="chart-wrap"><canvas id="itemsChart" height="80"></canvas></div>
  </section>

  <section>
    <h2><span class="eyebrow">02</span> Последние прогоны</h2>
    <table>
      <thead><tr><th>Время</th><th>Статус</th><th class="num">Статей</th><th class="num">Длит.</th><th>Ошибки</th></tr></thead>
      <tbody>{runs_html}</tbody>
    </table>
  </section>
  {health_html}
</main>

<footer>metrics.jsonl · генерируется автоматически</footer>

<script>
new Chart(document.getElementById('itemsChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(days)},
    datasets: [{{
      label: 'Статей в дайджесте',
      data: {json.dumps(counts)},
      borderColor: '#F0A83C',
      backgroundColor: 'rgba(240,168,60,0.08)',
      borderWidth: 2, pointRadius: 3, fill: true, tension: 0.25,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#262D3B' }}, ticks: {{ color: '#8993A6' }} }},
      y: {{ grid: {{ color: '#262D3B' }}, ticks: {{ color: '#8993A6' }}, beginAtZero: true }}
    }}
  }}
}});
</script>
</body></html>"""

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ dashboard.html создан ({len(html)} байт, {len(metrics)} записей в metrics.jsonl)")


if __name__ == "__main__":
    generate()
