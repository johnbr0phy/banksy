# Banksy Print Tracker

A daily-updated static site tracking upcoming auction lots for original Banksy prints worldwide.

## Setup

### 1. Enable GitHub Pages

1. Go to **Settings > Pages** in your GitHub repository
2. Under **Source**, select **Deploy from a branch**
3. Set branch to `main` and folder to `/docs`
4. Click **Save**

Your site will be live at `https://<username>.github.io/banksy/`

### 2. Auction houses tracked

Daily scrapes check these houses (public pages where possible — **no logins required**):

| House | Notes |
|-------|--------|
| Bonhams | Upcoming + past results |
| Christie's | Best-effort (often bot-protected) |
| Forum Auctions | Prints / Banksy department |
| Heritage Auctions | Best-effort |
| Koller Auctions | Best-effort |
| Phillips | Strong completed / realised data |
| Roseberys | Realised results |
| Sotheby's | Available + past lots |
| Tate Ward | Strong realised data |

Invaluable and LiveAuctioneers are also scanned as **aggregators**, but only lots from the houses above (or known print titles) are kept.
### 3. Trigger a Manual Scrape

1. Go to **Actions > Daily Scrape**
2. Click **Run workflow**
3. Select the branch and click **Run workflow**

The scraper runs automatically every day at 6:00 AM UTC.

## Local Development

### Run the scraper locally

```bash
pip install -r scraper/requirements.txt
playwright install chromium

# Full run (writes docs/data/upcoming.json + data/upcoming.json)
# LiveAuctioneers + Bonhams work with NO credentials.
python scraper/scrape.py

# Optional: major-house scrapers if you have accounts
export PHILLIPS_EMAIL="your@email.com"
export PHILLIPS_PASSWORD="yourpassword"
# ... SOTHEBYS_*, CHRISTIES_* ...

# Dry run (prints to stdout, no file writes)
python scraper/scrape.py --dry-run
```

### Run tests

```bash
cd scraper
python test_scraper.py                    # Unit tests only
python test_scraper.py liveauctioneers    # Unit tests + live scraper test
python test_scraper.py bonhams
```

### Preview the site

Serve the `docs/` folder with any static server:

```bash
python -m http.server 8000 --directory docs
```

Then open `http://localhost:8000`. Auction data is loaded from `docs/data/upcoming.json`.

## Adding New Auction Sources

1. Add a new `async def scrape_newsite(pw)` function in `scraper/scrape.py`
2. Follow the same pattern: search (prefer public pages), extract, filter with `is_original_banksy_print()`
3. Add the function to the `scrapers` list in `run_all_scrapers()`
4. If credentials are needed, add env vars to the GitHub Actions workflow + repo secrets

## File Structure

```
├── docs/               # GitHub Pages site (publish root)
│   ├── index.html      # Upcoming auctions page
│   ├── completed.html  # Completed auctions (stub)
│   ├── data/
│   │   └── upcoming.json  # Served by the site (auto-updated)
│   ├── css/style.css
│   └── js/app.js
├── data/
│   └── upcoming.json   # Mirror of docs/data (for tooling)
├── scraper/
│   ├── scrape.py       # Main scraper
│   ├── test_scraper.py # Tests
│   └── requirements.txt
├── .github/workflows/
│   └── daily-update.yml  # Daily scrape automation
└── README.md
```

## Data Format

`data/upcoming.json`:

```json
{
  "last_updated": "2026-03-27T06:00:00Z",
  "lots": [
    {
      "id": "liveauctioneers-12345",
      "print_name": "Girl With Balloon",
      "auction_house": "Sotheby's",
      "auction_date": "2026-04-15",
      "edition": "Signed, numbered /150",
      "low_estimate": 80000,
      "high_estimate": 120000,
      "currency": "GBP",
      "url": "https://...",
      "image_url": "https://...",
      "source": "liveauctioneers",
      "is_original": true
    }
  ]
}
```
