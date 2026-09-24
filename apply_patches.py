#!/usr/bin/env python3
"""Применяет 4 фикса к main.py: PR-блоки, дубли источника, мусор, модели Gemini."""

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

changes = []

# --- Fix 1a: Добавить FALLBACK_TRASH_KEYWORDS ---
anchor = '''LOCAL_CRIME_AND_TRIVIA_KEYWORDS = [
    "убил жену", "убил мужа", "убил дочь", "убил сына", "убил родствен",
    "застрелил", "зарезал", "ДТП", "сбил насмерть", "поджог дома",
    "бытовое убийство", "семейная ссора закончилась",
]'''
replacement = anchor + '''

# Список стоп-слов для фильтрации жёлтого/lifestyle-мусора в fallback-режиме.
FALLBACK_TRASH_KEYWORDS = [
    "дом-2", "дом 2", "голая", "голый", "обнажённ", "обнаженн",
    "инстаграм", "инстаграме", "тикток", "тик-ток",
    "звезда ютуб", "звезда инстаграм", "похудела", "накачала губы",
    "развод звезды", "пластическ", "светская хроника",
    "тайно женился", "тайно вышла замуж", "беременна от",
    "экс-участниц", "экс-участник", "курьёз", "курьез",
]'''
assert anchor in content, "Fix 1a: anchor not found"
content = content.replace(anchor, replacement, 1)
changes.append("1a. Добавлен FALLBACK_TRASH_KEYWORDS")

# --- Fix 1b: Заменить fallback-блок ---
anchor = '''    # === FALLBACK: если Gemini не дала новостей, но есть собранные ===
    if total_items == 0 and news_db:
        print("⚠️  Gemini не вернула категорий, используем сырые заголовки как fallback.")
        # Создаём временную категорию "raw" для отображения
        raw_items = []
        for news_id, info in list(news_db.items())[:30]:
            # Определим is_russia грубо по наличию слова "Россия" или "росси" в заголовке
            title = info.get("title", "")
            is_russia = "Россия" in title or "росси" in title.lower()
            raw_items.append({
                "id": news_id,
                "summary_ru": title,
                "is_russia": is_russia
            })
        # Помещаем их в категорию "raw" (нестандартную, но мы её обработаем отдельно)
        data["raw"] = raw_items
        total_items = len(raw_items)'''
replacement = '''    # === FALLBACK: если Gemini не дала новостей, но есть собранные ===
    is_fallback = False
    if total_items == 0 and news_db:
        is_fallback = True
        print("⚠️  Gemini не вернула категорий, используем сырые заголовки как fallback.")
        raw_items = []
        for news_id, info in list(news_db.items())[:40]:
            title = info.get("title", "")
            title_lower = title.lower()
            # Отсеиваем явный lifestyle/жёлтый мусор (в fallback-режиме
            # единственный доступный фильтр — Gemini недоступна)
            if any(kw in title_lower for kw in FALLBACK_TRASH_KEYWORDS):
                print(f"   🗑️  Fallback: отброшен мусор — «{title[:70]}»")
                continue
            # Российскость определяем по наличию кириллицы в заголовке
            is_russia = bool(re.search(r'[а-яёА-ЯЁ]', title))
            raw_items.append({
                "id": news_id,
                "summary_ru": title,
                "is_russia": is_russia,
            })
        data["raw"] = raw_items
        total_items = len(raw_items)
        print(f"   📰 После фильтрации мусора осталось {total_items} сырых заголовков.")'''
assert anchor in content, "Fix 1b: anchor not found"
content = content.replace(anchor, replacement, 1)
changes.append("1b. Fallback теперь фильтрует мусор и лучше определяет Россию")

# --- Fix 2: Force_show PR блоков отключаем в fallback ---
anchor = '''    pr_world_html, pr_world_urls = build_one(False, "📢 <b>PR В МИРЕ</b>", PR_SECTIONS, force_show=True)
    pr_russia_html, pr_russia_urls = build_one(True, "📢 <b>PR В РОССИИ</b>", PR_SECTIONS, force_show=True)'''
replacement = '''    # В fallback-режиме PR-блоки пусты и только путают — не форсируем их показ
    pr_force_show = not is_fallback
    pr_world_html, pr_world_urls = build_one(False, "📢 <b>PR В МИРЕ</b>", PR_SECTIONS, force_show=pr_force_show)
    pr_russia_html, pr_russia_urls = build_one(True, "📢 <b>PR В РОССИИ</b>", PR_SECTIONS, force_show=pr_force_show)'''
assert anchor in content, "Fix 2: anchor not found"
content = content.replace(anchor, replacement, 1)
changes.append("2. Пустые PR-блоки не показываются в fallback")

# --- Fix 3: Убрать дублирование источника в заголовке ---
old_line = '                safe_url = html_escape(url, quote=True)\n                safe_summary = html_escape(summary, quote=False)\n                safe_source = html_escape(source_name, quote=False)\n                html_output += f"• {safe_summary} (<a href=\\"{safe_url}\\">{safe_source}</a>)\\n"'
new_line = '''                # Убираем дублирующееся упоминание источника в самом заголовке
                # (Google News в заголовок уже добавляет " - Reuters" и т.п.)
                cleaned_summary = re.sub(
                    rf"\\s*[-–—|]\\s*{re.escape(source_name)}\\s*$",
                    "", summary, flags=re.IGNORECASE,
                ).strip()
                if not cleaned_summary:
                    cleaned_summary = summary
                safe_url = html_escape(url, quote=True)
                safe_summary = html_escape(cleaned_summary, quote=False)
                safe_source = html_escape(source_name, quote=False)
                html_output += f"• {safe_summary} (<a href=\\"{safe_url}\\">{safe_source}</a>)\\n"'''
assert old_line in content, "Fix 3: anchor not found"
content = content.replace(old_line, new_line, 1)
changes.append("3. Убрано дублирование имени источника в заголовках")

# --- Fix 4a: GEMINI_MODELS константа ---
anchor = '''MAX_FETCH_WORKERS = CONFIG["collection"]["max_fetch_workers"]'''
replacement = '''MAX_FETCH_WORKERS = CONFIG["collection"]["max_fetch_workers"]

# Список моделей Gemini: при 503 (перегружена) пробуем следующую.
GEMINI_MODELS = CONFIG.get("gemini_models", [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
])'''
assert anchor in content, "Fix 4a: anchor not found"
content = content.replace(anchor, replacement, 1)
changes.append("4a. Добавлена константа GEMINI_MODELS")

# --- Fix 4b: Переписать generate_analytical_json ---
start_marker = 'def generate_analytical_json(raw_data_prompt, recently_published_titles=None):'
end_marker = '\ndef postprocess_pr_classification(data, news_db):'
start_idx = content.find(start_marker)
end_idx = content.find(end_marker)
assert start_idx != -1 and end_idx != -1, "Fix 4b: boundaries not found"

new_function = '''def generate_analytical_json(raw_data_prompt, recently_published_titles=None):
    template = load_prompt_template()

    recently_published_titles = recently_published_titles or []
    if recently_published_titles:
        recent_block = (
            "\\n    СПРАВОЧНО — эти заголовки уже были опубликованы в недавних "
            "дайджестах (последние ~12 часов), читатель их уже видел. Если "
            "среди входящих новостей ниже есть такая, что по сути описывает "
            "ТО ЖЕ САМОЕ событие, что и один из этих заголовков — даже другим "
            "источником, другими словами или на другом языке — НЕ включай её "
            "снова. Включай повторно ТОЛЬКО если новость содержит существенно "
            "НОВУЮ фактуру:\\n"
            + "\\n".join(f"    - {t}" for t in recently_published_titles)
            + "\\n"
        )
    else:
        recent_block = ""

    company_filter = ""
    cs = CONFIG.get("company_significance", {})
    if cs.get("global_major"):
        company_filter += "Крупные мировые компании: " + ", ".join(cs["global_major"]) + ".\\n"
    if cs.get("global_well_known"):
        company_filter += "Широко узнаваемые компании: " + ", ".join(cs["global_well_known"]) + ".\\n"
    if cs.get("russian_major"):
        company_filter += "Российские компании-лидеры: " + ", ".join(cs["russian_major"]) + ".\\n"
    if company_filter:
        company_filter = "ФИЛЬТР ПО ЗНАЧИМОСТИ КОМПАНИЙ:\\n" + company_filter + "\\nДля business/technology новости о компаниях включай, только если компания в одном из этих списков (кроме случаев, когда само событие значимо для отрасли). Для pr это правило НЕ применяется.\\n"

    prompt = template.replace("__RECENT_CONTEXT__", recent_block)
    prompt = prompt.replace("__INPUT_DATA__", raw_data_prompt)
    prompt = prompt.replace("__MAX_ITEMS__", str(MAX_ITEMS_PER_CATEGORY_PER_REGION))
    prompt = prompt.replace("__COMPANY_FILTER__", company_filter)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 65536,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }

    empty_fallback = json.dumps({
        "geopolitics": [], "economics": [], "business": [],
        "technology": [], "energy": [], "security": [], "pr": [],
    })

    gemini_call_start = time.time()
    max_retries_per_model = 3
    total_attempts = 0
    gemini_meta = {
        "latency_sec": None,
        "attempts_used": 0,
        "fallback_used": False,
        "error_type": None,
        "error_detail": None,
        "models_tried": [],
    }

    for model_index, model_name in enumerate(GEMINI_MODELS):
        print(f"🤖 Пробуем модель: {model_name} ({model_index + 1}/{len(GEMINI_MODELS)})")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={gemini_api_key}"
        )
        gemini_meta["models_tried"].append(model_name)

        for attempt in range(max_retries_per_model):
            total_attempts += 1
            try:
                response = requests.post(url, json=payload, timeout=280)

                if response.status_code == 400:
                    try:
                        error_data = response.json()
                        error_message = error_data.get("error", {}).get("message", "")
                        if "safety" in error_message.lower() or "blocked" in error_message.lower():
                            print(f"⛔ Gemini заблокировал запрос: {error_message[:200]}")
                            gemini_meta["error_type"] = "safety_block"
                        else:
                            print(f"❌ Некорректный запрос к Gemini (400): {response.text[:200]}")
                            gemini_meta["error_type"] = "invalid_request"
                        gemini_meta["error_detail"] = error_message
                    except Exception:
                        print(f"❌ Некорректный запрос к Gemini (400): {response.text[:200]}")
                        gemini_meta["error_type"] = "invalid_request"
                    gemini_meta["latency_sec"] = round(time.time() - gemini_call_start, 1)
                    gemini_meta["attempts_used"] = total_attempts
                    gemini_meta["fallback_used"] = True
                    return empty_fallback, gemini_meta

                if response.status_code == 429:
                    try:
                        data = response.json()
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        wait_time = min(retry_after, 60)
                    except Exception:
                        wait_time = 10
                    print(f"⏸️  Rate limit 429 ({model_name}). Ждём {wait_time}с...")
                    time.sleep(wait_time)
                    continue

                if response.status_code == 503:
                    wait_time = min(20 * (2 ** attempt), 60)
                    print(f"⏸️  API перегружена (503, {model_name}). Ждём {wait_time}с...")
                    time.sleep(wait_time)
                    continue

                if response.status_code >= 500:
                    wait_time = min(10 * (2 ** attempt), 60)
                    print(f"⚠️  Ошибка сервера ({response.status_code}, {model_name}). Ждём {wait_time}с...")
                    time.sleep(wait_time)
                    continue

                if response.status_code == 200:
                    result = response.json()
                    gemini_meta["latency_sec"] = round(time.time() - gemini_call_start, 1)
                    gemini_meta["attempts_used"] = total_attempts
                    gemini_meta["fallback_used"] = False
                    gemini_meta["model_used"] = model_name
                    return result["candidates"][0]["content"]["parts"][0]["text"], gemini_meta

                print(f"❌ Ошибка Gemini API ({response.status_code}): {response.text[:200]}")
                response.raise_for_status()

            except requests.exceptions.Timeout:
                wait_time = 10 * (attempt + 1)
                print(f"⏸️  Timeout ({model_name}). Ждём {wait_time}с...")
                time.sleep(wait_time)
                continue
            except Exception as e:
                print(f"⚠️  Исключение ({model_name}): {str(e)[:100]}")
                if attempt < max_retries_per_model - 1:
                    time.sleep(5 * (attempt + 1))
                continue

        print(f"⚠️  Модель {model_name} не ответила, пробуем следующую.")

    print("❌ Все модели Gemini недоступны. Используем fallback.")
    gemini_meta["latency_sec"] = round(time.time() - gemini_call_start, 1)
    gemini_meta["attempts_used"] = total_attempts
    gemini_meta["fallback_used"] = True
    gemini_meta["error_type"] = "all_models_failed"
    return empty_fallback, gemini_meta


'''

content = content[:start_idx] + new_function + content[end_idx + 1:]

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Патч успешно применён:")
for c in changes:
    print(f"   • {c}")
print("   • 4b. Мультимодельный Gemini (при 503 переключается на следующую модель)")
