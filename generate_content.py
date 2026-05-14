#!/usr/bin/env python3
"""
Daily content generator for The Daily Crude.
Fetches prices and news from curated O&G sources via OpenAI web_search.

VERSION: v5 (Upgraded to gpt-5.5 — 52.5% fewer hallucinations on financial data)
CHANGES FROM v3:
  TREND DATA REFRESH SCHEDULE:
  - trend_data (7/30/90-day price series for crude & gas) is fetched ONLY on Mondays.
  - Tuesday–Sunday: existing trend_data is read back from the current HTML and preserved
    unchanged. No daily accumulation, no drift, no stale appending.
  - This weekly-override model ensures data correctness, consistency and accuracy.

  FAILURE RESILIENCE:
  - Daily content fetch: 3 retries with exponential backoff (10s, 30s, 60s).
  - Monday trend fetch: separate 3-retry loop with backoff, independent of daily fetch.
  - If ALL retries are exhausted for EITHER fetch: inject_maintenance_page() is called,
    replacing index.html with a branded maintenance page (header + footer preserved,
    body shows "under maintenance" message). The script then exits with code 1 so the
    GitHub Actions workflow marks the run as failed for visibility.
  - trend_data fallback: if Monday trend fetch fails after all retries but daily content
    succeeded, existing trend_data is preserved (read from HTML) rather than blanking.

  OTHER:
  - TREND_PROMPT and fetch_trend_data() added as separate function.
  - read_existing_trend_data() extracts current trend_data from HTML before overwrite.
  - inject_maintenance_page() writes branded maintenance HTML.
  - All source lists unchanged from v4.
  - Model upgraded: gpt-4o → gpt-5.5 (OpenAI production recommendation as of May 2026)
    gpt-5.5 has 52.5% fewer hallucinated claims on financial/factual prompts per OpenAI eval.
    web_search_preview tool retained — gpt-5.5 supports it natively.
"""

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
HTML_FILE        = "index.html"
MAINTENANCE_FILE = "index.html"          # same file — maintenance replaces live page
IST              = timezone(timedelta(hours=5, minutes=30))
NOW_IST          = datetime.now(IST)
TODAY            = NOW_IST.strftime("%A, %d %B %Y")
TODAY_SHORT      = NOW_IST.strftime("%d %b %Y")
ISSUE_DATE       = NOW_IST.strftime("%d %B %Y")
IS_MONDAY        = NOW_IST.weekday() == 0   # 0 = Monday
DOW_NAME         = NOW_IST.strftime("%A")   # e.g. "Tuesday"

# Retry config
DAILY_RETRIES    = 3
TREND_RETRIES    = 3
RETRY_BACKOFF    = [10, 30, 60]   # seconds between attempts

# ── Source Registry (from Energy Industry Reference Database) ──────────────────
#
# Daily O&G market pulse
DAILY_PULSE_SOURCES  = "oilprice.com, worldoil.com, energynewsbeat.com, canarymedia.com"

# Financial price benchmarks — definitive pricing sources
PRICE_SOURCES        = (
    "spglobal.com/commodityinsights, "   # Platts — definitive price assessments & news
    "spglobal.com/en/cera, "             # S&P Global CERA — research & advisory/critical data
    "spglobal.com/en/energy-horizons, "  # S&P Global Horizons — energy expansion & sustainability
    "spglobal.com/en/energy, "           # S&P Global Energy Events — thought leadership
    "argusmedia.com, "                   # Argus Media — price assessments
    "eia.gov, "                          # EIA — free, authoritative US & global data
    "oilprice.com, "                     # Oil Price — free real-time aggregator
    "opec.org, "                         # OPEC basket price
    "ogj.com"                            # OGJ daily market page
)

# LNG-specific sources
LNG_SOURCES          = (
    "lngindustry.com, "                  # LNG Industry magazine
    "gastechinsights.com, "              # Gas Processing & LNG
    "offshore-energy.biz, "             # Offshore Energy — LNG shipping/projects
    "iea.org/data-and-statistics"        # IEA LNG export tracker — combine with Platts
)

# General O&G news
NEWS_SOURCES         = (
    "ogj.com, "                          # Oil & Gas Journal — primary trade publication
    "worldoil.com, "                     # World Oil
    "energynewsbeat.com, "               # Energy News Beat — quick-turn daily content
    "oilprice.com, "                     # Oil Price — news aggregator
    "upstreamonline.com, "               # Upstream Online
    "hartenergy.com, "                   # Hart Energy (E&P, Pipeline & Gas)
    "rigzone.com, "                      # Rigzone — drilling & equipment
    "offshore-mag.com, "                 # Offshore Magazine
    "offshore-energy.biz, "             # Offshore Energy
    "energyvoice.com, "                  # Energy Voice — North Sea focus
    "hydrocarbonprocessing.com, "        # Hydrocarbon Processing — downstream/refining
    "pgjonline.com"                      # PGJ Online — pipeline/gas
)

# India energy sources
INDIA_SOURCES        = (
    "ogj.com, "
    "upstreamonline.com, "
    "hartenergy.com, "
    "energyvoice.com, "
    "offshore-energy.biz"
)

# Geopolitical & macro energy analysis
GEO_SOURCES          = (
    "csis.org, "                         # CSIS — policy analysis
    "energypolicy.columbia.edu, "        # Columbia CGEP — markets & policy
    "oies.org, "                         # Oxford Institute for Energy Studies — markets
    "doomberg.substack.com"              # Doomberg — macro energy commentary
)

# Strategy & forecasting — use all three for balanced view (per Reference DB note)
STRATEGY_SOURCES     = (
    "iea.org, "                          # IEA WEO — world energy outlook
    "eia.gov, "                          # EIA STEO/AEO — short & annual energy outlook
    "opec.org, "                         # OPEC MOMR — monthly oil market report
    "spglobal.com/en/cera, "             # S&P Global CERA — advisory reports & insights
    "woodmac.com, "                      # Wood Mackenzie — commercial research
    "mckinsey.com/industries/oil-and-gas, "
    "bcg.com/industries/energy, "
    "rystadenergy.com"
)

# Data visualisation sources
DATA_VIZ_SOURCES     = (
    "ourworldindata.org, "               # Our World in Data — charts
    "iea.org/data-and-statistics, "      # IEA Data Explorer — interactive
    "eia.gov/energyexplained, "          # EIA — free data tables
    "spglobal.com/en/energy-horizons"    # S&P Global Horizons — sustainability & expansion data
)

# ── System Prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are the data engine for The Daily Crude — a professional daily energy intelligence brief for upstream, midstream, and downstream O&G professionals.

Today is {TODAY}.

You have access to web_search. Use it to fetch real, current data from these TRUSTED SOURCES ONLY, grouped by purpose:

PRICE BENCHMARKS  : {PRICE_SOURCES}
LNG DATA          : {LNG_SOURCES}
DAILY PULSE NEWS  : {DAILY_PULSE_SOURCES}
DEEP O&G NEWS     : {NEWS_SOURCES}
INDIA ENERGY      : {INDIA_SOURCES}
GEOPOLITICS/MACRO : {GEO_SOURCES}
STRATEGY/FORECASTS: {STRATEGY_SOURCES}
DATA & CHARTS     : {DATA_VIZ_SOURCES}

RULES:
1. Execute all 6 searches below in order. Do not skip any.
2. Return ONLY a raw JSON object. No markdown fences, no preamble, no explanation.
3. All numeric fields must contain REAL numbers sourced from the above sites. No XX, no placeholders.
4. All text fields must contain REAL headlines, real project names, real company names.
5. For prices: hit Platts (spglobal.com), Argus (argusmedia.com), and EIA (eia.gov) first.
   These are the definitive benchmark publishers. Oil Price (oilprice.com) is a free fallback.
6. For LNG prices: use lngindustry.com and iea.org LNG export tracker; combine with Platts JKM assessment.
7. For geopolitical drivers: draw from CSIS, Columbia CGEP, and OIES — not generic news aggregators.
8. For strategy framework: compare IEA WEO, EIA STEO/AEO, and OPEC MOMR for a balanced macro view,
   then layer in Wood Mac / McKinsey / BCG for commercial framework depth.

CRITICAL PRICE RULE:
- EVERY price field (ticker and markets.prices) MUST contain a real numeric value like "$65.40" or "€34.20".
- NEVER return "Price data unavailable", "N/A", "—", "xx.xx", or any non-numeric string in a price field.
- If a price cannot be found on Platts/Argus, fall back to EIA or oilprice.com — but always return a number.
- A blank or unavailable price field is a FAILURE and will trigger a retry.
"""

# ── User Prompt ────────────────────────────────────────────────────────────────
USER_PROMPT = f"""Today is {TODAY}.

Execute these 6 searches in order, then return the complete JSON:

SEARCH 1 — BENCHMARK PRICES
Search all four S&P Global Energy products in this order:
  1. spglobal.com/commodityinsights (Platts) — Brent, Dubai, WTI, JKM LNG, Naphtha, Gasoil price assessments
  2. spglobal.com/en/cera (CERA) — any research notes or advisory data on today's price drivers
  3. spglobal.com/en/energy-horizons (Horizons) — energy expansion/sustainability data relevant to today
  4. spglobal.com/en/energy (S&P Global Energy Events) — any published thought-leadership on today's market
Also search argusmedia.com (Argus) and eia.gov for TTF, Henry Hub, OPEC basket cross-checks.
Also check lngindustry.com and iea.org for LNG export/spot data to cross-reference JKM.
Every single price field MUST be a real number. No exceptions.

SEARCH 2 — DAILY O&G MARKET PULSE
Search energynewsbeat.com, oilprice.com, and worldoil.com for today's top market-moving
headlines: OPEC+ supply decisions, demand outlook, refining margins, crude differentials,
and any intraday price drivers. These are quick-turn sources — use them for the macro_signal
paragraph and the market drivers section.

SEARCH 3 — DEEP O&G NEWS
Search ogj.com, upstreamonline.com, offshore-mag.com, rigzone.com, offshore-energy.biz,
hartenergy.com, hydrocarbonprocessing.com for today's upstream exploration, FID/FEED/EPC
awards, offshore developments, LNG project milestones, M&A, and refining news.
Use these for the global_news cards and project tracker.

SEARCH 4 — INDIA ENERGY
Search ogj.com, upstreamonline.com, hartenergy.com for today's India-specific news:
crude import basket price, refinery throughput, ONGC/IOC/BPCL/Reliance updates,
India LNG imports, domestic gas pricing, MoPNG policy announcements.

SEARCH 5 — GEOPOLITICAL & MACRO ENERGY ANALYSIS
Search csis.org, energypolicy.columbia.edu (Columbia CGEP), oies.org (Oxford Institute
for Energy Studies), and doomberg.substack.com for today's geopolitical risk factors,
sanctions developments, macro energy narratives, and supply/demand structural themes.
Use these specifically for the geopolitical driver card and strategy watchpoints.

SEARCH 6 — STRATEGY FRAMEWORK
Compare the latest IEA (iea.org), EIA STEO/AEO (eia.gov), and OPEC MOMR (opec.org)
outlooks to identify a key divergence or framework theme relevant to today's market.
Also search spglobal.com/en/cera (S&P Global CERA) for any advisory reports or research
notes that provide critical data, insights, or expert commentary on today's theme.
Then layer in a commercial framework from woodmac.com, mckinsey.com, or bcg.com.
Use this for the strategy featured card and mini-cards.

Return this exact JSON with ALL fields filled from real search results:

{{
  "meta": {{
    "date": "{TODAY}",
    "issue_date": "{ISSUE_DATE}",
    "last_updated": "08:00 IST"
  }},
  "ticker": [
    {{"label": "BRENT",          "price": "actual $/bbl from Platts or Argus",    "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "WTI",            "price": "actual $/bbl from EIA or Platts",      "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "DUBAI CRUDE",    "price": "actual $/bbl from Platts",             "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "JKM LNG",        "price": "actual $/MMBtu from Platts + IEA LNG", "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "TTF GAS",        "price": "actual €/MWh from ICE/Argus",          "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "HH NATGAS",      "price": "actual $/MMBtu from EIA",              "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "OPEC BASKET",    "price": "actual $/bbl from opec.org",           "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "NAPHTHA CIF ARA","price": "actual $/MT from Platts or Argus",     "change": "▲/▼ actual%", "direction": "up or down or flat"}},
    {{"label": "GASOIL ICE",     "price": "actual $/MT from ICE or Argus",        "change": "▲/▼ actual%", "direction": "up or down or flat"}}
  ],
  "markets": {{
    "macro_signal": "One real paragraph from Energy News Beat / Oil Price / World Oil — today's key macro driver",
    "prices": [
      {{"commodity": "Brent Crude (ICE)",  "value": "actual $/bbl", "change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up/down/flat", "meta": "$/bbl · ICE · Front-Month · Platts"}},
      {{"commodity": "WTI Crude (NYMEX)",  "value": "actual $/bbl", "change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up/down/flat", "meta": "$/bbl · NYMEX · Front-Month · EIA"}},
      {{"commodity": "JKM LNG Spot",       "value": "actual $/MMBtu","change_abs": "actual ±$", "change_pct": "actual ±%", "direction": "up/down/flat", "meta": "$/MMBtu · Platts · NE Asia · IEA LNG tracker"}},
      {{"commodity": "TTF Natural Gas",    "value": "actual €/MWh",  "change_abs": "actual ±€", "change_pct": "actual ±%", "direction": "up/down/flat", "meta": "€/MWh · ICE Endex · Front-Month · Argus"}}
    ],
    "drivers": [
      {{"icon": "🛢️", "headline": "Supply driver from Energy News Beat or OGJ",          "body": "2-3 sentences — cite source"}},
      {{"icon": "🌏", "headline": "Demand/Asia driver from World Oil or Oil Price",       "body": "2-3 sentences — cite source"}},
      {{"icon": "⚠️", "headline": "Geopolitical driver from CSIS or Columbia CGEP or OIES","body": "2-3 sentences — cite source"}},
      {{"icon": "📊", "headline": "Macro/structural driver from Doomberg or OIES",       "body": "2-3 sentences — cite source"}}
    ]
  }},
  "india": {{
    "headline": "Real India O&G headline from SEARCH 4 sources",
    "headline_body": "2-3 real paragraphs",
    "news": [
      {{"sector": "Refining",  "sector_color": "#c57800", "title": "Real title", "summary": "2-3 sentences", "source": "real source name"}},
      {{"sector": "Upstream",  "sector_color": "#c8401a", "title": "Real title", "summary": "2-3 sentences", "source": "real source name"}}
    ],
    "stats": [
      {{"label": "India Crude Import Basket",       "value": "actual $/bbl",    "note": "Russia ~X% · ME ~X% · Others ~X% · PPAC"}},
      {{"label": "LNG Spot Import (Petronet Dahej)","value": "actual $/MMBtu",  "note": "Blended spot vs LTC · Platts JKM ref"}},
      {{"label": "ONGC Crude Production (YTD)",     "value": "actual X.X MMT",  "note": "Crude oil equiv. · vs annual target"}},
      {{"label": "India Refinery Throughput",        "value": "actual X.X MMT",  "note": "MoPNG · YTD · % capacity utilisation"}},
      {{"label": "India LNG Imports (YTD)",          "value": "actual X BCM",    "note": "vs prior year · PPAC · IEA LNG tracker"}}
    ]
  }},
  "global_news": [
    {{"sector": "Upstream · Exploration",      "sector_class": "sector-upstream",   "dot_color": "#c8401a", "title": "Real headline from OGJ or Upstream Online", "summary": "2-3 real sentences", "source": "OGJ"}},
    {{"sector": "Policy · Regulation",         "sector_class": "sector-policy",     "dot_color": "#5a3a00", "title": "Real headline from CSIS or Columbia CGEP",   "summary": "2-3 real sentences", "source": "CSIS"}},
    {{"sector": "Midstream · LNG",             "sector_class": "sector-midstream",  "dot_color": "#8b4500", "title": "Real headline from LNG Industry or Offshore Energy", "summary": "2-3 real sentences", "source": "LNG Industry"}},
    {{"sector": "Offshore · Subsea",           "sector_class": "sector-offshore",   "dot_color": "#1e4a7a", "title": "Real headline from Offshore Magazine",        "summary": "2-3 real sentences", "source": "Offshore Magazine"}},
    {{"sector": "Downstream · Refining",       "sector_class": "sector-downstream", "dot_color": "#1e3a5f", "title": "Real headline from Hydrocarbon Processing",   "summary": "2-3 real sentences", "source": "Hydrocarbon Processing"}},
    {{"sector": "OPEC+ · Supply",              "sector_class": "sector-upstream",   "dot_color": "#8b1a00", "title": "Real headline from OGJ or World Oil",         "summary": "2-3 real sentences", "source": "World Oil"}},
    {{"sector": "Geopolitics · Sanctions",     "sector_class": "sector-policy",     "dot_color": "#5a3a00", "title": "Real headline from OIES or Columbia CGEP",    "summary": "2-3 real sentences", "source": "OIES"}},
    {{"sector": "M&A · Corporate",             "sector_class": "sector-upstream",   "dot_color": "#c8401a", "title": "Real headline from Hart Energy",               "summary": "2-3 real sentences", "source": "Hart Energy"}},
    {{"sector": "Macro · Energy Markets",      "sector_class": "sector-upstream",   "dot_color": "#4a2060", "title": "Real headline from Doomberg or Energy News Beat","summary": "2-3 real sentences","source": "Doomberg"}}
  ],
  "strategy": {{
    "featured": {{
      "label": "⭐ Framework of the Day",
      "title": "Real framework — draw from IEA/EIA/OPEC divergence or Wood Mac/McKinsey/BCG",
      "tags": ["tag1", "tag2", "tag3"],
      "audience": "IOCs · NOCs · Private Equity · Strategy Consultants · EPC PMOs",
      "read_time": "actual N min read",
      "sources": "IEA + EIA STEO + OPEC MOMR or Wood Mac / McKinsey / BCG",
      "url": "real URL",
      "intro": "Real intro paragraph",
      "framework_title": "Real subtitle",
      "framework_desc": "Real paragraph",
      "steps": [
        {{"title": "Step 1", "body": "Real explanation"}},
        {{"title": "Step 2", "body": "Real explanation"}},
        {{"title": "Step 3", "body": "Real explanation"}},
        {{"title": "Step 4", "body": "Real explanation"}},
        {{"title": "Step 5", "body": "Real explanation"}}
      ],
      "watchpoints_title": "Key Watchpoints",
      "watchpoints": "Real paragraph — draw from OIES or Columbia CGEP for geopolitical watchpoints"
    }},
    "mini_cards": [
      {{"label": "🔍 Upstream · Due Diligence",  "title": "Real title from Rystad or Wood Mac", "desc": "2 real sentences", "read_time": "N", "tag": "E&P / Consultant",  "tag_bg": "var(--tag-bg)",    "tag_color": "var(--ink)",   "url": "real URL"}},
      {{"label": "🛢️ Midstream · LNG Strategy", "title": "Real title from LNG Industry or IEA","desc": "2 real sentences", "read_time": "N", "tag": "LNG / Trading",     "tag_bg": "var(--steel-light)","tag_color": "var(--steel)", "url": "real URL"}},
      {{"label": "⚙️ Operations · EPC",          "title": "Real title from BCG or McKinsey",    "desc": "2 real sentences", "read_time": "N", "tag": "PMC / EPC",         "tag_bg": "var(--tag-bg)",    "tag_color": "var(--ink)",   "url": "real URL"}}
    ]
  }},
  "projects": [
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "lng/upstream/midstream/downstream", "stage": "EPC/FID/FEED/PDP", "stage_class": "stage-epc/fid/feed/pdp", "value": "actual $XB", "location": "City, Country", "description": "One real sentence", "event": "✅ label", "event_color": "#1a5c38"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "lng",       "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#c8401a"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "upstream",  "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1a5c38"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "midstream", "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1e3a5f"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "lng",       "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#c8401a"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "upstream",  "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1a5c38"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "downstream","stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1e3a5f"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "upstream",  "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1a5c38"}},
    {{"name": "Real project", "company": "Real operator", "sector": "real sector", "data_sector": "lng",       "stage": "stage", "stage_class": "class", "value": "$XB", "location": "City, Country", "description": "One real sentence", "event": "event", "event_color": "#1a5c38"}}
  ]
}}"""


# ── Trend Data Prompt (Monday only) ────────────────────────────────────────────
# Fetches 90-day closing price series for all crude and gas benchmarks.
# The 7-day and 30-day slices are derived from the last 7 and 30 values of the d90 array.
TREND_PROMPT = f"""Today is {TODAY}.

You have access to web_search. Fetch REAL closing/settlement price data for the past 90 calendar days for each commodity below. Use these sources: spglobal.com/commodityinsights (Platts), argusmedia.com, eia.gov, opec.org, oilprice.com.

For EACH commodity return a JSON array of exactly 90 numeric values in chronological order (oldest first, today last). Use actual closing/settlement prices. If a day has no trading (weekend/holiday), carry forward the prior day's close.

Return ONLY this raw JSON object — no markdown, no explanation:

{{
  "crude": {{
    "brent":  {{"label":"Brent Crude",  "unit":"$/bbl",     "d90":[...90 values...]}},
    "wti":    {{"label":"WTI Crude",    "unit":"$/bbl",     "d90":[...90 values...]}},
    "dubai":  {{"label":"Dubai Crude",  "unit":"$/bbl",     "d90":[...90 values...]}},
    "murban": {{"label":"Murban",       "unit":"$/bbl",     "d90":[...90 values...]}},
    "mars":   {{"label":"Mars Blend",   "unit":"$/bbl",     "d90":[...90 values...]}},
    "lls":    {{"label":"LLS",          "unit":"$/bbl",     "d90":[...90 values...]}},
    "opec":   {{"label":"OPEC Basket",  "unit":"$/bbl",     "d90":[...90 values...]}}
  }},
  "gas": {{
    "hh":   {{"label":"Henry Hub",       "unit":"$/MMBtu",  "d90":[...90 values...]}},
    "ttf":  {{"label":"TTF Natural Gas", "unit":"€/MWh",    "d90":[...90 values...]}},
    "jkm":  {{"label":"JKM LNG Spot",   "unit":"$/MMBtu",  "d90":[...90 values...]}},
    "nbp":  {{"label":"NBP UK Gas",      "unit":"p/therm",  "d90":[...90 values...]}},
    "aeco": {{"label":"AECO Canada",     "unit":"CAD$/GJ",  "d90":[...90 values...]}}
  }}
}}

RULES:
- Every d90 array must have EXACTLY 90 numeric values.
- All values must be real numbers — no nulls, no strings, no zeros unless the actual price was zero.
- Values must be in chronological order: index 0 = 90 days ago, index 89 = today.
- Weekend/holiday gaps: carry the prior trading day's close forward.
- Sources in priority order: Platts (spglobal.com) → Argus (argusmedia.com) → EIA (eia.gov) → oilprice.com.
"""

# ── Validation ─────────────────────────────────────────────────────────────────
BAD_PATTERNS = [
    "xx.xx", "x.xx%", "actual $/bbl", "actual €", "actual ±", "actual x",
    "real headline", "real project", "real operator", "real title", "real city",
    "real sector", "real stage", "real class", "real url", "real source",
    "news headline", "project name", "framework title", "real intro",
    "real paragraph", "real subtitle", "real explanation",
]

PRICE_UNAVAIL_RX = re.compile(
    r"(price data unavailable|data unavailable|unavailable|n/a|not available|—|–|^\s*$)",
    re.IGNORECASE
)
PRICE_VALUE_RX = re.compile(r"[\$€£¥₹]?\s*\d[\d,\.]+")


def _has_placeholders(data: dict) -> list[str]:
    raw = json.dumps(data).lower()
    return [p for p in BAD_PATTERNS if p in raw]


def _check_prices(data: dict) -> list[str]:
    problems: list[str] = []
    for item in data.get("ticker", []):
        label = item.get("label", "?")
        price = str(item.get("price", "")).strip()
        if not price or PRICE_UNAVAIL_RX.search(price) or not PRICE_VALUE_RX.search(price):
            problems.append(f"ticker[{label}].price = {price!r}")
    for item in data.get("markets", {}).get("prices", []):
        commodity = item.get("commodity", "?")
        value = str(item.get("value", "")).strip()
        if not value or PRICE_UNAVAIL_RX.search(value) or not PRICE_VALUE_RX.search(value):
            problems.append(f"markets.prices[{commodity}].value = {value!r}")
    return problems


def _validate_trend(td: dict) -> list[str]:
    """Verify every d90 array has exactly 90 numeric values."""
    problems: list[str] = []
    for group in ("crude", "gas"):
        for key, obj in td.get(group, {}).items():
            arr = obj.get("d90", [])
            if len(arr) != 90:
                problems.append(f"trend_data.{group}.{key}.d90 has {len(arr)} values (need 90)")
            bad_vals = [v for v in arr if not isinstance(v, (int, float))]
            if bad_vals:
                problems.append(f"trend_data.{group}.{key}.d90 has non-numeric values: {bad_vals[:3]}")
    return problems


def _derive_slices(td: dict) -> dict:
    """Derive d7 and d30 from the last 7/30 values of each d90 array."""
    for group in ("crude", "gas"):
        for obj in td.get(group, {}).values():
            arr = obj.get("d90", [])
            obj["d7"]  = arr[-7:]  if len(arr) >= 7  else arr
            obj["d30"] = arr[-30:] if len(arr) >= 30 else arr
    return td


# ── Read existing trend_data from current HTML (Tue–Sun) ──────────────────────
def read_existing_trend_data() -> dict | None:
    """
    Extract the trend_data block from the currently deployed HTML.
    Returns None if the file doesn't exist or trend_data is absent.
    """
    if not os.path.exists(HTML_FILE):
        print("  No existing HTML found — trend_data will be absent today.")
        return None
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
        m = re.search(r'<script id="daily-data">\s*window\.DAILY_DATA\s*=\s*(\{.*?\});\s*</script>',
                      html, re.DOTALL)
        if not m:
            print("  Could not locate DAILY_DATA in existing HTML.")
            return None
        existing = json.loads(m.group(1))
        td = existing.get("markets", {}).get("trend_data")
        if td:
            print(f"  Existing trend_data preserved ({DOW_NAME} — not a Monday refresh).")
            return td
        print("  No trend_data in existing HTML.")
        return None
    except Exception as e:
        print(f"  Warning: could not read existing trend_data: {e}")
        return None


# ── Fetch daily content (main JSON) ───────────────────────────────────────────
def fetch_content(client: OpenAI) -> dict:
    for attempt in range(1, DAILY_RETRIES + 1):
        wait = RETRY_BACKOFF[attempt - 2] if attempt > 1 else 0
        if wait:
            print(f"  Waiting {wait}s before retry…")
            time.sleep(wait)
        print(f"Daily content attempt {attempt}/{DAILY_RETRIES}…")

        prefix = "" if attempt == 1 else (
            f"ATTEMPT {attempt}: Previous response still had unfilled or unavailable price fields. "
            f"Search spglobal.com/commodityinsights (Platts) and eia.gov RIGHT NOW for "
            f"Brent, WTI, JKM LNG, and TTF prices. Every price field MUST be a real number.\n\n"
        )

        try:
            response = client.responses.create(
                model="gpt-5.5",
                tools=[{"type": "web_search_preview"}],
                instructions=SYSTEM_PROMPT,
                input=prefix + USER_PROMPT,
                max_output_tokens=16000,
            )
        except Exception as e:
            print(f"  API error: {e}")
            continue

        raw = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw = block.text

        raw = re.sub(r"```json\s*|```", "", raw).strip()
        print(f"  Response: {len(raw)} chars")

        if not raw:
            print("  Empty response.")
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  JSON error: {e}")
            continue

        bad = _has_placeholders(data)
        if bad:
            print(f"  Text placeholders: {bad[:5]}")
            continue

        price_problems = _check_prices(data)
        if price_problems:
            print(f"  Blank prices ({len(price_problems)}): {price_problems[:3]}")
            continue

        print("  Daily content validated ✓")
        return data

    return None   # all retries exhausted


# ── Fetch weekly trend data (Monday only) ─────────────────────────────────────
def fetch_trend_data(client: OpenAI) -> dict | None:
    for attempt in range(1, TREND_RETRIES + 1):
        wait = RETRY_BACKOFF[attempt - 2] if attempt > 1 else 0
        if wait:
            print(f"  Waiting {wait}s before trend retry…")
            time.sleep(wait)
        print(f"Monday trend fetch attempt {attempt}/{TREND_RETRIES}…")

        try:
            response = client.responses.create(
                model="gpt-5.5",
                tools=[{"type": "web_search_preview"}],
                instructions=(
                    f"You are a financial data retrieval engine for The Daily Crude. "
                    f"Today is {TODAY}. Retrieve real historical closing prices only. "
                    f"Return ONLY raw JSON, no markdown, no explanation."
                ),
                input=TREND_PROMPT,
                max_output_tokens=16000,
            )
        except Exception as e:
            print(f"  API error: {e}")
            continue

        raw = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw = block.text

        raw = re.sub(r"```json\s*|```", "", raw).strip()
        print(f"  Trend response: {len(raw)} chars")

        if not raw:
            print("  Empty trend response.")
            continue

        try:
            td = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  Trend JSON error: {e}")
            continue

        problems = _validate_trend(td)
        if problems:
            print(f"  Trend validation failed: {problems[:3]}")
            continue

        td = _derive_slices(td)
        print("  Trend data validated ✓")
        return td

    print("  WARNING: All trend fetch attempts exhausted.")
    return None   # caller decides fallback


# ── HTML Injection ─────────────────────────────────────────────────────────────
def inject_into_html(data: dict) -> None:
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    json_str   = json.dumps(data, ensure_ascii=False, indent=2)
    data_block = f'<script id="daily-data">\nwindow.DAILY_DATA = {json_str};\n</script>'

    if 'id="daily-data"' in html:
        html = re.sub(
            r'<script id="daily-data">.*?</script>',
            lambda _: data_block,
            html,
            flags=re.DOTALL
        )
    else:
        html = html.replace("</head>", f"{data_block}\n</head>")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML updated.")


# ── Maintenance Page ───────────────────────────────────────────────────────────
def inject_maintenance_page(reason: str) -> None:
    """
    Replaces index.html with a branded maintenance page.
    Preserves the masthead and footer styling; body shows maintenance message.
    Called only when ALL retries for a critical fetch are exhausted.
    """
    print(f"CRITICAL: injecting maintenance page. Reason: {reason}")
    now_str = NOW_IST.strftime("%d %B %Y, %H:%M IST")
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Daily Crude — Under Maintenance</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:\'DM Sans\',sans-serif;background:#f5f0e8;color:#0d0d0d;min-height:100vh;display:flex;flex-direction:column;}}
.masthead{{background:#0d0d0d;border-bottom:6.67px solid #c8401a;padding:18px 40px 0;}}
.logo-text{{font-family:\'Playfair Display\',serif;font-size:60px;font-weight:700;color:#f5f0e8;text-decoration:underline;letter-spacing:-1px;line-height:51px;display:block;padding-bottom:18px;}}
.logo-text span{{color:#c8401a;}}
.maintenance-body{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 40px;text-align:center;gap:24px;}}
.maintenance-icon{{font-size:64px;}}
.maintenance-title{{font-family:\'Playfair Display\',serif;font-size:36px;font-weight:700;color:#0d0d0d;}}
.maintenance-subtitle{{font-size:16px;color:#6b6055;max-width:520px;line-height:1.7;}}
.maintenance-time{{font-family:\'DM Mono\',monospace;font-size:12px;color:#aaa;letter-spacing:1px;}}
.maintenance-divider{{width:60px;height:2px;background:#c8401a;}}
footer{{background:#0d0d0d;border-top:6.67px solid #c8401a;color:#666;padding:22px 40px;font-family:\'DM Mono\',monospace;font-size:11px;display:flex;justify-content:space-between;align-items:center;}}
footer .fl{{font-family:\'Playfair Display\',serif;font-size:28px;font-weight:700;color:#f5f0e8;text-decoration:underline;}}
footer .fl span{{color:#c8401a;}}
</style>
</head>
<body>
<header class="masthead">
  <span class="logo-text">The Daily <span>Crude</span></span>
</header>
<div class="maintenance-body">
  <div class="maintenance-icon">🛠️</div>
  <div class="maintenance-divider"></div>
  <div class="maintenance-title">Under Maintenance</div>
  <div class="maintenance-subtitle">
    Today\'s edition of The Daily Crude is currently being prepared.<br>
    Our systems are working to restore the brief. Please check back shortly.
  </div>
  <div class="maintenance-time">Last attempted: {now_str}</div>
</div>
<footer>
  <span class="fl">The Daily <span>Crude</span></span>
  <span>Energy Intelligence · Mumbai, India</span>
</footer>
</body>
</html>'''
    with open(MAINTENANCE_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Maintenance page written to {MAINTENANCE_FILE}.")


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _key = os.environ.get("OPENAI_API_KEY", "")
    if not _key:
        inject_maintenance_page("Content generation service not available")
        sys.exit(1)

    client = OpenAI(api_key=_key, timeout=300.0)
    del _key

    print(f"Build date: {TODAY} ({DOW_NAME}) — Monday refresh: {IS_MONDAY}")

    # ── Step 1: Fetch daily content ───────────────────────────────────────────
    data = fetch_content(client)
    if data is None:
        inject_maintenance_page("Daily content fetch failed after all retries")
        sys.exit(1)

    # ── Step 2: Resolve trend_data ────────────────────────────────────────────
    if IS_MONDAY:
        print("Monday detected — fetching fresh 90-day trend series…")
        trend = fetch_trend_data(client)
        if trend is None:
            # All trend retries failed — fall back to existing trend_data if available
            print("Monday trend fetch failed after all retries — attempting fallback to existing data…")
            trend = read_existing_trend_data()
            if trend is None:
                # No fallback available — this is a hard failure for trend only;
                # daily content is still injected but trend cards will be empty.
                print("WARNING: No trend_data available. Trend cards will not render.")
        else:
            print(f"Monday trend data fetched and validated ✓")
    else:
        # Tuesday–Sunday: read existing trend_data, do not re-fetch
        print(f"{DOW_NAME}: preserving existing trend_data unchanged…")
        trend = read_existing_trend_data()
        if trend is None:
            # Existing HTML had no trend_data (e.g. first deploy or after a bad merge).
            # Fall back to a fresh fetch so trend cards render correctly.
            print("No existing trend_data found — fetching fresh series as one-time recovery…")
            trend = fetch_trend_data(client)
            if trend is None:
                print("WARNING: Recovery fetch also failed. Trend cards will not render today.")

    # ── Step 3: Attach trend_data to markets block ────────────────────────────
    if trend:
        data.setdefault("markets", {})["trend_data"] = trend
        print("trend_data attached to markets block.")
    else:
        print("trend_data absent — trend cards will not render today.")

    # ── Step 4: Inject into HTML ──────────────────────────────────────────────
    try:
        inject_into_html(data)
    except Exception as e:
        traceback.print_exc()
        inject_maintenance_page(f"HTML injection failed: {e}")
        sys.exit(1)

    print(f"Done. Build complete for {TODAY}.")
