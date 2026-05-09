#!/usr/bin/env python3
"""
Daily content generator for The Daily Crude.
- Prices: fetched directly via yfinance (reliable, no AI hallucination)
- News/analysis: fetched via OpenAI Responses API with web_search
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import yfinance as yf
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────────────────
HTML_FILE = "index.html"
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).strftime("%A, %d %B %Y")
TODAY_SHORT = datetime.now(IST).strftime("%d %b %Y")
ISSUE_DATE = datetime.now(IST).strftime("%d %B %Y")

# ── Price fetching via yfinance ───────────────────────────────────────────────────────────────────
TICKERS = {
    "BRENT":  "BZ=F",
    "WTI":    "CL=F",
    "HH_GAS": "NG=F",
}

def _fmt_price(val, prefix="$", suffix="", decimals=2):
    if val is None:
        return "N/A"
    return f"{prefix}{val:,.{decimals}f}{suffix}"

def _fmt_change(change_abs, change_pct):
    if change_abs is None or change_pct is None:
        return "N/A", "flat"
    arrow = "▲" if change_abs >= 0 else "▼"
    direction = "up" if change_abs > 0 else ("down" if change_abs < 0 else "flat")
    sign = "+" if change_abs >= 0 else ""
    return f"{arrow} {sign}{change_pct:.2f}%", direction

def fetch_prices():
    prices = {}
    for name, ticker_sym in TICKERS.items():
        try:
            t = yf.Ticker(ticker_sym)
            info = t.fast_info
            price = getattr(info, "last_price", None)
            prev  = getattr(info, "previous_close", None)
            if price and prev:
                change_abs = price - prev
                change_pct = (change_abs / prev) * 100
            else:
                change_abs = change_pct = None
            prices[name] = {"price": price, "change_abs": change_abs, "change_pct": change_pct}
            print(f"  {name}: {price} (prev {prev})")
        except Exception as e:
            print(f"  {name}: fetch failed — {e}")
            prices[name] = {"price": None, "change_abs": None, "change_pct": None}
    return prices

def build_ticker_and_markets(prices, ai_prices: dict) -> tuple:
    def get(key):
        return prices.get(key, {})

    brent = get("BRENT")
    wti   = get("WTI")
    hh    = get("HH_GAS")

    brent_chg, brent_dir = _fmt_change(brent.get("change_abs"), brent.get("change_pct"))
    wti_chg,   wti_dir   = _fmt_change(wti.get("change_abs"),   wti.get("change_pct"))
    hh_chg,    hh_dir    = _fmt_change(hh.get("change_abs"),    hh.get("change_pct"))

    brent_price = _fmt_price(brent.get("price"), "$", "/bbl")
    wti_price   = _fmt_price(wti.get("price"),   "$", "/bbl")
    hh_price    = _fmt_price(hh.get("price"),    "$", "/MMBtu")

    dubai_price  = ai_prices.get("dubai_price",  "N/A")
    dubai_chg    = ai_prices.get("dubai_change",  "N/A")
    dubai_dir    = ai_prices.get("dubai_dir",     "flat")
    jkm_price    = ai_prices.get("jkm_price",    "N/A")
    jkm_chg      = ai_prices.get("jkm_change",   "N/A")
    jkm_dir      = ai_prices.get("jkm_dir",      "flat")
    ttf_price    = ai_prices.get("ttf_price",    "N/A")
    ttf_chg      = ai_prices.get("ttf_change",   "N/A")
    ttf_dir      = ai_prices.get("ttf_dir",      "flat")
    opec_price   = ai_prices.get("opec_price",   "N/A")
    opec_chg     = ai_prices.get("opec_change",  "N/A")
    opec_dir     = ai_prices.get("opec_dir",     "flat")
    naph_price   = ai_prices.get("naph_price",   "N/A")
    naph_chg     = ai_prices.get("naph_change",  "N/A")
    naph_dir     = ai_prices.get("naph_dir",     "flat")
    gasoil_price = ai_prices.get("gasoil_price", "N/A")
    gasoil_chg   = ai_prices.get("gasoil_change","N/A")
    gasoil_dir   = ai_prices.get("gasoil_dir",   "flat")

    brent_abs = brent.get("change_abs")
    wti_abs   = wti.get("change_abs")
    brent_pct = brent.get("change_pct")
    wti_pct   = wti.get("change_pct")

    ticker = [
        {"label": "BRENT",          "price": brent_price,  "change": brent_chg,  "direction": brent_dir},
        {"label": "WTI",            "price": wti_price,    "change": wti_chg,    "direction": wti_dir},
        {"label": "DUBAI CRUDE",    "price": dubai_price,  "change": dubai_chg,  "direction": dubai_dir},
        {"label": "JKM LNG",        "price": jkm_price,    "change": jkm_chg,    "direction": jkm_dir},
        {"label": "TTF GAS",        "price": ttf_price,    "change": ttf_chg,    "direction": ttf_dir},
        {"label": "HH NATGAS",      "price": hh_price,     "change": hh_chg,     "direction": hh_dir},
        {"label": "OPEC BASKET",    "price": opec_price,   "change": opec_chg,   "direction": opec_dir},
        {"label": "NAPHTHA CIF ARA","price": naph_price,   "change": naph_chg,   "direction": naph_dir},
        {"label": "GASOIL ICE",     "price": gasoil_price, "change": gasoil_chg, "direction": gasoil_dir},
    ]

    def signed(v, prefix="$"):
        if v is None: return "N/A"
        return f"{prefix}{'+' if v>=0 else ''}{v:.2f}"

    markets_prices = [
        {
            "commodity": "Brent Crude (ICE)",
            "value":      _fmt_price(brent.get("price"), "$"),
            "change_abs": signed(brent_abs),
            "change_pct": f"{'+' if (brent_pct or 0)>=0 else ''}{brent_pct:.2f}%" if brent_pct is not None else "N/A",
            "direction":  brent_dir,
            "meta":       "$/bbl · ICE · Front-Month",
        },
        {
            "commodity": "WTI Crude (NYMEX)",
            "value":      _fmt_price(wti.get("price"), "$"),
            "change_abs": signed(wti_abs),
            "change_pct": f"{'+' if (wti_pct or 0)>=0 else ''}{wti_pct:.2f}%" if wti_pct is not None else "N/A",
            "direction":  wti_dir,
            "meta":       "$/bbl · NYMEX · Front-Month",
        },
        {
            "commodity": "JKM LNG Spot",
            "value":      jkm_price,
            "change_abs": ai_prices.get("jkm_abs", "N/A"),
            "change_pct": jkm_chg,
            "direction":  jkm_dir,
            "meta":       "$/MMBtu · Platts assessed · NE Asia delivery",
        },
        {
            "commodity": "TTF Natural Gas",
            "value":      ttf_price,
            "change_abs": ai_prices.get("ttf_abs", "N/A"),
            "change_pct": ttf_chg,
            "direction":  ttf_dir,
            "meta":       "€/MWh · ICE Endex · Front-Month",
        },
    ]

    return ticker, markets_prices


# ── OpenAI content fetch ────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are the data engine for The Daily Crude — a professional daily energy intelligence brief.

Today is {TODAY}.

Your job is to use web_search to find:
1. Prices for: Dubai crude, JKM LNG spot, TTF natural gas, OPEC basket, Naphtha CIF ARA, Gasoil ICE
2. Today's top O&G news (global and India-specific)
3. Major O&G project updates (FIDs, EPC awards, FEED starts)
4. A strategy framework from McKinsey/BCG/Wood Mackenzie

Return ONLY a raw JSON object — no markdown, no backticks, no explanation.
All fields must contain REAL values from your searches. Generic text like "News headline" or "Project name" is forbidden.
"""

USER_PROMPT = f"""Today is {TODAY}.

Search for these prices now and return them in the JSON:
- Dubai crude oil price {TODAY_SHORT}
- JKM LNG spot price {TODAY_SHORT}
- TTF natural gas price {TODAY_SHORT}
- OPEC basket price {TODAY_SHORT}
- Naphtha CIF ARA price {TODAY_SHORT}
- Gasoil ICE price {TODAY_SHORT}

Also search for top oil & gas news, India energy news, major O&G project updates, and an O&G strategy framework.

Return this exact JSON (fill ALL fields with real data):
{{
  "prices": {{
    "dubai_price":   "<e.g. $72.30/bbl>",
    "dubai_change":  "<e.g. ▲ +0.85%>",
    "dubai_dir":     "<up|down|flat>",
    "jkm_price":     "<e.g. $12.40/MMBtu>",
    "jkm_change":    "<e.g. ▼ -1.20%>",
    "jkm_dir":       "<up|down|flat>",
    "jkm_abs":       "<e.g. -$0.15/MMBtu>",
    "ttf_price":     "<e.g. €34.50/MWh>",
    "ttf_change":    "<e.g. ▲ +2.10%>",
    "ttf_dir":       "<up|down|flat>",
    "ttf_abs":       "<e.g. +€0.71/MWh>",
    "opec_price":    "<e.g. $71.80/bbl>",
    "opec_change":   "<e.g. ▲ +1.10%>",
    "opec_dir":      "<up|down|flat>",
    "naph_price":    "<e.g. $610/MT>",
    "naph_change":   "<e.g. ▼ -0.50%>",
    "naph_dir":      "<up|down|flat>",
    "gasoil_price":  "<e.g. $720/MT>",
    "gasoil_change": "<e.g. ▲ +0.30%>",
    "gasoil_dir":    "<up|down|flat>"
  }},
  "macro_signal": "<one paragraph on today's key macro driver>",
  "drivers": [
    {{"icon": "🛢️", "headline": "<real headline>", "body": "<2-3 sentences>"}},
    {{"icon": "🌏", "headline": "<real headline>", "body": "<2-3 sentences>"}},
    {{"icon": "🔥", "headline": "<real headline>", "body": "<2-3 sentences>"}},
    {{"icon": "🤝", "headline": "<real headline>", "body": "<2-3 sentences>"}}
  ],
  "india": {{
    "headline": "<real India O&G headline>",
    "headline_body": "<2-3 paragraphs>",
    "news": [
      {{"sector": "Refining", "sector_color": "#c57800", "title": "<real title>", "summary": "<2-3 sentences>", "source": "<source>"}},
      {{"sector": "Upstream", "sector_color": "#c8401a", "title": "<real title>", "summary": "<2-3 sentences>", "source": "<source>"}}
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
    {{"sector": "Upstream · Exploration", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Policy · Regulation", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Midstream · LNG", "sector_class": "sector-midstream", "dot_color": "#8b4500", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Offshore · Subsea", "sector_class": "sector-offshore", "dot_color": "#1e4a7a", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Downstream · Petrochemicals", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "OPEC+ · Supply", "sector_class": "sector-upstream", "dot_color": "#8b1a00", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Refining · Margins", "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "Geopolitics · Sanctions", "sector_class": "sector-policy", "dot_color": "#5a3a00", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}},
    {{"sector": "M&A · Corporate", "sector_class": "sector-upstream", "dot_color": "#c8401a", "title": "<real>", "summary": "<2-3 sentences>", "source": "<source>"}}
  ],
  "strategy": {{
    "featured": {{
      "label": "⭐ Framework of the Day",
      "title": "<real framework title>",
      "tags": ["<tag1>", "<tag2>", "<tag3>"],
      "audience": "IOCs · NOCs · Private Equity · Strategy Consultants · EPC PMOs",
      "read_time": "<N min read>",
      "sources": "<publication>",
      "url": "<real URL>",
      "intro": "<opening paragraph>",
      "framework_title": "<subtitle>",
      "framework_desc": "<one paragraph>",
      "steps": [
        {{"title": "<step 1>", "body": "<explanation>"}},
        {{"title": "<step 2>", "body": "<explanation>"}},
        {{"title": "<step 3>", "body": "<explanation>"}},
        {{"title": "<step 4>", "body": "<explanation>"}},
        {{"title": "<step 5>", "body": "<explanation>"}}
      ],
      "watchpoints_title": "Key Watchpoints for Consultants",
      "watchpoints": "<paragraph>"
    }},
    "mini_cards": [
      {{"label": "🔍 Upstream · Due Diligence", "title": "<real>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "E&P / Consultant", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "<real URL>"}},
      {{"label": "🛢️ Midstream · LNG Strategy", "title": "<real>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "LNG / Trading", "tag_bg": "var(--steel-light)", "tag_color": "var(--steel)", "url": "<real URL>"}},
      {{"label": "⚙️ Operations · EPC", "title": "<real>", "desc": "<2 sentences>", "read_time": "<N min>", "tag": "PMC / EPC", "tag_bg": "var(--tag-bg)", "tag_color": "var(--ink)", "url": "<real URL>"}}
    ]
  }},
  "projects": [
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<EPC|FID|FEED|PDP>", "stage_class": "<stage-epc|stage-fid|stage-feed|stage-pdp>", "value": "<$XB>", "location": "<City, Country>", "description": "<one sentence>", "event": "<emoji label>", "event_color": "#1a5c38"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#c8401a"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1a5c38"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1e3a5f"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#c8401a"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1a5c38"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1e3a5f"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1a5c38"}},
    {{"name": "<real project>", "company": "<operator>", "sector": "<sector>", "data_sector": "<lng|upstream|midstream|downstream>", "stage": "<stage>", "stage_class": "<class>", "value": "<$XB>", "location": "<City, Country>", "event": "<emoji label>", "event_color": "#1a5c38"}}
  ]
}}"""

PLACEHOLDER_MARKERS = [
    "XX.XX", "X.XX%", "News headline", "Project name", "Framework title",
    "<real headline>", "<real>", "<real project>", "<$/bbl>", "<€/MWh>",
]

def _has_placeholders(data: dict) -> list:
    raw = json.dumps(data).lower()
    return [m for m in PLACEHOLDER_MARKERS if m.lower() in raw]

def fetch_ai_content() -> dict:
    _key = os.environ.get("OPENAI_API_KEY", "")
    if not _key:
        sys.exit("ERROR: OPENAI_API_KEY not set.")
    client = OpenAI(api_key=_key, timeout=300.0)
    del _key

    for attempt in range(1, 4):
        print(f"OpenAI attempt {attempt}/3...")
        prefix = "" if attempt == 1 else (
            "PREVIOUS ATTEMPT HAD UNFILLED PLACEHOLDERS. Search the web and fill every field with real data.\n\n"
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
            print(f"  JSON error: {e}, retrying...")
            continue
        bad = _has_placeholders(data)
        if bad:
            print(f"  Placeholders still present: {bad}, retrying...")
            continue
        print("  AI content validated.")
        return data

    print("WARNING: AI content failed all retries — using fallback empty content.")
    return {}


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
    print(f"HTML updated.")


# ── Main ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Fetching prices via yfinance ===")
    prices = fetch_prices()

    print("\n=== Fetching news/analysis via OpenAI ===")
    ai = fetch_ai_content()

    ai_prices = ai.get("prices", {})
    ticker, markets_prices = build_ticker_and_markets(prices, ai_prices)

    daily_data = {
        "meta": {
            "date": TODAY,
            "issue_date": ISSUE_DATE,
            "last_updated": "08:00 IST",
        },
        "ticker": ticker,
        "markets": {
            "macro_signal": ai.get("macro_signal", ""),
            "prices": markets_prices,
            "drivers": ai.get("drivers", []),
        },
        "india": ai.get("india", {}),
        "global_news": ai.get("global_news", []),
        "strategy": ai.get("strategy", {}),
        "projects": ai.get("projects", []),
    }

    print("\n=== Injecting into HTML ===")
    inject_into_html(daily_data)
    print("Done.")
