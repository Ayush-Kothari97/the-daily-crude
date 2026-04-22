"""
generate_digest.py — The Energy Intelligence Brief
----------------------------------------------------
Runs daily at 7am IST via GitHub Actions.
Uses OpenAI GPT-4o (no web search tool — uses model knowledge).
Writes structured cards to data/content.json.

SECURITY: OPENAI_API_KEY read from environment only.
Never written to disk, never logged, never in any file.
"""

import os, json, datetime, sys, time, re
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError

# ── Key from environment only ──────────────────────────────────────────────
_key = os.environ.get("OPENAI_API_KEY", "")
if not _key:
    print("ERROR: OPENAI_API_KEY not found.", file=sys.stderr)
    sys.exit(1)
client = OpenAI(api_key=_key, timeout=90.0)
del _key

# ── Date (IST = UTC+5:30) ──────────────────────────────────────────────────
today     = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
date_str  = today.strftime("%A, %d %B %Y")
date_iso  = today.strftime("%Y-%m-%d")

# ── Section configs ────────────────────────────────────────────────────────
SECTIONS = {
    "market-pulse": {
        "card_count": 5, "long_read": False,
        "sources": "OGJ, OilPrice.com, EIA, Platts/S&P Global, Argus Media, World Oil",
        "prompt": """Write {n} energy market intelligence cards for {date}.
Cover: Brent crude price and movement, WTI price, Henry Hub gas price,
a key OPEC+ or supply development, and one major refinery or shipping disruption.
Use your most recent knowledge of energy markets. Cite sources from: {sources}."""
    },
    "geopolitical": {
        "card_count": 4, "long_read": False,
        "sources": "CSIS, Columbia CGEP, OIES, Doomberg, OilPrice.com",
        "prompt": """Write {n} geopolitical energy analysis cards for {date}.
Cover: sanctions impacts on energy flows, pipeline diplomacy,
OPEC+ political dynamics, and one conflict affecting energy infrastructure.
Cite sources from: {sources}."""
    },
    "india": {
        "card_count": 4, "long_read": False,
        "sources": "India Energy Week, TERI, OilPrice.com, Argus Media, MoPNG",
        "prompt": """Write {n} India energy intelligence cards for {date}.
Cover: India crude import trends, a PSU development (ONGC/BPCL/Reliance),
Indian LNG or gas market news, and one energy policy update.
Cite sources from: {sources}."""
    },
    "upstream": {
        "card_count": 1, "long_read": True,
        "sources": "SPE/JPT, Wood Mackenzie, Rystad Energy, Hart Energy, OGJ",
        "prompt": """Write a detailed 8-10 minute read analytical article on the
most significant upstream oil & gas development relevant to {date}.
Cover: exploration, production, field development, FIDs, or drilling technology.
Structure: intro paragraph, 4-5 analytical sections with subheadings, key takeaways.
Write at least 600 words. Cite a source from: {sources}."""
    },
    "midstream": {
        "card_count": 1, "long_read": True,
        "sources": "LNG Industry, Gas Processing & LNG, Pipeline & Gas Journal, Offshore Energy",
        "prompt": """Write a detailed 8-10 minute read analytical article on the
most significant midstream energy story relevant to {date}.
Cover LNG markets, pipeline infrastructure, or tanker freight in depth.
Structure: intro, 4-5 analytical sections, key takeaways. At least 600 words.
Cite a source from: {sources}."""
    },
    "downstream": {
        "card_count": 1, "long_read": True,
        "sources": "Hydrocarbon Processing, OGJ Downstream, Platts, Argus",
        "prompt": """Write a detailed 8-10 minute read analytical article on the
most significant downstream/refining development relevant to {date}.
Cover refining margins, crack spreads, product markets, or refinery operations.
Structure: intro, 4-5 analytical sections, key takeaways. At least 600 words.
Cite a source from: {sources}."""
    },
    "petrochems": {
        "card_count": 1, "long_read": True,
        "sources": "ICIS, Hydrocarbon Processing, GlobalData, Offshore Technology",
        "prompt": """Write a detailed 8-10 minute read analytical article on the
most significant petrochemicals development relevant to {date}.
Cover ethylene, propylene, naphtha, polymers, or new cracker projects.
Structure: intro, 4-5 analytical sections, key takeaways. At least 600 words.
Cite a source from: {sources}."""
    },
    "og-projects": {
        "card_count": 3, "long_read": False,
        "sources": "Hart Energy A&D, Upstream Online, Rystad Energy, Wood Mackenzie",
        "prompt": """Write {n} oil & gas project tracker cards for {date}.
Cover recent FIDs, first oil milestones, offshore contract awards, LNG sanctions.
Cite sources from: {sources}."""
    },
    "re-projects": {
        "card_count": 3, "long_read": False,
        "sources": "Renewables Now, reNews, Renewable Energy World",
        "prompt": """Write {n} renewable energy project tracker cards for {date}.
Cover large solar/wind commissionings, storage project awards, offshore wind milestones.
Cite sources from: {sources}."""
    },
    "supply-demand": {
        "card_count": 3, "long_read": False,
        "sources": "IEA Oil Market Report, EIA Short-Term Energy Outlook, OPEC Monthly Oil Market Report",
        "prompt": """Write {n} supply & demand forecast cards for {date}.
One card per agency: IEA, EIA, and OPEC — with their most recent demand/supply figures.
Cite specific report URLs from: {sources}."""
    },
    "frameworks": {
        "card_count": 1, "long_read": True,
        "sources": "McKinsey Energy, BCG, Deloitte, HBR, Porter, academic strategy literature",
        "prompt": """Choose the single most relevant strategic consulting framework for
today's energy market context ({date}).
Write a detailed 8-10 minute read applying it analytically to the energy sector.
Reference specific companies, market conditions, and current dynamics.
Structure: framework overview, application to energy sector today (4-5 sections),
conclusion with strategic implications. At least 600 words.
Cite a source from: {sources}.
End with: [AI-generated analysis — for educational purposes only]"""
    },
    "narratives": {
        "card_count": 3, "long_read": False,
        "sources": "Canary Media, Carbon Brief, BloombergNEF, Gerard Reid, Adam Tooze",
        "prompt": """Write {n} energy transition narrative cards for {date}.
Cover: the dominant transition story, a policy/net-zero development, one analysis piece.
Cite sources from: {sources}."""
    },
    "hydrogen": {
        "card_count": 3, "long_read": False,
        "sources": "H2 Bulletin, Hydrogen Insight, H2Tech, Hydrogen Council",
        "prompt": """Write {n} hydrogen economy intelligence cards for {date}.
Cover: project FIDs or milestones, electrolyser/cost developments, offtake agreements.
Cite sources from: {sources}."""
    },
    "nuclear": {
        "card_count": 3, "long_read": False,
        "sources": "World Nuclear News, NEI Magazine, Energy Storage News",
        "prompt": """Write {n} nuclear & storage intelligence cards for {date}.
Cover: SMR project milestones, grid-scale battery contracts, nuclear policy or financing.
Cite sources from: {sources}."""
    },
    "ccus": {
        "card_count": 3, "long_read": False,
        "sources": "Carbon Capture Journal, Global CCS Institute, Carbon Brief",
        "prompt": """Write {n} CCUS & carbon market cards for {date}.
Cover: carbon capture project updates, carbon credit/ETS prices, DAC developments.
Cite sources from: {sources}."""
    },
    "clean-capital": {
        "card_count": 3, "long_read": False,
        "sources": "BloombergNEF, IRENA, RMI, IEEFA, Carbon Tracker",
        "prompt": """Write {n} clean energy investment cards for {date}.
Cover: major deals or fundraises, green bond issuances, BNEF or IRENA investment data.
Cite sources from: {sources}."""
    },
}

# ── System prompts ─────────────────────────────────────────────────────────
SYSTEM_SHORT = """You are a senior energy intelligence analyst writing a professional daily digest.
Today is {date}.

Return ONLY a valid JSON object. No markdown, no backticks, no preamble.

Format: {{"cards": [...]}}
Each card must have exactly:
{{
  "title": "Specific analytical headline, max 12 words",
  "source": "Publication or organisation name",
  "source_url": "https://homepage-url-of-this-publication.com",
  "body": "2-3 analytical sentences with specific numbers, dates, companies. May use <strong><em><u> tags.",
  "long_read": false
}}

Rules:
- Be specific: cite real companies, real numbers, real geographies
- source_url: use the publication homepage (e.g. https://oilprice.com)
- Return ONLY the JSON, nothing else
"""

SYSTEM_LONG = """You are a senior energy intelligence analyst writing a professional daily digest.
Today is {date}.

Return ONLY a valid JSON object. No markdown, no backticks, no preamble.

Format: {{"cards": [{{
  "title": "Headline, max 15 words",
  "source": "Publication or organisation name",
  "source_url": "https://homepage-url-of-this-publication.com",
  "body": "Full article text. Use <p> tags for paragraphs. Use <strong> for key terms and company names. Use <em> for analytical emphasis. Structure with clear sections. Minimum 600 words.",
  "long_read": true
}}]}}

Rules:
- Write a genuine, analytical, well-structured 8-10 minute read
- Include specific numbers, companies, market data, and expert context
- Return ONLY the JSON, nothing else
"""

# ── Generate one section ───────────────────────────────────────────────────
def generate_section(sid, config, max_retries=3):
    long_read = config["long_read"]
    n         = config["card_count"]
    prompt    = config["prompt"].format(
        date=date_str, n=n, sources=config["sources"]
    )
    system = (SYSTEM_LONG if long_read else SYSTEM_SHORT).format(date=date_str)

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.35,
                max_tokens=4000 if long_read else 2000,
            )
            raw = (resp.choices[0].message.content or "").strip()

            # Strip accidental markdown fences
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                cards = parsed
            elif isinstance(parsed, dict):
                cards = parsed.get("cards") or next(
                    (v for v in parsed.values() if isinstance(v, list)), []
                )
            else:
                cards = []

            clean = []
            for c in cards[:15]:
                if not isinstance(c, dict): continue
                clean.append({
                    "title":      str(c.get("title",  "Untitled")).strip(),
                    "source":     str(c.get("source",  "")).strip(),
                    "source_url": str(c.get("source_url", "#")).strip(),
                    "body":       str(c.get("body",    "")).strip(),
                    "long_read":  bool(c.get("long_read", long_read)),
                })
            return clean

        except RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"\n    Rate limited — waiting {wait}s...", flush=True)
            time.sleep(wait)
        except (APITimeoutError, APIConnectionError):
            wait = 15 * (attempt + 1)
            print(f"\n    Timeout — waiting {wait}s...", flush=True)
            time.sleep(wait)
        except json.JSONDecodeError as e:
            print(f"\n    JSON error attempt {attempt+1}: {e}", flush=True)
            if attempt == max_retries - 1: return []
            time.sleep(5)
        except Exception as e:
            print(f"\n    Error attempt {attempt+1}: {type(e).__name__}: {e}", flush=True)
            if attempt == max_retries - 1: return []
            time.sleep(10)
    return []

# ── Main ───────────────────────────────────────────────────────────────────
print(f"The Energy Intelligence Brief — {date_str}")
print(f"Generating {len(SECTIONS)} sections...\n")

output = {
    "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
    "date":         date_iso,
    "date_display": date_str,
    "sections":     {}
}

DELAY = 3  # seconds between calls

for i, (sid, config) in enumerate(SECTIONS.items(), 1):
    label = "long-read" if config["long_read"] else f"{config['card_count']} cards"
    print(f"  [{i:02d}/{len(SECTIONS)}] {sid} ({label})...", end=" ", flush=True)

    cards = generate_section(sid, config)
    output["sections"][sid] = {"cards": cards}
    print(f"✓ {len(cards)}" if cards else "✗ empty")

    if not cards:
        print(f"         Retrying {sid} in 20s...")
        time.sleep(20)
        cards = generate_section(sid, config)
        output["sections"][sid] = {"cards": cards}
        print(f"         Retry: {len(cards)} cards")

    if i < len(SECTIONS):
        time.sleep(DELAY)

# ── Write ──────────────────────────────────────────────────────────────────
out_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "content.json")
)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

total = sum(len(s["cards"]) for s in output["sections"].values())
empty = [k for k, v in output["sections"].items() if not v["cards"]]
print(f"\n{'='*50}")
print(f"Complete: {total} cards across {len(SECTIONS)} sections.")
if empty: print(f"Empty: {', '.join(empty)}")
else:     print("All sections populated.")
print(f"Saved: {out_path}")
