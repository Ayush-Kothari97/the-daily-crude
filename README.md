# The Energy Intelligence Brief

A personal daily energy intelligence dashboard — automatically updated every day at 7:00 AM IST.

## Live Dashboard
**[ayush-kothari97.github.io/the-daily-crude](https://ayush-kothari97.github.io/the-daily-crude)**

## How it works

```
7:00 AM IST (01:30 UTC)
        │
        ▼
GitHub Actions runner (Ubuntu, server-side)
        │  reads OPENAI_API_KEY from GitHub Secrets
        ▼
OpenAI GPT-4o searches and writes all digest sections
        │
        ▼
data/content.json committed to repo
        │
        ▼
GitHub Pages serves updated dashboard
        │
        ▼
Browser loads index.html → fetches content.json → populates cards
```

## Repository structure

```
energy-brief/
├── index.html                   ← Dashboard (self-contained, all map data inline)
├── data/
│   └── content.json             ← Daily generated content (auto-committed)
├── scripts/
│   └── generate_digest.py       ← OpenAI generation script
├── .github/
│   └── workflows/
│       └── daily-digest.yml     ← GitHub Actions cron job
└── README.md
```

## Security

- The `OPENAI_API_KEY` is stored **only** in GitHub Secrets (Settings → Secrets → Actions)
- It is **never** written to any file in this repository
- It is **never** printed or logged during the workflow
- It is injected into the Actions runner memory at runtime only
- Users of the dashboard download `index.html` and `content.json` — neither contains any key

## Manual trigger

To regenerate the digest at any time:
1. Go to **Actions** tab in this repository
2. Select **Daily Energy Digest**
3. Click **Run workflow**

## Sections covered

| Section | Sources |
|---|---|
| Daily Market Pulse | OGJ, OilPrice.com, EIA, Platts, Argus |
| Geopolitical Lens | CSIS, Columbia CGEP, OIES, Doomberg |
| India Monitor | India Energy Week, TERI, MoPNG |
| Sector Deep Dive | SPE/JPT, Wood Mackenzie, Rystad, ICIS |
| Project Tracker | Hart Energy, Upstream Online, Renewables Now |
| Supply & Demand | IEA OMR, EIA STEO, OPEC MOMR |
| Strategic Frameworks | McKinsey, BCG, Deloitte |
| Energy Transition | Canary Media, Carbon Brief, BNEF, H2 Bulletin, World Nuclear News |

## Built by
Ayush Kothari · [Substack](https://substack.com) · Mumbai, India
