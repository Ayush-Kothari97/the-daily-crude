#!/usr/bin/env python3
"""
Daily content generator for The Daily Crude.
Triggered by GitHub Actions at 08:00 IST daily.
Calls OpenAI Responses API with web_search_preview to collect real market data,
then injects a DAILY_DATA JSON object into the HTML file.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────────────────
HTML_FILE = "index.html"
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).strftime("%A, %d %B %Y")
TODAY_SHORT = datetime.now(IST).strftime("%d %b %Y")
ISSUE_DATE = datetime.now(IST).strftime("%d %B %Y")

SYSTEM_PROMPT = f"""You are the data engine for The Daily Crude — a professional daily energy intelligence brief for upstream, midstream, and downstream professionals.

Today is {TODAY}.

TASK: Use web_search to fetch real current data, then return a single valid JSON object.

STRICT RULES:
- Call web_search MULTIPLE TIMES before writing your answer.
- Return ONLY raw JSON — no markdown fences, no explanation, no preamble.
- Every numeric field must contain a REAL number from your searches (e.g. "62.45", not "XX.XX").
- Every text field must contain REAL content (real headlines, real project names, real company names).
- The word "placeholder", the pattern "XX", and generic strings like "News headline" or "Project name" are FORBIDDEN in your output.

SEARCH PLAN (execute all of these before returning JSON):
1. Search "Brent crude oil price today {TODAY_SHORT}" → get $/bbl
2. Search "WTI crude oil price today {TODAY_SHORT}" → get $/bbl
3. Search "Dubai crude oil price today {TODAY_SHORT}" → get $/bbl
4. Search "JKM LNG spot price today {TODAY_SHORT}" → get $/MMBtu
5. Search "TTF natural gas price today {TODAY_SHORT}" → get €/MWh
6. Search "Henry Hub natural gas price today {TODAY_SHORT}" → get $/MMBtu
7. Search "OPEC basket price today {TODAY_SHORT}" → get $/bbl
8. Search "oil gas news today {TODAY_SHORT}" → top global O&G stories
9. Search "India oil gas energy news {TODAY_SHORT}" → India-specific stories
10. Search "oil gas project FID EPC award {TODAY_SHORT}" → major project milestones
11. Search "McKinsey BCG oil gas strategy framework 2025 2026" → for strategy section

JSON SCHEMA (replace every angle-bracket field with real searched data):

{{
  "meta": {{
    "date": "{TODAY}",
    "issue_date": "{ISSUE_DATE}",
    "last_updated": "08:00 IST"
  }},

  "ticker": [
    {{"label": "BRENT", "price": "<$/bbl from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "WTI", "price": "<$/bbl from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "DUBAI CRUDE", "price": "<$/bbl from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "JKM LNG", "price": "<$/MMBtu from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "TTF GAS", "price": "<€/MWh from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "HH NATGAS", "price": "<$/MMBtu from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "OPEC BASKET", "price": "<$/bbl from search>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "NAPHTHA CIF ARA", "price": "<$/MT estimated>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}},
    {{"label": "GASOIL ICE", "price": "<$/MT estimated>", "change": "<▲ or ▼ and %>", "direction": "<up|down|flat>"}}
  ],

  "markets": {{
    "macro_signal": "<One paragraph: today's key macro driver — e.g. OPEC+ decision, US inventory data, geopolitical event>",
    "prices": [
      {{
        "commodity": "Brent Crude (ICE)",
        "value": "<$/bbl>",
        "change_abs": "<±$/bbl>",
        "change_pct": "<±%>",
        "direction": "<up|down|flat>",
        "meta": "<one-line context e.g. front-month settlement, ICE>"
      }},
      {{
        "commodity": "WTI Crude (NYMEX)",
        "value": "<$/bbl>",
        "change_abs": "<±$/bbl>",
        "change_pct": "<±%>",
        "direction": "<up|down|flat>",
        "meta": "<one-line context>"
      }},
      {{
        "commodity": "JKM LNG Spot",
        "value": "<$/MMBtu>",
        "change_abs": "<±$/MMBtu>",
        "change_pct": "<±%>",
        "direction": "<up|down|flat>",
        "meta": "$/MMBtu · Platts assessed · NE Asia delivery"
      }},
      {{
        "commodity": "TTF Natural Gas",
        "value": "<€/MWh>",
        "change_abs": "<±€/MWh>",
        "change_pct": "<±%>",
        "direction": "<up|down|flat>",
        "meta": "€/MWh · ICE Endex · Front-Month"
      }}
    ],
    "drivers": [
      {{"icon": "🛢️", "headline": "<real market driver headline>", "body": "<2-3 sentences of detail>"}},
      {{"icon": "🌏", "headline": "<real market driver headline>", "body": "<2-3 sentences>"}},
      {{"icon": "🔥", "headline": "<real market driver headline>", "body": "<2-3 sentences>"}},
      {{"icon": "🤝", "headline": "<real market driver headline>", "body": "<2-3 sentences>"}}
    ]
  }},

  "india": {{
    "headline": "<real India O&G headline from today>",
    "headline_body": "<2-3 paragraphs on the headline story>",
    "news": [
      {{
        "sector": "Refining",
        "sector_color": "#c57800",
        "title": "<real news title>",
        "summary": "<2-3 sentence summary>",
        "source": "<publication name>"
      }},
      {{
        "sector": "Upstream",
        "sector_color": "#c8401a",
        "title": "<real news title>",
        "summary": "<2-3 sentence summary>",
        "source": "<publication name>"
      }}
    ],
    "stats": [
      {{"label": "India Crude Import Basket", "value": "<$/bbl>", "note": "Russia ~X% · ME ~X% · Others ~X% · PPAC"}},
      {{"label": "LNG Spot Import (Petronet Dahej)", "value": "<$/MMBtu>", "note": "Blended spot vs LTC pricing"}},
      {{"label": "ONGC Crude Production (YTD)", "value": "<X.X MMT>", "note": "Crude oil equiv. · vs annual target"}},
      {{"label": "India Refinery Throughput", "value": "<X.X MMT>", "note": "MoPNG · YTD vs capacity utilisation"}},
      {{"label": "India LNG Imports (YTD)", "value": "<X BCM>", "note": "vs prior year · PPAC"}}
    ]
  }},

  "global_news": [
    {{"sector": "Upstream · Exploration", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Policy · Regulation", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Midstream · LNG", "sector_class": "sector-midstream", "dot_color": "#8b4500", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Offshore · Subsea", "sector_class": "sector-offshore", "dot_color": "#1e4a7a", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Downstream · Petrochemicals", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "OPEC+ · Supply", "sector_class": "sector-upstream", "dot_color": "#8b1a00", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Refining · Margins", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Geopolitics · Sanctions", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "M&A · Corporate", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "<real headline>", "summary": "<2-3 sentences>", "source": "<source>"}}
  ],

  "strategy": {{
    "featured": {{
      "label": "⭐ Framework of the Day",
      "title": "<real framework title from McKinsey/BCG/WoodMac>",
      "tags": ["<tag1>", "<tag2>", "<tag3>"],
      "audience": "IOCs · NOCs · Private Equity · Strategy Consultants · EPC PMOs",
      "read_time": "<N min read>",
      "sources": "<publication names>",
      "url": "<real article URL found via web search>",
      "intro": "<opening paragraph>",
      "framework_title": "<framework subtitle>",
      "framework_desc": "<one paragraph describing the framework>",
      "steps": [
        {{"title": "<step 1 title>", "body": "<explanation>"}},
        {{"title": "<step 2 title>", "body": "<explanation>"}},
        {{"title": "<step 3 title>", "body": "<explanation>"}},
        {{"title": "<step 4 title>", "body": "<explanation>"}},
        {{"title": "<step 5 title>", "body": "<explanation>"}}
      ],
      "watchpoints_title": "Key Watchpoints for Consultants",
      "watchpoints": "<paragraph of watchpoints>"
    }},
    "mini_cards": [
      {{"label": "🔍 Upstream · Due Diligence", "title": "<real title>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "E&P / Consultant", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "<real URL>"}},
      {{"label": "🛢️ Midstream · LNG Strategy", "title": "<real title>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "LNG / Trading", "tag_bg": "var(--steel-light)", "tag_color": "var(--steel)", "url": "<real URL>"}},
      {{"label": "⚙️ Operations · EPC", "title": "<real title>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "PMC / EPC", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "<real URL>"}}
    ]
  }},

  "projects": [
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<EPC|FID|FEED|PDP|On Hold>", "stage_class": "<stage-epc|stage-fid|stage-feed|stage-pdp|stage-concept>", "value": "<$XB>", "location": "<City, Country>", "description": "<one sentence milestone>", "event": "<emoji + event label>", "event_color": "#1a5c38"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#c8401a"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1a5c38"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1e3a5f"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#c8401a"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1a5c38"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1e3a5f"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1a5c38"}},
    {{"name": "<real project name>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji + event label>", "event_color": "#1a5c38"}}
  ]
}}
"""

USER_PROMPT = f"""Today is {TODAY}. Execute the search plan from your instructions, then return the filled JSON.

Do NOT return angle-bracket placeholders like <real headline> or <$/bbl>. Replace every one with actual data from your searches.

Search now for: Brent price, WTI price, Dubai crude, JKM LNG, TTF gas, Henry Hub, OPEC basket, top O&G news, India energy news, major O&G project updates."""

# ── Validation ────────────────────────────────────────────────────────────────────────────
PLACEHOLDER_MARKERS = [
    "XX.XX", "X.XX%", "XX BCM", "XX.X MMT",
    "Project name", "News headline", "Framework title",
    "<real headline>", "<$/bbl>", "<real project",
    "real headline", "real news", "real title",
]

def _contains_placeholders(data: dict) -> bool:
    raw = json.dumps(data)
    return any(marker.lower() in raw.lower() for marker in PLACEHOLDER_MARKERS)

# ── API Call ────────────────────────────────────────────────────────────────────────────
MAX_RETRIES = 3

def fetch_content() -> dict:
    _key = os.environ.get("OPENAI_API_KEY", "")
    if not _key:
        sys.exit("ERROR: OPENAI_API_KEY not set in environment.")
    client = OpenAI(api_key=_key, timeout=300.0)
    del _key

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"Attempt {attempt}/{MAX_RETRIES}: calling OpenAI with web search...")

        user_input = USER_PROMPT
        if attempt > 1:
            user_input = (
                "PREVIOUS ATTEMPT FAILED — your response still had unfilled placeholders or template text. "
                "You MUST search the web for real data NOW and fill every field with actual values.\n\n"
                + USER_PROMPT
            )

        response = client.responses.create(
            model="gpt-4o",
            tools=[{"type": "web_search_preview"}],
            instructions=SYSTEM_PROMPT,
            input=user_input,
            max_output_tokens=16000,
        )

        raw = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw = block.text

        raw = re.sub(r"```json\s*|```", "", raw).strip()
        print(f"Response length: {len(raw)} chars")

        if not raw:
            last_error = "Empty response from API"
            print(f"Attempt {attempt} failed: {last_error}")
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e} — tail: ...{raw[-400:]}"
            print(f"Attempt {attempt} failed: {last_error}")
            continue

        if _contains_placeholders(data):
            raw_lower = json.dumps(data).lower()
            triggered = [m for m in PLACEHOLDER_MARKERS if m.lower() in raw_lower]
            last_error = f"Placeholder values detected: {triggered}"
            print(f"Attempt {attempt} failed: {last_error}")
            continue

        print("Content fetched and validated successfully.")
        return data

    sys.exit(f"ERROR: All {MAX_RETRIES} attempts failed. Last: {last_error}")


# ── HTML Injection ────────────────────────────────────────────────────────────────────────────────
def inject_into_html(data: dict):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    data_block = f'<script id="daily-data">\nwindow.DAILY_DATA = {json_str};\n</script>'

    if 'id="daily-data"' in html:
        html = re.sub(
            r'<script id="daily-data">.*?</script>',
            data_block,
            html,
            flags=re.DOTALL
        )
    else:
        html = html.replace("</head>", f"{data_block}\n</head>")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML updated: {HTML_FILE}")


# ── Entry Point ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = fetch_content()
    inject_into_html(data)
    print("Done.")
