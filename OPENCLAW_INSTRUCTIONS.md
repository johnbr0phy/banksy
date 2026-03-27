# OpenClaw Daily Update Instructions

## Purpose

You are maintaining the **Banksy Print Tracker** — a GitHub Pages site that lists upcoming auction lots for original Banksy prints. Your job is to search auction sites daily, find upcoming Banksy print lots, and update the data file in this repository.

## Repository

- **Repo:** `johnbr0phy/banksy`
- **Data file:** `data/upcoming.json`
- **Branch:** `main`
- **Site:** https://johnbr0phy.github.io/banksy/

## What to do

### 1. Search these auction sources (in priority order)

Search each of these sites for upcoming Banksy lots:

1. **LiveAuctioneers** — https://www.liveauctioneers.com/search/?keyword=banksy+print&status=open
2. **Phillips** — https://www.phillips.com/search#q=banksy
3. **Sotheby's** — https://www.sothebys.com/en/results?q=banksy
4. **Christie's** — https://www.christies.com/search?entry=banksy+print
5. **Bonhams** — https://www.bonhams.com/search/?keyword=banksy+print
6. **Dreweatts** — https://www.dreweatts.com/search/?q=banksy
7. **Forum Auctions** — https://www.forumauctions.co.uk (search for Banksy)
8. **Swann Galleries** — https://www.swanngalleries.com (search for Banksy)

### 2. For each lot found, extract this information

| Field | Description | Example |
|-------|-------------|---------|
| `id` | Source + lot ID (unique key) | `"liveauctioneers-12345"` |
| `print_name` | Name of the print | `"Girl With Balloon"` |
| `auction_house` | Name of auction house | `"Sotheby's"` |
| `auction_date` | Date of auction (YYYY-MM-DD) | `"2026-04-15"` |
| `edition` | Edition info if available | `"Signed, numbered /150"` |
| `low_estimate` | Low estimate as integer (no commas) | `80000` |
| `high_estimate` | High estimate as integer (no commas) | `120000` |
| `currency` | ISO currency code | `"GBP"`, `"USD"`, `"EUR"` |
| `url` | Direct link to the auction lot page | `"https://..."` |
| `image_url` | Thumbnail image URL (if available) | `"https://..."` |
| `source` | Source site name (lowercase) | `"liveauctioneers"` |
| `is_original` | Always `true` (you've already filtered) | `true` |

### 3. Filtering rules (critical — follow strictly)

**ONLY include a lot if ALL of these are true:**

- Artist is **Banksy** (not "after Banksy", not "attributed to Banksy")
- The work is a **print, screenprint, lithograph, giclée, or work on paper**
- The auction date is **in the future** (after today's date)
- The listing does **NOT** contain any of these terms:
  - "copy", "tribute", "inspired by", "after banksy"
  - "unsigned open edition", "reproduction", "poster only"
  - "merchandise", "t-shirt", "mug", "phone case"
  - "NFT", "sculpture", "bronze", "ceramic", "resin", "figurine"

**When in doubt, exclude the lot.** It is better to miss a legitimate lot than to include a fake/copy.

### 4. Known Banksy print titles (for reference)

These are confirmed original Banksy print titles. Use this list to help identify legitimate lots:

Girl With Balloon, Love Is in the Bin, Flower Thrower, Laugh Now, Pulp Fiction,
Jack and Jill, Soup Can, Kate Moss, Choose Your Weapon, Queue Jumpers, Grannies,
Happy Choppers, Morons, Di-Faced Tenner, Barcode, Bomb Hugger, Bomb Love,
Bombing Middle England, Flag, Golf Sale, Grin Reaper, Have a Nice Day,
Heavy Weaponry, I Fought the Law, Insect, Kissing Coppers, Napalm, Nola,
Rage Flower Thrower, Rude Copper, Sale Ends, Shopping Trolleys, Stop and Search,
Toxic Mary, Trolley Hunters, Very Little Helps, Weston Super Mare, Wrong War,
Gangsta Rat, Monkey Queen, Monkey Parliament, Festival (Destroy Capitalism),
Donuts (Chocolate), Donuts (Strawberry), Applause, Bad Meaning Good,
Brace Yourself, CND Soldiers, Dismaland, Every Picture Tells a Lie,
Flying Copper, Forgive Us Our Trespassing, Free Zehra Dogan, Get Out While You Can,
Grannies, Happy Choppers, Laugh Now But One Day We'll Be in Charge, Love Rat,
Mean and Vicious, Monkey Detonator, No Ball Games, Radar Rat, Record,
Rude Snowman, Season's Greetings, Sunflowers, Welcome to Hell

### 5. Update the data file

The data file is `data/upcoming.json`. Its structure is:

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

**Update rules:**

- **Read the existing file first** — do not overwrite from scratch
- **Merge** new lots into the existing list using the `id` field as the unique key
- **Update** existing lots if data has changed (e.g. estimate updated)
- **Remove** lots where the `auction_date` is in the past (before today)
- **Set `last_updated`** to the current UTC timestamp in ISO 8601 format
- **Keep `low_estimate` and `high_estimate` as integers**, not strings (no commas, no currency symbols)
- If an estimate is not available, set the field to `null`
- If an image URL is not available, set `image_url` to `""` (empty string)

### 6. Commit and push

After updating `data/upcoming.json`:

1. Commit with message: `Update upcoming auction data YYYY-MM-DDTHH:MM:SSZ`
2. Push to `main` branch
3. The GitHub Pages site will automatically redeploy

## Example workflow

```
1. Read data/upcoming.json to get current lots
2. Search LiveAuctioneers for "banksy print" — filter results
3. Search Phillips for "banksy" — filter results
4. Search Sotheby's for "banksy" — filter results
5. Search Christie's for "banksy print" — filter results
6. Search any additional sources
7. Merge all new lots into existing data
8. Remove lots with past auction dates
9. Update last_updated timestamp
10. Write updated data/upcoming.json
11. Commit and push to main
```

## Error handling

- If a site is down or returns no results, **skip it and continue** with other sources
- If you cannot determine whether a lot is an original print, **exclude it**
- If you find zero new lots across all sources, still update `last_updated` and remove expired lots
- Never commit credentials, API keys, or personal information

## Schedule

Run this task **daily at 6:00 AM UTC**, or when manually triggered.
