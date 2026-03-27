# Banksy Print Tracker

A daily-updated static site tracking upcoming auction lots for original Banksy prints worldwide.

## Setup

### 1. Enable GitHub Pages

1. Go to **Settings > Pages** in your GitHub repository
2. Under **Source**, select **Deploy from a branch**
3. Set branch to `main` and folder to `/docs`
4. Click **Save**

Your site will be live at `https://<username>.github.io/banksy/`

### 2. Add Auction Site Credentials

Go to **Settings > Secrets and variables > Actions** and add these 8 repository secrets:

| Secret | Description |
|--------|-------------|
| `LIVEAUCTIONEERS_EMAIL` | LiveAuctioneers login email |
| `LIVEAUCTIONEERS_PASSWORD` | LiveAuctioneers login password |
| `PHILLIPS_EMAIL` | Phillips login email |
| `PHILLIPS_PASSWORD` | Phillips login password |
| `SOTHEBYS_EMAIL` | Sotheby's login email |
| `SOTHEBYS_PASSWORD` | Sotheby's login password |
| `CHRISTIES_EMAIL` | Christie's login email |
| `CHRISTIES_PASSWORD` | Christie's login password |

Any missing credentials will cause that scraper to be skipped (not crash).

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

# Set credentials as environment variables
export LIVEAUCTIONEERS_EMAIL="your@email.com"
export LIVEAUCTIONEERS_PASSWORD="yourpassword"
# ... set other credentials ...

# Full run (writes to data/upcoming.json)
python scraper/scrape.py

# Dry run (prints to stdout, no file writes)
python scraper/scrape.py --dry-run
```

### Run tests

```bash
cd scraper
python test_scraper.py                    # Unit tests only
python test_scraper.py liveauctioneers    # Unit tests + live scraper test
```

### Preview the site

Serve the `docs/` folder with any static server:

```bash
python -m http.server 8000 --directory docs
```

Then open `http://localhost:8000`.

## Adding New Auction Sources

1. Add a new `async def scrape_newsite(pw)` function in `scraper/scrape.py`
2. Follow the same pattern: login, search, extract, filter with `is_original_banksy_print()`
3. Add the function to the `scrapers` list in `run_all_scrapers()`
4. Add the credential env vars to the GitHub Actions workflow
5. Add the corresponding secrets in GitHub repo settings

## File Structure

```
├── docs/               # GitHub Pages site
│   ├── index.html      # Upcoming auctions page
│   ├── completed.html  # Completed auctions (stub)
│   ├── css/style.css   # Styles
│   └── js/app.js       # Frontend logic
├── data/
│   └── upcoming.json   # Auction data (auto-updated)
├── scraper/
│   ├── scrape.py       # Main scraper
│   ├── test_scraper.py # Test/dry-run script
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
