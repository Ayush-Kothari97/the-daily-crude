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

# ── Config ────────────────────────────────────────────────────────────────────
HTML_FILE = "index.html"
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).strftime("%A, %d %B %Y")
TODAY_SHORT = datetime.now(IST).strftime("%d %b %Y")
ISSUE_DATE = datetime.now(IST).strftime("%d %B %Y")

SYSTEM_PROMPT = f"""You are the data engine for The Daily Crude — a professional daily energy intelligence brief for upstream, midstream, and downstream professionals.

Today is {TODAY}.

Your job is to collect real, current market data and news via web search, then return a single valid JSON object that will be injected into the newsletter's HTML.

CRITICAL RULES:
1. Use the web_search tool extensively to fetch real prices, real news, and real project updates.
2. Return ONLY a valid JSON object. No markdown, no backticks, no preamble, no explanation.
3. All prices must be real and sourced from today or the most recent available data.
4. All news must be from the last 24-48 hours where possible, otherwise the most recent available.
5. Dates in the output should reflect today: {TODAY_SHORT}.

Return this exact JSON structure (fill all values with real data):

{{
  "meta": {{
    "date": "{TODAY}",
    "issue_date": "{ISSUE_DATE}",
    "last_updated": "08:00 IST"
  }},

  "ticker": [
    {{"label": "BRENT", "price": "$XX.XX/bbl", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "WTI", "price": "$XX.XX/bbl", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "DUBAI CRUDE", "price": "$XX.XX/bbl", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "JKM LNG", "price": "$XX.XX/MMBtu", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "TTF GAS", "price": "€XX.XX/MWh", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "HH NATGAS", "price": "$X.XX/MMBtu", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "OPEC BASKET", "price": "$XX.XX/bbl", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "NAPHTHA CIF ARA", "price": "$XXX/MT", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}},
    {{"label": "GASOIL ICE", "price": "$XXX/MT", "change": "▲/▼ X.XX%", "direction": "up|down|flat"}}
  ],

  "markets": {{
    "macro_signal": "One paragraph headline summary of today's key macro driver in energy markets.",
    "prices": [
      {{
        "commodity": "Brent Crude (ICE)",
        "value": "$XX.XX",
        "change_abs": "-$X.XX",
        "change_pct": "-X.XX%",
        "direction": "down",
        "meta": "Brief contextual note"
      }},
      {{
        "commodity": "WTI Crude (NYMEX)",
        "value": "$XX.XX",
        "change_abs": "-$X.XX",
        "change_pct": "-X.XX%",
        "direction": "down",
        "meta": "Brief contextual note"
      }},
      {{
        "commodity": "JKM LNG Spot",
        "value": "$XX.XX",
        "change_abs": "-$X.XX",
        "change_pct": "-X.XX%",
        "direction": "down",
        "meta": "$/MMBtu · Platts assessed · NE Asia delivery"
      }},
      {{
        "commodity": "TTF Natural Gas",
        "value": "€XX.XX",
        "change_abs": "-€X.XX",
        "change_pct": "-X.XX%",
        "direction": "down",
        "meta": "€/MWh · ICE Endex · Front-Month"
      }}
    ],
    "drivers": [
      {{"icon": "🛢️", "headline": "Short bold headline", "body": "2-3 sentence detail on this market driver."}},
      {{"icon": "🌏", "headline": "Short bold headline", "body": "2-3 sentence detail."}},
      {{"icon": "🔥", "headline": "Short bold headline", "body": "2-3 sentence detail."}},
      {{"icon": "🤝", "headline": "Short bold headline", "body": "2-3 sentence detail."}}
    ]
  }},

  "india": {{
    "headline": "Full headline title of today's top India energy story",
    "headline_body": "2-3 paragraph summary of the headline story.",
    "news": [
      {{
        "sector": "Refining",
        "sector_color": "#c57800",
        "title": "News card title",
        "summary": "2-3 sentence summary.",
        "source": "Source Name"
      }},
      {{
        "sector": "Upstream",
        "sector_color": "#c8401a",
        "title": "News card title",
        "summary": "2-3 sentence summary.",
        "source": "Source Name"
      }}
    ],
    "stats": [
      {{"label": "India Crude Import Basket", "value": "$XX.XX/bbl", "note": "Russia ~X% · ME ~X% · Others ~X% · PPAC"}},
      {{"label": "LNG Spot Import (Petronet Dahej)", "value": "$XX.XX/MMBtu", "note": "Blended spot vs LTC pricing"}},
      {{"label": "ONGC Crude Production (YTD)", "value": "XX.X MMT", "note": "Crude oil equiv. · vs annual target"}},
      {{"label": "India Refinery Throughput", "value": "XX.X MMT", "note": "MoPNG · YTD vs capacity utilisation"}},
      {{"label": "India LNG Imports (YTD)", "value": "XX BCM", "note": "vs prior year · PPAC"}}
    ]
  }},

  "global_news": [
    {{
      "sector": "Upstream · Exploration",
      "sector_class": "sector-upstream",
      "dot_color": "#c8401a",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Policy · Regulation",
      "sector_class": "sector-policy",
      "dot_color": "#5a3a00",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Midstream · LNG",
      "sector_class": "sector-midstream",
      "dot_color": "#8b4500",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Offshore · Subsea",
      "sector_class": "sector-offshore",
      "dot_color": "#1e4a7a",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Downstream · Petrochemicals",
      "sector_class": "sector-downstream",
      "dot_color": "#1e3a5f",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "OPEC+ · Supply",
      "sector_class": "sector-upstream",
      "dot_color": "#8b1a00",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Refining · Margins",
      "sector_class": "sector-downstream",
      "dot_color": "#1e3a5f",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "Geopolitics · Sanctions",
      "sector_class": "sector-policy",
      "dot_color": "#5a3a00",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }},
    {{
      "sector": "M&A · Corporate",
      "sector_class": "sector-upstream",
      "dot_color": "#c8401a",
      "title": "News headline",
      "summary": "2-3 sentence summary.",
      "source": "Source"
    }}
  ],

  "strategy": {{
    "featured": {{
      "label": "⭐ Framework of the Day",
      "title": "Framework title",
      "tags": ["Tag1", "Tag2", "Tag3"],
      "audience": "IOCs · NOCs · Private Equity · Strategy Consultants · EPC PMOs",
      "read_time": "~X min read",
      "sources": "McKinsey, BCG, Wood Mackenzie",
      "intro": "Opening italic paragraph.",
      "framework_title": "The Framework — subtitle",
      "framework_desc": "One paragraph describing the framework.",
      "steps": [
        {{"title": "Step title", "body": "Step explanation."}},
        {{"title": "Step title", "body": "Step explanation."}},
        {{"title": "Step title", "body": "Step explanation."}},
        {{"title": "Step title", "body": "Step explanation."}},
        {{"title": "Step title", "body": "Step explanation."}}
      ],
      "watchpoints_title": "Key Watchpoints for Consultants",
      "watchpoints": "Paragraph of watchpoints text."
    }},
    "mini_cards": [
      {{
        "label": "🔍 Upstream · Due Diligence",
        "title": "Mini card title",
        "desc": "2-sentence description.",
        "read_time": "~X min",
        "tag": "E&P / Consultant",
        "tag_bg": "var(--tag-bg)",
        "tag_color": "var(--ink)"
      }},
      {{
        "label": "🛢️ Midstream · LNG Strategy",
        "title": "Mini card title",
        "desc": "2-sentence description.",
        "read_time": "~X min",
        "tag": "LNG / Trading",
        "tag_bg": "var(--steel-light)",
        "tag_color": "var(--steel)"
      }},
      {{
        "label": "⚙️ Operations · EPC",
        "title": "Mini card title",
        "desc": "2-sentence description.",
        "read_time": "~X min",
        "tag": "PMC / EPC",
        "tag_bg": "var(--tag-bg)",
        "tag_color": "var(--ink)"
      }}
    ]
  }},

  "projects": [
    {{
      "name": "Project name",
      "company": "Operator / Contractor",
      "sector": "LNG Export",
      "data_sector": "lng",
      "stage": "EPC",
      "stage_class": "stage-epc",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "✅ EPC Awarded",
      "event_color": "#1a5c38"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Upstream",
      "data_sector": "upstream",
      "stage": "On Hold",
      "stage_class": "stage-concept",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "⚖️ Regulatory Hold",
      "event_color": "#c8401a"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Deepwater",
      "data_sector": "upstream",
      "stage": "FID",
      "stage_class": "stage-fid",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "🟢 FID Taken",
      "event_color": "#1a5c38"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "LNG Terminal",
      "data_sector": "lng",
      "stage": "FEED",
      "stage_class": "stage-feed",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "📋 FEED Commenced",
      "event_color": "#1e3a5f"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Refinery",
      "data_sector": "downstream",
      "stage": "PDP",
      "stage_class": "stage-pdp",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "📌 PDP Stage",
      "event_color": "#c8401a"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Offshore",
      "data_sector": "upstream",
      "stage": "EPC",
      "stage_class": "stage-epc",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "✅ EPC Awarded",
      "event_color": "#1a5c38"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Gas Processing",
      "data_sector": "midstream",
      "stage": "FEED",
      "stage_class": "stage-feed",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "📋 FEED Award",
      "event_color": "#1e3a5f"
    }},
    {{
      "name": "Project name",
      "company": "Operator",
      "sector": "Petrochemicals",
      "data_sector": "downstream",
      "stage": "EPC",
      "stage_class": "stage-epc",
      "value": "$X.XB",
      "location": "Location, Country",
      "event": "✅ EPC in Progress",
      "event_color": "#1a5c38"
    }},
    {{
      "name": "Project name",
      "company": "Operator / Partners",
      "sector": "LNG Regasification",
      "data_sector": "lng",
      "stage": "EPC",
      "stage_class": "stage-epc",
      "value": "$X.XB est.",
      "location": "Location, Country",
      "event": "✅ EPC in Progress",
      "event_color": "#1a5c38"
    }}
  ]
}}
"""

USER_PROMPT = f"""Today is {TODAY}.

Use web search to gather all current data. Search for:
1. Real-time O&G commodity prices: Brent crude, WTI crude, Dubai crude, JKM LNG spot, TTF natural gas, Henry Hub, OPEC basket price, Naphtha CIF ARA, Gasoil ICE
2. Top oil & gas news from the last 24 hours across: upstream E&P, LNG markets, offshore, midstream pipelines, downstream refining, petrochemicals, OPEC+ policy, geopolitics/sanctions affecting oil flows, O&G M&A
3. India-specific O&G news: crude imports, refinery throughput, LNG imports, ONGC/IOC/BPCL/Reliance updates, government petroleum policy
4. Major O&G project updates: FIDs, EPC awards, FEED commencements, first oil milestones, LNG project sanctions, refinery expansions
5. An O&G strategy framework relevant to today's upstream, midstream, or downstream market conditions

Focus strictly on oil & gas. Do not include renewables, wind, solar, hydrogen, CCUS, nuclear, or carbon markets.
Search broadly and return the complete JSON as specified. Be precise with numbers and attribute all data to real sources."""

# ── API Call ───────────────────────────────────────────────────────────────────
MAX_RETRIES = 3

def fetch_content() -> dict:
    _key = os.environ.get("OPENAI_API_KEY", "")
    if not _key:
        sys.exit("ERROR: OPENAI_API_KEY not set in environment.")
    client = OpenAI(api_key=_key, timeout=240.0)
    del _key

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"Calling OpenAI API with web search (attempt {attempt}/{MAX_RETRIES})...")
        response = client.responses.create(
            model="gpt-4o",
            tools=[{"type": "web_search_preview"}],
            instructions=SYSTEM_PROMPT,
            input=USER_PROMPT,
            max_output_tokens=16000,
        )

        raw = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw = block.text

        raw = re.sub(r"```json|```", "", raw).strip()

        try:
            data = json.loads(raw)
            print("Content fetched and parsed successfully.")
            return data
        except json.JSONDecodeError as e:
            print(f"JSON parse error (attempt {attempt}): {e}")
            print(f"Response length: {len(raw)} chars — Raw tail: ...{raw[-200:]}")
            if attempt == MAX_RETRIES:
                sys.exit(f"Failed after {MAX_RETRIES} attempts — last error: {e}")
            print("Retrying...")

    sys.exit("Unreachable")


# ── HTML Injection ─────────────────────────────────────────────────────────────
def inject_into_html(data: dict):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    data_block = f"<script id=\"daily-data\">\nwindow.DAILY_DATA = {json_str};\n</script>"

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


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = fetch_content()
    inject_into_html(data)
    print("Done.")
