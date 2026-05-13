# The Daily Crude

Daily O&G energy intelligence brief — auto-generated at 08:00 IST.

**Live site:** https://ayush-kothari97.github.io/the-daily-crude

## Files

### index.html
Self-contained single-file frontend. All CSS, JS, and sample `window.DAILY_DATA` inline.
- On build: `generate_content.py` replaces the `<script id="daily-data">` block with live data
- No external dependencies except Google Fonts (CDN)

### generate_content.py
OpenAI GPT-5.5 content generator with `web_search_preview` tool.

**Build schedule:** GitHub Actions at 08:00 IST daily (`cron: '30 2 * * *'` UTC)

## Data refresh schedule

| Day | Trend data | Daily content |
|-----|-----------|---------------|
| Monday | Full 90-day series fetched (d7/d1m/d3m derived + d6m/d1y) | ✓ |
| Tue–Fri | Existing trend_data preserved unchanged | ✓ |
| Saturday | Existing trend_data preserved | Weekend intelligence brief |
| Sunday | Existing trend_data preserved | Monday preview brief |

## Failure handling
- 3 retries with backoff (10s / 30s / 60s) for both daily and trend fetches
- All retries exhausted → branded maintenance page injected → `sys.exit(1)`

## Key data structure
```json
{
  "meta": { "last_updated": "...", "issue_date": "..." },
  "ticker": [...],
  "markets": {
    "prices": [...],
    "trend_data": { "crude": {...}, "gas": {...} },
    "sentiment": {...},
    "eia_stats": [...],
    "drivers": [...]
  },
  "intel": { "mode": "daily|inventory|weekend", ... },
  "article_cards": [...],
  "india": {...},
  "global_news": [...],
  "strategy": {...},
  "projects": [...]
}
```
