"""
generate_digest.py
------------------
Runs daily at 7am IST via GitHub Actions.
Calls OpenAI GPT-4o to generate all digest sections.
Writes output to data/content.json.

SECURITY: The OPENAI_API_KEY is read exclusively from the environment variable
injected by GitHub Secrets at runtime. It is never written to disk, never
printed, never logged, and never appears in any committed file.
"""

import os
import json
import datetime
import sys
import time
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError

# Key read from environment only — never logged, never written to disk
_key = os.environ.get("OPENAI_API_KEY", "")
if not _key:
    print("ERROR: OPENAI_API_KEY secret not found in environment.", file=sys.stderr)
    sys.exit(1)

client = OpenAI(api_key=_key, timeout=60.0)
del _key  # immediately remove from process memory

# Date context (IST = UTC+5:30)
today = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
date_str = today.strftime("%A, %d %B %Y")
date_iso = today.strftime("%Y-%m-%d")

SOURCES = {
    "market-pulse":  "OGJ, OilPrice.com, EIA, Platts/S&P Global, Argus Media, World Oil",
    "geopolitical":  "CSIS, Columbia CGEP, OIES, Doomberg, OilPrice.com",
    "india":         "India Energy Week, TERI, OilPrice.com, Argus Media, MoPNG",
    "upstream":      "SPE/JPT, Wood Mackenzie, Rystad Energy, Hart Energy, OGJ, Baker Hughes",
    "midstream":     "LNG Industry, Gas Processing & LNG, Pipeline & Gas Journal, Offshore Energy",
    "downstream":    "Hydrocarbon Processing, OGJ Downstream, Platts, Argus",
    "petrochems":    "ICIS, Hydrocarbon Processing, GlobalData, Offshore Technology",
    "og-projects":   "Hart Energy A&D, Upstream Online, Rystad Energy, Wood Mackenzie",
    "re-projects":   "Renewables Now, reNews, Renewable Energy World",
    "supply-demand": "IEA Oil Market Report, EIA Short-Term Energy Outlook, OPEC Monthly Oil Market Report",
    "frameworks":    "McKinsey Energy, BCG, Deloitte, HBR, academic energy strategy",
    "narratives":    "Canary Media, Carbon Brief, BloombergNEF, Gerard Reid, Adam Tooze",
    "hydrogen":      "H2 Bulletin, Hydrogen Insight, H2Tech, Hydrogen Council",
    "nuclear":       "World Nuclear News, NEI Magazine, Energy Storage News",
    "ccus":          "Carbon Capture Journal, Global CCS Institute, Carbon Brief",
    "clean-capital": "BloombergNEF, IRENA, RMI, IEEFA, Carbon Tracker",
}

SECTION_PROMPTS = {
    "market-pulse": "Write 5 energy market intelligence cards for {date}. Cover: Brent crude price and movement, WTI price, Henry Hub gas price, a key OPEC+ or supply development, and one major refinery or shipping disruption. Cite sources from: {sources}.",
    "geopolitical": "Write 4 geopolitical energy analysis cards for {date}. Cover: sanctions impacts on energy flows, pipeline diplomacy, OPEC+ political dynamics, and one conflict zone affecting energy infrastructure. Cite sources from: {sources}.",
    "india": "Write 4 India energy intelligence cards for {date}. Cover: India crude import trends, a refinery or PSU development (ONGC/BPCL/Reliance), Indian LNG or gas news, and one energy policy update. Cite sources from: {sources}.",
    "upstream": "Write 3 upstream oil & gas intelligence cards for {date}. Cover: one exploration discovery or FID, current Baker Hughes rig count context, and one deepwater or unconventional development. Cite sources from: {sources}.",
    "midstream": "Write 3 midstream intelligence cards for {date}. Cover: one LNG terminal or capacity development, a pipeline project update, and tanker market or freight rate news. Cite sources from: {sources}.",
    "downstream": "Write 3 downstream intelligence cards for {date}. Cover: refining margin trends, diesel or gasoline crack spread movements, and one product inventory or fuel demand data point. Cite sources from: {sources}.",
    "petrochems": "Write 3 petrochemicals intelligence cards for {date}. Cover: ethylene or propylene margin movements, naphtha feedstock price dynamics, and one new cracker or petrochemical project. Cite sources from: {sources}.",
    "og-projects": "Write 3 oil & gas project tracker cards for {date}. Cover: one recent FID or sanction, one first oil milestone, and one offshore contract award. Cite sources from: {sources}.",
    "re-projects": "Write 3 renewable energy project tracker cards for {date}. Cover: one large solar or wind commissioning, one storage project award, and one offshore wind development. Cite sources from: {sources}.",
    "supply-demand": "Write 3 supply & demand forecast cards for {date}. Cover: IEA Oil Market Report key figures, EIA Short-Term Energy Outlook highlights, and OPEC Monthly Oil Market Report demand projections. Cite sources from: {sources}.",
    "frameworks": "Write 1 strategic framework card for {date}. Choose one consulting framework (Porter's Five Forces, Value Chain, BCG Matrix, Scenario Planning, etc.) and apply it analytically to today's energy market with specific references. Cite source from: {sources}.",
    "narratives": "Write 3 energy transition narrative cards for {date}. Cover: the dominant transition story this week, one policy or net-zero commitment development, and one key analysis or opinion piece. Cite sources from: {sources}.",
    "hydrogen": "Write 3 hydrogen economy intelligence cards for {date}. Cover: one green or blue hydrogen project FID or milestone, electrolyser cost or policy development, and one offtake or demand-side development. Cite sources from: {sources}.",
    "nuclear": "Write 3 nuclear & storage intelligence cards for {date}. Cover: one SMR project milestone or contract, one grid-scale battery storage deployment, and one nuclear policy or financing development. Cite sources from: {sources}.",
    "ccus": "Write 3 CCUS & carbon market cards for {date}. Cover: one carbon capture project update, carbon credit or ETS price movements, and one DAC or industrial CCS development. Cite sources from: {sources}.",
    "clean-capital": "Write 3 clean energy investment cards for {date}. Cover: one major clean energy deal or fund raise, a green bond issuance, and BNEF or IRENA investment flow data. Cite sources from: {sources}.",
}

SYSTEM_PROMPT = """You are a senior energy intelligence analyst writing a professional daily digest.
Today is {date}.

Return ONLY a valid JSON object with a single key "cards" containing an array.
No markdown, no backticks, no preamble. Pure JSON only.

Each card object must have exactly:
{{
  "title": "Specific analytical headline (max 12 words)",
  "source": "Publication name",
  "source_url": "https://real-url-for-this-publication.com",
  "body": "2-3 sentences. Be specific: cite numbers, dates, company names. May use <strong>, <em>, <u> tags."
}}
"""

def generate_section(section_id, prompt, date, sources, max_retries=3):
    filled = prompt.format(date=date, sources=sources)
    system = SYSTEM_PROMPT.format(date=date)

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": filled}
                ],
                temperature=0.4,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()
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
                if not isinstance(c, dict):
                    continue
                clean.append({
                    "title":      str(c.get("title", "Untitled")).strip(),
                    "source":     str(c.get("source", "")).strip(),
                    "source_url": str(c.get("source_url", "#")).strip(),
                    "body":       str(c.get("body", "")).strip(),
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
        except json.JSONDecodeError:
            print(f"\n    JSON error on attempt {attempt+1}", flush=True)
            if attempt == max_retries - 1:
                return []
            time.sleep(5)
        except Exception as e:
            print(f"\n    Error attempt {attempt+1}: {type(e).__name__}", flush=True)
            if attempt == max_retries - 1:
                return []
            time.sleep(10)

    return []

# Main generation loop
print(f"Generating Energy Intelligence Brief — {date_str}")
print(f"{len(SECTION_PROMPTS)} sections to generate\n")

output = {
    "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
    "date":         date_iso,
    "date_display": date_str,
    "sections":     {}
}

DELAY = 3  # seconds between calls to avoid rate limits

for i, (sid, prompt) in enumerate(SECTION_PROMPTS.items(), 1):
    print(f"  [{i:02d}/{len(SECTION_PROMPTS)}] {sid}...", end=" ", flush=True)
    cards = generate_section(sid, prompt, date_str, SOURCES[sid])
    output["sections"][sid] = {"cards": cards}
    print(f"{len(cards)} cards")

    # If empty, retry once after a longer pause
    if not cards:
        print(f"         Retrying {sid} after 20s...")
        time.sleep(20)
        cards = generate_section(sid, prompt, date_str, SOURCES[sid])
        output["sections"][sid] = {"cards": cards}
        print(f"         Retry: {len(cards)} cards")

    if i < len(SECTION_PROMPTS):
        time.sleep(DELAY)

# Write output
out_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "content.json")
)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

total = sum(len(s["cards"]) for s in output["sections"].values())
empty = [k for k, v in output["sections"].items() if not v["cards"]]
print(f"\n{'='*50}")
print(f"Complete: {total} cards across {len(output['sections'])} sections.")
if empty:
    print(f"Still empty: {', '.join(empty)}")
else:
    print("All sections populated.")
print(f"Saved to: {out_path}")
