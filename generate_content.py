#!/usr/bin/env python3
"""
Daily content generator for The Daily Crude.
Fetches prices and news from curated O&G sources via OpenAI web_search.
Sources: oilprice.com, ogj.com, opec.org, offshore-mag.com, upstreamonline.com,
         lngindustry.com, hartenergy.com, rigzone.com, argusmedia.com, etc.
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

# ── Trusted source list (from Energy Industry Reference Database) ─────────────────
PRICE_SOURCES = "oilprice.com, ogj.com, opec.org, eia.gov, argusmedia.com, spglobal.com/commodityinsights"
NEWS_SOURCES = "ogj.com, worldoil.com, offshore-mag.com, upstreamonline.com, lngindustry.com, hartenergy.com, rigzone.com, offshore-energy.biz, energyvoice.com, hydrocarbonprocessing.com, pgjonline.com"
INDIA_SOURCES = "ogj.com, energyvoice.com, upstreamonline.com, hartenergy.com, offshore-energy.biz"
STRATEGY_SOURCES = "woodmac.com, mckinsey.com, bcg.com, rystadenergy.com, hartenergy.com, spglobal.com"

SYSTEM_PROMPT = f"""You are the data engine for The Daily Crude — a professional daily energy intelligence brief for upstream, midstream, and downstream O&G professionals.

Today is {TODAY}.

You have access to web_search. Use it to fetch real, current data from these TRUSTED SOURCES ONLY:

PRICE SOURCES (search these for commodity prices): {PRICE_SOURCES}
NEWS SOURCES (search these for O&G news): {NEWS_SOURCES}
INDIA SOURCES (search these for India energy news): {INDIA_SOURCES}
STRATEGY SOURCES (search these for frameworks): {STRATEGY_SOURCES}

RULES:
1. Call web_search multiple times — once for prices, once for global news, once for India news, once for projects, once for strategy.
2. Return ONLY a raw JSON object. No markdown fences, no explanation.
3. All numeric fields must contain REAL numbers. No XX, no placeholders.
4. All text fields must contain REAL headlines, real project names, real company names sourced from the above sites.
"""

USER_PROMPT = f"""Today is {TODAY}.

Execute these searches in order, then return the complete JSON:

SEARCH 1 — Prices: Search oilprice.com and ogj.com for today's Brent crude, WTI crude, Dubai crude, Henry Hub, TTF gas, JKM LNG, OPEC basket, Naphtha CIF ARA, Gasoil ICE prices.

SEARCH 2 — Global O&G news: Search ogj.com, offshore-mag.com, upstreamonline.com, rigzone.com, offshore-energy.biz for today's top upstream, midstream, LNG, offshore, refining, OPEC+, geopolitics, and M&A news.

SEARCH 3 — India energy news: Search ogj.com, upstreamonline.com, hartenergy.com for today's India crude imports, refinery, LNG, ONGC/IOC/BPCL/Reliance news.

SEARCH 4 — Projects: Search offshore-mag.com, upstreamonline.com, offshore-energy.biz, lngindustry.com for recent FID, EPC award, FEED commencement, first oil milestones.

SEARCH 5 — Strategy: Search woodmac.com, mckinsey.com, bcg.com for a current O&G strategy framework relevant to today's market.

Return this exact JSON with ALL fields filled from real search results:
{{
  "meta": {{
    "date": "{TODAY}",
    "issue_date": "{ISSUE_DATE}",
    "last_updated": "08:00 IST"
  }},
  "ticker": [
    {{"label": "BRENT",          "price": "actual $/bbl from oilprice.com or ogj.com", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "WTI",            "price": "actual $/bbl", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "DUBAI CRUDE",    "price": "actual $/bbl", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "JKM LNG",        "price": "actual $/MMBtu", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "TTF GAS",        "price": "actual €/MWh", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "HH NATGAS",      "price": "actual $/MMBtu", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "OPEC BASKET",    "price": "actual $/bbl from opec.org", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "NAPHTHA CIF ARA","price": "actual $/MT", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "GASOIL ICE",     "price": "actual $/MT", "change": "▲/▼ actual%", "direction": "up or down or flat"}}
  ],
  "markets": {{
    "macro_signal": "One real paragraph on today's key macro driver from your searches",
    "prices": [
      {{"commodity": "Brent Crude (ICE)", "value": "actual $/bbl", "change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up or down or flat", "meta": "$/bbl · ICE · Front-Month"}},
      {{"commodity": "WTI Crude (NYMEX)", "value": "actual $/bbl", "change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up or down or flat", "meta": "$/bbl · NYMEX · Front-Month"}},
      {{"commodity": "JKM LNG Spot", "value": "actual $/MMBtu", "change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up or down or flat", "meta": "$/MMBtu · Platts assessed · NE Asia delivery"}},
      {{"commodity": "TTF Natural Gas", "value": "actual €/MWh", "change_abs": "actual ±€", "change_pct": "actual ±%", "direction": "up or down or flat", "meta": "€/MWh · ICE Endex · Front-Month"}}
    ],
    "drivers": [
      {{"icon": "🛢️", "headline": "real headline from ogj.com or oilprice.com", "body": "2-3 sentences with real detail"}},
      {{"icon": "🌏", "headline": "real headline", "body": "2-3 sentences"}},
      {{"icon": "🔥", "headline": "real headline", "body": "2-3 sentences"}},
      {{"icon": "🤝", "headline": "real headline", "body": "2-3 sentences"}}
    ]
  }},
  "india": {{
    "headline": "Real India O&G headline from your searches",
    "headline_body": "2-3 real paragraphs on the story",
    "news": [
      {{"sector": "Refining", "sector_color": "#c57800", "title": "Real title from search", "summary": "2-3 sentence real summary", "source": "OGJ or Upstream Online or similar"}},
      {{"sector": "Upstream", "sector_color": "#c8401a", "title": "Real title from search", "summary": "2-3 sentence real summary", "source": "real source name"}}
    ],
    "stats": [
      {{"label": "India Crude Import Basket", "value": "actual $/bbl", "note": "Russia ~X% · ME ~X% · Others ~X% · PPAC"}},
      {{"label": "LNG Spot Import (Petronet Dahej)", "value": "actual $/MMBtu", "note": "Blended spot vs LTC pricing"}},
      {{"label": "ONGC Crude Production (YTD)", "value": "actual X.X MMT", "note": "Crude oil equiv. · vs annual target"}},
      {{"label": "India Refinery Throughput", "value": "actual X.X MMT", "note": "MoPNG · YTD vs capacity utilisation"}},
      {{"label": "India LNG Imports (YTD)", "value": "actual X BCM", "note": "vs prior year · PPAC"}}
    ]
  }},
  "global_news": [
    {{"sector": "Upstream · Exploration", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "Real headline from ogj.com or upstreamonline.com", "summary": "2-3 real sentences", "source": "OGJ"}},
    {{"sector": "Policy · Regulation", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "Real headline", "summary": "2-3 real sentences", "source": "real source"}},
    {{"sector": "Midstream · LNG", "sector_class": "sector-midstream", "dot_color": "#8b4500", "title": "Real headline from lngindustry.com or offshore-energy.biz", "summary": "2-3 real sentences", "source": "LNG Industry"}},
    {{"sector": "Offshore · Subsea", "sector_class": "sector-offshore", "dot_color": "#1e4a7a", "title": "Real headline from offshore-mag.com", "summary": "2-3 real sentences", "source": "Offshore Magazine"}},
    {{"sector": "Downstream · Petrochemicals", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "Real headline from hydrocarbonprocessing.com", "summary": "2-3 real sentences", "source": "Hydrocarbon Processing"}},
    {{"sector": "OPEC+ · Supply", "sector_class": "sector-upstream", "dot_color": "#8b1a00", "title": "Real headline", "summary": "2-3 real sentences", "source": "OGJ or World Oil"}},
    {{"sector": "Refining · Margins", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "Real headline", "summary": "2-3 real sentences", "source": "real source"}},
    {{"sector": "Geopolitics · Sanctions", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "Real headline", "summary": "2-3 real sentences", "source": "real source"}},
    {{"sector": "M&A · Corporate", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "Real headline from hartenergy.com", "summary": "2-3 real sentences", "source": "Hart Energy"}}
  ],
  "strategy": {{
    "featured": {{
      "label": "⭐ Framework of the Day",
      "title": "Real framework title from woodmac.com, mckinsey.com, or bcg.com",
      "tags": ["real tag1", "real tag2", "real tag3"],
      "audience": "IOCs · NOCs · Private Equity · Strategy Consultants · EPC PMOs",
      "read_time": "actual N min read",
      "sources": "Wood Mackenzie or McKinsey or BCG",
      "url": "real URL found via web search",
      "intro": "Real opening paragraph about the framework",
      "framework_title": "Real framework subtitle",
      "framework_desc": "Real one paragraph describing the framework",
      "steps": [
        {{"title": "Real step 1", "body": "Real explanation"}},
        {{"title": "Real step 2", "body": "Real explanation"}},
        {{"title": "Real step 3", "body": "Real explanation"}},
        {{"title": "Real step 4", "body": "Real explanation"}},
        {{"title": "Real step 5", "body": "Real explanation"}}
      ],
      "watchpoints_title": "Key Watchpoints for Consultants",
      "watchpoints": "Real paragraph of watchpoints"
    }},
    "mini_cards": [
      {{"label": "🔍 Upstream · Due Diligence", "title": "Real article title", "desc": "2 real sentences", "read_time": "actual N min", "tag": "E&P / Consultant", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "real URL"}},
      {{"label": "🛢️ Midstream · LNG Strategy", "title": "Real article title", "desc": "2 real sentences", "read_time": "actual N min", "tag": "LNG / Trading", "tag_bg": "var(--steel-light)", "tag_color": "var(--steel)", "url": "real URL"}},
      {{"label": "⚙️ Operations · EPC", "title": "Real article title", "desc": "2 real sentences", "read_time": "actual N min", "tag": "PMC / EPC", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "real URL"}}
    ]
  }},
  "projects": [
    {{"name": "Real project name from offshore-mag.com or upstreamonline.com", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "EPC or FID or FEED or PDP", "stage_class": "stage-epc or stage-fid or stage-feed or stage-pdp", "value": "actual $XB", "location": "Real City, Real Country", "description": "One real sentence on milestone", "event": "✅ EPC Awarded", "event_color": "#1a5c38"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#c8401a"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1a5c38"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1e3a5f"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#c8401a"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1a5c38"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1e3a5f"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1a5c38"}},
    {{"name": "Real project name", "company": "Real operator", "sector": "real sector", "data_sector": "lng or upstream or midstream or downstream", "stage": "real stage", "stage_class": "real class", "value": "actual $XB", "location": "Real City, Real Country", "event": "real emoji + label", "event_color": "#1a5c38"}}
  ]
}}"""

# ── Validation ────────────────────────────────────────────────────────────────────────────
BAD_PATTERNS = [
    "xx.xx", "x.xx%", "actual $/bbl", "actual €", "actual ±", "actual x",
    "real headline", "real project", "real operator", "real title", "real city",
    "real sector", "real stage", "real class", "real url", "real source",
    "news headline", "project name", "framework title",
]

def _has_placeholders(data: dict) -> list:
    raw = json.dumps(data).lower()
    return [p for p in BAD_PATTERNS if p in raw]

# ── API Call ────────────────────────────────────────────────────────────────────────────
def fetch_content() -> dict:
    _key = os.environ.get("OPENAI_API_KEY", "")
    if not _key:
        sys.exit("ERROR: OPENAI_API_KEY not set.")
    client = OpenAI(api_key=_key, timeout=300.0)
    del _key

    for attempt in range(1, 4):
        print(f"Attempt {attempt}/3: searching trusted O&G sources...")
        prefix = "" if attempt == 1 else (
            f"ATTEMPT {attempt}: Your previous response still had unfilled fields. "
            f"Search oilprice.com for prices, ogj.com and offshore-mag.com for news. Fill EVERY field with real data.\n\n"
        )
        response = client.responses.create(
            model="gpt-4o",
            tools=[{"type": "web_search_preview"}],
            instructions=SYSTEM_PROMPT,
            input=prefix + USER_PROMPT,
            max_output_tokens=16000,
        )
        raw = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw = block.text

        raw = re.sub(r"```json\s*|```", "", raw).strip()
        print(f"  Response: {len(raw)} chars")

        if not raw:
            print("  Empty response, retrying...")
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  JSON error: {e}")
            continue

        bad = _has_placeholders(data)
        if bad:
            print(f"  Still has placeholders: {bad[:5]}")
            continue

        print("  Validated.")
        return data

    sys.exit("ERROR: All 3 attempts failed — check OPENAI_API_KEY and workflow logs.")


# ── HTML Injection ────────────────────────────────────────────────────────────────────────────────
def inject_into_html(data: dict):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    data_block = f'<script id="daily-data">\nwindow.DAILY_DATA = {json_str};\n</script>'
    if 'id="daily-data"' in html:
        html = re.sub(r'<script id="daily-data">.*?</script>', data_block, html, flags=re.DOTALL)
    else:
        html = html.replace("</head>", f"{data_block}\n</head>")
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML updated.")


# ── Entry Point ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = fetch_content()
    inject_into_html(data)
    print("Done.")
