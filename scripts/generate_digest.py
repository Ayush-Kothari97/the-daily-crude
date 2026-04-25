"""
generate_digest.py — The Energy Intelligence Brief
----------------------------------------------------
Lean rebuild. Runs daily at 7 AM IST via GitHub Actions.
Model: OpenAI GPT-4o  |  Key: env only, never on disk.

Improvements over prior build:
  • Short sections run in parallel (4 workers) — cuts runtime ~60 %
  • Falls back to previous day's content if a section fails
  • Jittered exponential backoff (no retry storms)
  • Market Pulse returns tickers + key movers + cards (rich UI)
  • Archive: saves dated JSON + updates manifest (30-day rolling window)
"""

import json, os, re, sys, time, random, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError

# ── Bootstrap ──────────────────────────────────────────────────────────────
_key = os.environ.get("OPENAI_API_KEY", "")
if not _key:
    sys.exit("ERROR: OPENAI_API_KEY not set in environment.")
client = OpenAI(api_key=_key, timeout=120.0)
del _key

today    = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
DATE_STR = today.strftime("%A, %d %B %Y")
DATE_ISO = today.strftime("%Y-%m-%d")
DATA_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "content.json")
)
ARCHIVE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "archive")
)

# ── Section definitions ────────────────────────────────────────────────────
# long=True  → 1 card, 600-word analytical essay, 4 096 tokens
# long=False → N cards, concise intelligence briefs, 2 048 tokens
SECTIONS = {
    "market-pulse": {
        "cards": 5, "long": False,
        "src": "OGJ, OilPrice.com, EIA, Platts/S&P Global, Argus Media",
        "prompt": (
            "Generate today's energy market intelligence for {date}. "
            "Tickers (5): Brent crude, WTI crude, Henry Hub natural gas, TTF European gas, Newcastle coal. "
            "Key movers (6): the 6 most significant energy company movers today "
            "(mix of E&P, integrated major, refiner, utility — vary the companies daily). "
            "ticker_reasons (5): one brief reason PER TICKER in the same order "
            "(Brent, WTI, Henry Hub, TTF, Newcastle coal). "
            "Each reason is 2-3 sentences with specific numbers and context for that commodity. "
            "financial_news (4): COMPLETELY DIFFERENT stories from ticker_reasons — "
            "broader market intelligence: OPEC+ policy, refinery/shipping events, "
            "demand outlook, energy policy, or notable trade flows. "
            "Cite from: {src}."
        ),
    },
    "geopolitical": {
        "cards": 4, "long": False,
        "src": "CSIS, Columbia CGEP, OIES, Doomberg, OilPrice.com",
        "prompt": (
            "Write {n} geopolitical energy analysis cards for {date}. "
            "Cover: sanctions impacts on energy flows, pipeline diplomacy, "
            "OPEC+ political dynamics, one conflict affecting energy infrastructure. "
            "Cite from: {src}."
        ),
    },
    "india": {
        "cards": 4, "long": False,
        "src": "India Energy Week, TERI, OilPrice.com, Argus Media, MoPNG",
        "prompt": (
            "Write {n} India energy intelligence cards for {date}. "
            "Cover: India crude import trends, a PSU development (ONGC/BPCL/Reliance), "
            "Indian LNG/gas market news, one energy policy update. "
            "Cite from: {src}."
        ),
    },
    "upstream": {
        "cards": 1, "long": True,
        "src": "SPE/JPT, Wood Mackenzie, Rystad Energy, Hart Energy, OGJ",
        "prompt": (
            "Write a detailed 8-10 min read on the most significant upstream O&G "
            "development for {date}. Cover exploration, production, FIDs, or drilling technology. "
            "Structure: intro paragraph, 4-5 analytical sections with subheadings, key takeaways. "
            "Min 600 words. Cite from: {src}."
        ),
    },
    "midstream": {
        "cards": 1, "long": True,
        "src": "LNG Industry, Gas Processing & LNG, Pipeline & Gas Journal, Offshore Energy",
        "prompt": (
            "Write a detailed 8-10 min read on the most significant midstream energy story "
            "for {date}. Cover LNG markets, pipeline infrastructure, or tanker freight. "
            "Structure: intro, 4-5 analytical sections with subheadings, key takeaways. "
            "Min 600 words. Cite from: {src}."
        ),
    },
    "downstream": {
        "cards": 1, "long": True,
        "src": "Hydrocarbon Processing, OGJ Downstream, Platts, Argus",
        "prompt": (
            "Write a detailed 8-10 min read on the most significant downstream/refining "
            "development for {date}. Cover refining margins, crack spreads, product markets, "
            "or refinery operations. "
            "Structure: intro, 4-5 analytical sections with subheadings, key takeaways. "
            "Min 600 words. Cite from: {src}."
        ),
    },
    "petrochems": {
        "cards": 1, "long": True,
        "src": "ICIS, Hydrocarbon Processing, GlobalData, Offshore Technology",
        "prompt": (
            "Write a detailed 8-10 min read on the most significant petrochemicals "
            "development for {date}. Cover ethylene, propylene, naphtha, polymers, or new cracker projects. "
            "Structure: intro, 4-5 analytical sections with subheadings, key takeaways. "
            "Min 600 words. Cite from: {src}."
        ),
    },
    "og-projects": {
        "cards": 3, "long": False,
        "src": "Hart Energy, Upstream Online, Rystad Energy, Wood Mackenzie",
        "prompt": (
            "Write {n} O&G project tracker cards for {date}. "
            "Cover: FIDs, first oil milestones, offshore contract awards, LNG sanctions. "
            "Cite from: {src}."
        ),
    },
    "re-projects": {
        "cards": 3, "long": False,
        "src": "Renewables Now, reNews, Renewable Energy World",
        "prompt": (
            "Write {n} renewable energy project tracker cards for {date}. "
            "Cover: large solar/wind commissionings, storage project awards, offshore wind milestones. "
            "Cite from: {src}."
        ),
    },
    "supply-demand": {
        "cards": 3, "long": False,
        "src": "IEA Oil Market Report, EIA Short-Term Energy Outlook, OPEC Monthly Oil Market Report",
        "prompt": (
            "Write {n} supply & demand forecast cards for {date}. "
            "One card per agency — IEA, EIA, OPEC — with their most recent demand/supply figures. "
            "Cite from: {src}."
        ),
    },
    "frameworks": {
        "cards": 1, "long": True,
        "src": "McKinsey Energy, BCG, Deloitte, HBR, academic strategy literature",
        "prompt": (
            "Choose the most relevant strategic consulting framework for today's energy market "
            "context ({date}). Write a detailed 8-10 min read applying it analytically to the "
            "energy sector with specific companies and market dynamics. "
            "Structure: framework overview, 4-5 application sections, strategic conclusion. "
            "Min 600 words. End with: [AI-generated analysis — for educational purposes only]. "
            "Cite from: {src}."
        ),
    },
    "narratives": {
        "cards": 3, "long": False,
        "src": "Canary Media, Carbon Brief, BloombergNEF, Gerard Reid, Adam Tooze",
        "prompt": (
            "Write {n} energy transition narrative cards for {date}. "
            "Cover: the dominant transition story, a policy/net-zero development, one analysis piece. "
            "Cite from: {src}."
        ),
    },
    "hydrogen": {
        "cards": 3, "long": False,
        "src": "H2 Bulletin, Hydrogen Insight, H2Tech, Hydrogen Council",
        "prompt": (
            "Write {n} hydrogen economy intelligence cards for {date}. "
            "Cover: project FIDs/milestones, electrolyser/cost developments, offtake agreements. "
            "Cite from: {src}."
        ),
    },
    "nuclear": {
        "cards": 3, "long": False,
        "src": "World Nuclear News, NEI Magazine, Energy Storage News",
        "prompt": (
            "Write {n} nuclear & storage intelligence cards for {date}. "
            "Cover: SMR project milestones, grid-scale battery contracts, nuclear policy or financing. "
            "Cite from: {src}."
        ),
    },
    "ccus": {
        "cards": 3, "long": False,
        "src": "Carbon Capture Journal, Global CCS Institute, Carbon Brief",
        "prompt": (
            "Write {n} CCUS & carbon market cards for {date}. "
            "Cover: carbon capture project updates, carbon credit/ETS prices, DAC developments. "
            "Cite from: {src}."
        ),
    },
    "clean-capital": {
        "cards": 3, "long": False,
        "src": "BloombergNEF, IRENA, RMI, IEEFA, Carbon Tracker",
        "prompt": (
            "Write {n} clean energy investment cards for {date}. "
            "Cover: major deals/fundraises, green bond issuances, BNEF/IRENA investment data. "
            "Cite from: {src}."
        ),
    },
}

# ── System prompts ─────────────────────────────────────────────────────────
_SHORT_SYS = (
    "You are a senior energy intelligence analyst. Today: {date}.\n"
    'Return ONLY a valid JSON object: {{"cards":[...]}}\n'
    'Each card must have exactly: {{"title":"Specific headline max 12 words","source":"Publication",'
    '"source_url":"https://publication-homepage.com","body":"2-3 analytical sentences with specific '
    'numbers, dates, companies. HTML tags <strong><em><u> permitted.","long_read":false}}\n'
    "No markdown fences. No preamble. JSON only."
)
_LONG_SYS = (
    "You are a senior energy intelligence analyst. Today: {date}.\n"
    'Return ONLY a valid JSON object: {{"cards":[{{...}}]}}\n'
    'Card fields: {{"title":"Headline max 15 words","source":"Publication",'
    '"source_url":"https://publication-homepage.com","body":"Full analytical article. '
    "Use <p> tags for paragraphs. <strong> for key terms and companies. Min 600 words.\","
    '"long_read":true}}\n'
    "No markdown fences. No preamble. JSON only."
)
# Special prompt for market-pulse — four arrays, no repeated content
_MARKET_SYS = (
    "You are a senior energy intelligence analyst. Today: {date}.\n"
    "Return ONLY a valid JSON object with exactly four keys: tickers, key_movers, ticker_reasons, financial_news.\n\n"
    "tickers — 5 items, one per commodity:\n"
    '  {{"symbol":"BRENT","label":"Brent Crude Oil","price":"$82.45","unit":"/bbl","change":"+1.2%","dir":"up"}}\n'
    '  dir must be \"up\", \"down\", or \"flat\". price includes currency symbol.\n\n'
    "key_movers — 6 items, the most significant publicly-traded energy company movers today\n"
    "(mix of E&Ps, integrated majors, refiners, utilities — different companies each day):\n"
    '  {{"name":"Saudi Aramco","ticker":"2222.SR","move":"+2.1%","note":"One-line reason","dir":"up"}}\n\n'
    "ticker_reasons — 5 items in SAME ORDER as tickers (Brent, WTI, HH, TTF, Newcastle coal).\n"
    "Each explains ONLY that commodity's price driver in 1-2 sentences. Fields:\n"
    '  {{"body":"1-2 sentences on this commodity price driver today.","source":"Publication"}}\n\n'
    "financial_news — 4 items with DIFFERENT content from ticker_reasons:\n"
    "Cover OPEC+ policy, refinery/shipping events, demand outlook, or trade flows.\n"
    '  {{"title":"Headline max 12 words","source":"Publication","source_url":"https://url.com",'
    '"body":"2-3 analytical sentences with specific numbers."}}\n\n'
    "No markdown fences. No preamble. JSON only."
)


# ── Core API call — standard sections (retry with jitter) ─────────────────
def _call(sid: str, cfg: dict) -> list:
    """Call GPT-4o for one section. Returns list of card dicts, or [] on failure."""
    is_long = cfg["long"]
    system  = (_LONG_SYS if is_long else _SHORT_SYS).format(date=DATE_STR)
    prompt  = cfg["prompt"].format(date=DATE_STR, n=cfg["cards"], src=cfg["src"])
    tokens  = 4096 if is_long else 2048

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.35,
                max_tokens=tokens,
            )
            raw = (resp.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                cards = parsed
            elif isinstance(parsed, dict):
                cards = parsed.get("cards") or next(
                    (v for v in parsed.values() if isinstance(v, list)), []
                )
            else:
                cards = []
            return [
                {
                    "title":      str(c.get("title",      "Untitled")).strip(),
                    "source":     str(c.get("source",     "")).strip(),
                    "source_url": str(c.get("source_url", "#")).strip(),
                    "body":       str(c.get("body",       "")).strip(),
                    "long_read":  bool(c.get("long_read", is_long)),
                }
                for c in cards[:15]
                if isinstance(c, dict)
            ]

        except RateLimitError:
            wait = 30 * (attempt + 1) + random.uniform(0, 10)
            print(f"  [{sid}] rate-limited — wait {wait:.0f}s", flush=True)
            time.sleep(wait)

        except (APITimeoutError, APIConnectionError) as exc:
            wait = 20 * (attempt + 1) + random.uniform(0, 5)
            print(f"  [{sid}] {type(exc).__name__} — wait {wait:.0f}s", flush=True)
            time.sleep(wait)

        except json.JSONDecodeError as exc:
            print(f"  [{sid}] JSON parse error (attempt {attempt + 1}): {exc}", flush=True)
            if attempt == 2:
                return []
            time.sleep(5)

        except Exception as exc:
            print(f"  [{sid}] {type(exc).__name__}: {exc}", flush=True)
            if attempt == 2:
                return []
            time.sleep(10)

    return []


# ── Market Pulse: special call — returns tickers + key_movers + cards ─────
def _call_market() -> dict:
    """Call GPT-4o for market-pulse. Returns {"tickers":[...], "key_movers":[...], "cards":[...]}."""
    _empty = {"tickers": [], "key_movers": [], "ticker_reasons": [], "financial_news": []}
    system = _MARKET_SYS.format(date=DATE_STR)
    cfg    = SECTIONS["market-pulse"]
    prompt = cfg["prompt"].format(date=DATE_STR, n=cfg["cards"], src=cfg["src"])

    def _tk(lst):
        return [
            {
                "symbol": str(t.get("symbol", "")).strip(),
                "label":  str(t.get("label",  "")).strip(),
                "price":  str(t.get("price",  "—")).strip(),
                "unit":   str(t.get("unit",   "")).strip(),
                "change": str(t.get("change", "")).strip(),
                "dir":    str(t.get("dir",    "flat")).strip(),
            }
            for t in (lst or [])[:10] if isinstance(t, dict)
        ]

    def _mv(lst):
        return [
            {
                "name":   str(m.get("name",   "")).strip(),
                "ticker": str(m.get("ticker", "")).strip(),
                "move":   str(m.get("move",   "")).strip(),
                "note":   str(m.get("note",   "")).strip(),
                "dir":    str(m.get("dir",    "flat")).strip(),
            }
            for m in (lst or [])[:10] if isinstance(m, dict)
        ]

    def _reason(lst):
        return [
            {
                "body":   str(r.get("body",   "")).strip(),
                "source": str(r.get("source", "")).strip(),
            }
            for r in (lst or [])[:10] if isinstance(r, dict)
        ]

    def _news(lst):
        return [
            {
                "title":      str(n.get("title",      "Untitled")).strip(),
                "source":     str(n.get("source",     "")).strip(),
                "source_url": str(n.get("source_url", "#")).strip(),
                "body":       str(n.get("body",       "")).strip(),
            }
            for n in (lst or [])[:10] if isinstance(n, dict)
        ]

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.35,
                max_tokens=3500,
            )
            raw = (resp.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
            parsed = json.loads(raw)
            return {
                "tickers":        _tk(parsed.get("tickers",        [])),
                "key_movers":     _mv(parsed.get("key_movers",     [])),
                "ticker_reasons": _reason(parsed.get("ticker_reasons", [])),
                "financial_news": _news(parsed.get("financial_news", [])),
            }

        except RateLimitError:
            wait = 30 * (attempt + 1) + random.uniform(0, 10)
            print(f"  [market-pulse] rate-limited — wait {wait:.0f}s", flush=True)
            time.sleep(wait)

        except (APITimeoutError, APIConnectionError) as exc:
            wait = 20 * (attempt + 1) + random.uniform(0, 5)
            print(f"  [market-pulse] {type(exc).__name__} — wait {wait:.0f}s", flush=True)
            time.sleep(wait)

        except json.JSONDecodeError as exc:
            print(f"  [market-pulse] JSON parse error (attempt {attempt + 1}): {exc}", flush=True)
            if attempt == 2:
                return _empty
            time.sleep(5)

        except Exception as exc:
            print(f"  [market-pulse] {type(exc).__name__}: {exc}", flush=True)
            if attempt == 2:
                return _empty
            time.sleep(10)

    return _empty


# ── Load previous content (fallback on section failure) ────────────────────
def _load_previous() -> dict:
    try:
        with open(DATA_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("sections", {})
    except Exception:
        return {}


# ── Save archive file + update manifest ────────────────────────────────────
def _save_archive(content: dict) -> None:
    """Save today's content to data/archive/YYYY-MM-DD.json and update manifest.json."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # Write dated archive file
    arc_path = os.path.join(ARCHIVE_DIR, f"{DATE_ISO}.json")
    with open(arc_path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, indent=2, ensure_ascii=False)

    # Load existing manifest
    manifest_path = os.path.join(ARCHIVE_DIR, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        manifest = {"dates": []}

    # Add today, deduplicate, keep newest 30, sort descending
    dates = list(set(manifest.get("dates", []) + [DATE_ISO]))
    dates = sorted(dates, reverse=True)[:30]

    manifest["dates"] = dates
    manifest["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(f"Archive: {arc_path}  |  manifest: {len(dates)} dates", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    prev = _load_previous()

    print(f"\nThe Energy Intelligence Brief — {DATE_STR}")
    print(f"Sections: {len(SECTIONS)} total\n")

    results: dict = {}

    short_sids = [s for s, c in SECTIONS.items() if not c["long"] and s != "market-pulse"]
    long_sids  = [s for s, c in SECTIONS.items() if     c["long"]]

    # ── Market Pulse (special structure) ──────────────────────────────────
    print("[0/3] Market Pulse (tickers + reasons + movers + news)")
    print("  → market-pulse ...", end=" ", flush=True)
    mp = _call_market()
    if mp["tickers"] or mp["ticker_reasons"]:
        results["market-pulse"] = mp
        print(f"✓  {len(mp['tickers'])} tickers | {len(mp['key_movers'])} movers | {len(mp['ticker_reasons'])} reasons | {len(mp['financial_news'])} news", flush=True)
    else:
        prev_mp = prev.get("market-pulse", {})
        # Handle old format (plain list) gracefully
        if isinstance(prev_mp, list):
            prev_mp = {"tickers": [], "key_movers": [], "ticker_reasons": [], "financial_news": []}
        results["market-pulse"] = prev_mp or {"tickers": [], "key_movers": [], "ticker_reasons": [], "financial_news": []}
        print("✗ failed — using previous", flush=True)

    # ── Short sections: 4 parallel workers ────────────────────────────────
    print(f"\n[1/3] Short sections ({len(short_sids)} sections, 4 parallel workers)")
    with ThreadPoolExecutor(max_workers=4) as pool:
        fmap = {pool.submit(_call, sid, SECTIONS[sid]): sid for sid in short_sids}
        for fut in as_completed(fmap):
            sid = fmap[fut]
            cards = fut.result() if not fut.exception() else []
            if cards:
                results[sid] = cards
                print(f"  ✓ {sid}: {len(cards)} cards", flush=True)
            else:
                prev_sec = prev.get(sid, {})
                fallback = prev_sec.get("cards", []) if isinstance(prev_sec, dict) else prev_sec
                results[sid] = fallback or []
                tag = f"prev {len(fallback)}" if fallback else "EMPTY"
                print(f"  ✗ {sid}: failed — {tag}", flush=True)

    # ── Long reads: sequential (avoid token hammering) ────────────────────
    print(f"\n[2/3] Long reads ({len(long_sids)} sections, sequential)")
    for sid in long_sids:
        print(f"  → {sid} ...", end=" ", flush=True)
        cards = _call(sid, SECTIONS[sid])
        if cards:
            results[sid] = cards
            print(f"✓ {len(cards)}", flush=True)
        else:
            prev_sec = prev.get(sid, {})
            fallback = prev_sec.get("cards", []) if isinstance(prev_sec, dict) else prev_sec
            results[sid] = fallback or []
            tag = f"prev {len(fallback)}" if fallback else "EMPTY"
            print(f"✗ failed — {tag}", flush=True)

    # ── Build output ───────────────────────────────────────────────────────
    sections_out: dict = {}
    for sid in SECTIONS:
        r = results.get(sid, [])
        if sid == "market-pulse":
            # r is already {"tickers":[...], "key_movers":[...], "cards":[...]}
            sections_out[sid] = r if isinstance(r, dict) else {"tickers": [], "key_movers": [], "cards": r}
        else:
            sections_out[sid] = {"cards": r if isinstance(r, list) else []}

    out = {
        "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
        "date":         DATE_ISO,
        "date_display": DATE_STR,
        "sections":     sections_out,
    }

    # ── Write content.json ─────────────────────────────────────────────────
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    # ── Write archive ──────────────────────────────────────────────────────
    _save_archive(out)

    # ── Summary ────────────────────────────────────────────────────────────
    total = sum(len(v.get("cards", [])) for v in out["sections"].values())
    empty = [k for k, v in out["sections"].items() if not v.get("cards")]

    print(f"\n{'='*54}")
    print(f"Done  : {total} cards across {len(SECTIONS)} sections")
    if empty:
        print(f"Empty : {', '.join(empty)}")
    else:
        print("Status: all sections populated")
    print(f"Saved : {DATA_PATH}")


if __name__ == "__main__":
    main()
