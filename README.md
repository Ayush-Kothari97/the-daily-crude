# The Daily Crude

A professional daily energy intelligence brief — automatically updated every day at 08:00 IST.

## Live Site
**[ayush-kothari97.github.io/the-daily-crude](https://ayush-kothari97.github.io/the-daily-crude)**

## How it works

```
08:00 IST (02:30 UTC) — GitHub Actions cron
        │
        ▼
generate_content.py
        │  reads OPENAI_API_KEY from GitHub Secrets
        │  calls OpenAI Responses API (gpt-4o + web_search_preview)
        │  fetches live prices, news, project updates
        ▼
index.html updated
        │  window.DAILY_DATA injected as inline <script>
        ▼
commit + push to main
        │
        ▼
GitHub Pages serves updated index.html
```

## Repository structure

```
the-daily-crude/
├── index.html                        ← Single-file frontend (self-contained)
├── generate_content.py               ← Content generator (OpenAI Responses API)
├── requirements.txt                  ← Pinned Python dependencies
├── .github/
│   └── workflows/
│       └── daily_update.yml          ← GitHub Actions cron job (08:00 IST)
├── .gitignore
└── README.md
```

## Branches

| Branch | Purpose |
|---|---|
| `main` | Production — GitHub Pages serves from here |
| `develop` | Staging — all active development and testing |

Merge `develop` → `main` only when changes are verified.

## Local development

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export OPENAI_API_KEY=sk-...

# Run the generator
python generate_content.py

# Open index.html in a browser to verify output
```

## GitHub Actions setup

One secret required in **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key |

## Manual trigger

To regenerate content at any time:
1. Go to **Actions** tab
2. Select **Daily Crude — Content Update**
3. Click **Run workflow**

## Coverage

| Section | Data |
|---|---|
| Ticker bar | Brent, WTI, Dubai, JKM LNG, TTF, Henry Hub, EU ETS, OPEC Basket, Naphtha, Gasoil |
| Market pulse | Macro signal, price cards, carbon credits, market drivers |
| India monitor | Headline story, news cards, key stats |
| Global news | 9 sectors: Upstream, Policy, Renewables, Hydrogen, Midstream, Offshore, CCUS, Nuclear, Downstream |
| Strategy | Framework of the Day + 3 mini cards |
| Project tracker | 9 active global energy projects |

## Security

- `OPENAI_API_KEY` is stored **only** in GitHub Secrets
- Never written to any file, never logged, never committed
- Injected into the Actions runner at runtime only

## Built by
Ayush Kothari · Mumbai, India
