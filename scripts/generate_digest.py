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
from openai import OpenAI

# ── Key read from environment only ─────────────────────────────────────────
# This is the only place the key is referenced. It comes from GitHub Secrets.
# If the key is missing the job fails immediately with no sensitive output.
_key = os.environ.get("OPENAI_API_KEY", "")
if not _key:
    print("ERROR: OPENAI_API_KEY secret not found in environment.", file=sys.stderr)
    sys.exit(1)

client = OpenAI(api_key=_key)
# Immediately delete the reference — key no longer accessible in this process
del _key

# ── Date context ────────────────────────────────────────────────────────────
today = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
date_str = today.strftime("%A, %d %B %Y")
date_iso = today.strftime("%Y-%m-%d")

# ── Source mapping (from your Excel Quick Reference Index) ──────────────────
SOURCES = {
    "market-pulse":   "OGJ, OilPrice.com, EIA, Platts/S&P Global, Argus Media, World Oil",
    "geopolitical":   "CSIS, Columbia CGEP, OIES, Doomberg, OilPrice.com",
    "india":          "India Energy Week, TERI, OilPrice.com, Argus Media, MoPNG press releases",
    "upstream":       "SPE/JPT, Wood Mackenzie, Rystad Energy, Hart Energy, OGJ, Baker Hughes",
    "midstream":      "LNG Industry, Gas Processing & LNG, Pipeline & Gas Journal, Offshore Energy",
    "downstream":     "Hydrocarbon Processing, OGJ Downstream, Platts, Argus",
    "petrochems":     "ICIS, Hydrocarbon Processing, GlobalData, Offshore Technology",
    "og-projects":    "Hart Energy A&D, Upstream Online, Rystad Energy, Wood Mackenzie",
    "re-projects":    "Renewables Now, reNews, Renewable Energy World",
    "supply-demand":  "IEA Oil Market Report, EIA Short-Term Energy Outlook, OPEC Monthly Oil Market Report",
    "frameworks":     "McKinsey Energy, BCG, Deloitte, HBR, academic energy strategy literature",
    "narratives":     "Canary Media, Carbon Brief, BloombergNEF, Gerard Reid, Adam Tooze",
    "hydrogen":       "H2 Bulletin, Hydrogen Insight, H2Tech, Hydrogen Council",
    "nuclear":        "World Nuclear News, NEI Magazine, Energy Storage News",
    "ccus":           "Carbon Capture Journal, Global CCS Institute, Carbon Brief",
    "clean-capital":  "BloombergNEF, IRENA, RMI, IEEFA, Carbon Tracker",
}

# ── Section prompts ─────────────────────────────────────────────────────────
SECTION_PROMPTS = {
    "market-pulse": """
Write 5 energy market intelligence cards for {date}.
Focus on: Brent crude price, WTI price, Henry Hub gas, key OPEC+ moves, major supply disruptions, refinery outages.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "geopolitical": """
Write 4 geopolitical energy analysis cards for {date}.
Focus on: sanctions impacts, pipeline diplomacy, OPEC+ politics, conflict zones affecting energy, US/China/Russia energy policy.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "india": """
Write 4 India energy intelligence cards for {date}.
Focus on: India crude imports, refinery news, ONGC/Reliance/BPCL updates, Indian energy policy, India LNG, domestic gas.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "upstream": """
Write 3 upstream oil & gas intelligence cards for {date}.
Focus on: exploration discoveries, FIDs, production data, drilling campaigns, Baker Hughes rig count, deepwater developments.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "midstream": """
Write 3 midstream intelligence cards for {date}.
Focus on: LNG terminal news, pipeline projects, tanker market, storage levels, new export capacity.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "downstream": """
Write 3 downstream intelligence cards for {date}.
Focus on: refining margins, crack spreads, fuel demand, product inventory, refinery maintenance, gasoline/diesel/jet fuel prices.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "petrochems": """
Write 3 petrochemicals intelligence cards for {date}.
Focus on: ethylene/propylene margins, naphtha prices, polyolefin demand, aromatics market, new cracker projects.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "og-projects": """
Write 3 oil & gas project tracker cards for {date}.
Focus on: recent FIDs, first oil milestones, offshore contract awards, LNG train sanctions, major drilling campaign starts.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "re-projects": """
Write 3 renewable energy project tracker cards for {date}.
Focus on: large solar/wind project announcements, capacity commissioning milestones, storage project awards, offshore wind updates.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "supply-demand": """
Write 3 supply & demand forecast cards for {date}.
Focus on: IEA OMR latest numbers, EIA STEO key figures, OPEC MOMR highlights, demand growth projections, supply outlook.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "frameworks": """
Write 1 strategic framework card for {date}.
Choose one consulting or analytical framework relevant to the current energy market context (e.g. Porter's Five Forces, SWOT, Value Chain Analysis, BCG Matrix, McKinsey 7-S, scenario planning).
Apply it specifically to the oil & gas or energy transition sector.
The card must have a title, a 4-5 sentence explanation of how the framework applies today, and cite a source from: {sources}.
""",
    "narratives": """
Write 3 energy transition narrative cards for {date}.
Focus on: the big-picture story of the energy shift, policy debates, net-zero commitments vs. reality, public narratives, key opinion pieces.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "hydrogen": """
Write 3 hydrogen economy intelligence cards for {date}.
Focus on: green/blue hydrogen project news, electrolyser costs, policy mandates, offtake agreements, FIDs, cost benchmarks.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "nuclear": """
Write 3 nuclear & storage intelligence cards for {date}.
Focus on: SMR project milestones, reactor construction news, battery storage deployments, grid-scale storage contracts, nuclear policy.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "ccus": """
Write 3 CCUS & carbon market cards for {date}.
Focus on: carbon capture project status, carbon credit prices, DAC developments, CCS policy, industrial decarbonisation deals.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
    "clean-capital": """
Write 3 clean energy investment cards for {date}.
Focus on: clean energy deal flow, green bond issuance, VC/PE investment in energy transition, BNEF investment tracker highlights.
Each card must have a title, 2-3 sentence body, and cite a specific source from: {sources}.
""",
}

# ── JSON schema that GPT must return ────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior energy intelligence analyst writing for a professional daily digest.
Today's date is {date}.

For each section you will return ONLY a valid JSON array of card objects.
No preamble, no markdown, no backticks. Pure JSON only.

Each card object must have exactly these fields:
{{
  "title": "Card headline (max 12 words)",
  "source": "Publication or organisation name",
  "source_url": "https://... (best available URL for this source)",
  "body": "2-3 sentence analytical summary. Can use <strong>, <em>, <u> tags for emphasis."
}}

Rules:
- source_url must be a real, working URL for the named publication (homepage or specific article if known)
- body must be analytical, not generic — reference specific numbers, dates, companies where possible
- Maximum 15 cards per section, minimum 1
- Return ONLY the JSON array, nothing else
"""

def generate_section(section_id, prompt, date, sources):
    """Call GPT-4o for one section. Returns list of card dicts."""
    filled_prompt = prompt.format(date=date, sources=sources)
    system = SYSTEM_PROMPT.format(date=date)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": filled_prompt}
            ],
            temperature=0.4,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        # GPT returns {"cards": [...]} or just [...] — handle both
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            cards = parsed
        elif isinstance(parsed, dict):
            # Find the first list value
            cards = next((v for v in parsed.values() if isinstance(v, list)), [])
        else:
            cards = []

        # Validate and sanitise each card
        clean = []
        for c in cards[:15]:  # hard cap at 15
            if not isinstance(c, dict):
                continue
            clean.append({
                "title":      str(c.get("title", "")).strip(),
                "source":     str(c.get("source", "")).strip(),
                "source_url": str(c.get("source_url", "#")).strip(),
                "body":       str(c.get("body", "")).strip(),
            })
        return clean

    except Exception as e:
        # Log error but never log key or response containing key
        print(f"ERROR generating {section_id}: {type(e).__name__}: {e}", file=sys.stderr)
        return []

# ── Generate all sections ────────────────────────────────────────────────────
print(f"Generating digest for {date_str}...")

output = {
    "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
    "date": date_iso,
    "date_display": date_str,
    "sections": {}
}

for section_id, prompt in SECTION_PROMPTS.items():
    print(f"  → {section_id}...", end=" ", flush=True)
    cards = generate_section(section_id, prompt, date_str, SOURCES[section_id])
    output["sections"][section_id] = {"cards": cards}
    print(f"{len(cards)} cards")

# ── Write output ─────────────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(__file__), "..", "data", "content.json")
out_path = os.path.normpath(out_path)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

total = sum(len(s["cards"]) for s in output["sections"].values())
print(f"\nDone. {total} cards written to {out_path}")
