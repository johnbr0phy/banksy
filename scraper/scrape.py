#!/usr/bin/env python3
"""
Banksy Print Tracker - Auction Scraper

Scrapes upcoming Banksy print auctions from major auction houses.
Writes results to data/upcoming.json.

Credentials are read from environment variables:
  LIVEAUCTIONEERS_EMAIL / LIVEAUCTIONEERS_PASSWORD
  PHILLIPS_EMAIL / PHILLIPS_PASSWORD
  SOTHEBYS_EMAIL / SOTHEBYS_PASSWORD
  CHRISTIES_EMAIL / CHRISTIES_PASSWORD
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "upcoming.json"

# Known Banksy print titles for matching
KNOWN_PRINTS = [
    "girl with balloon", "love is in the bin", "flower thrower",
    "laugh now", "pulp fiction", "jack and jill", "soup can",
    "kate moss", "choose your weapon", "queue jumpers", "grannies",
    "happy choppers", "morons", "di-faced tenner", "barcode",
    "bomb hugger", "bomb love", "bombing middle england",
    "flag", "golf sale", "grin reaper", "have a nice day",
    "heavy weaponry", "i fought the law", "insect", "kissing coppers",
    "napalm", "nola", "rage flower thrower", "rude copper",
    "sale ends", "shopping trolleys", "stop and search",
    "toxic mary", "trolley hunters", "very little helps",
    "weston super mare", "wrong war",
]

# Words that indicate the lot is NOT an original Banksy print
EXCLUDE_TERMS = [
    "copy", "tribute", "inspired by", "after banksy",
    "unsigned open edition", "reproduction", "poster only",
    "merchandise", "t-shirt", "mug", "phone case", "nft",
    "sculpture", "bronze", "ceramic", "resin", "figurine",
]


def is_original_banksy_print(title: str, description: str = "") -> bool:
    """Determine if a listing is likely an original Banksy print."""
    text = (title + " " + description).lower()

    # Must reference banksy
    if "banksy" not in text:
        return False

    # Exclude non-originals
    for term in EXCLUDE_TERMS:
        if term in text:
            return False

    # Check for print indicators
    print_indicators = [
        "print", "screenprint", "screen print", "lithograph",
        "giclée", "giclee", "signed", "numbered", "edition",
        "work on paper", "silkscreen",
    ]
    has_print_indicator = any(ind in text for ind in print_indicators)

    # Check for known print titles
    has_known_title = any(t in text for t in KNOWN_PRINTS)

    return has_print_indicator or has_known_title


def parse_estimate(text: str) -> tuple:
    """Parse estimate text into (low, high, currency)."""
    if not text:
        return None, None, "GBP"

    text = text.strip()

    # Detect currency
    currency = "GBP"
    if "$" in text and "£" not in text and "HK" not in text:
        currency = "USD"
    elif "€" in text:
        currency = "EUR"
    elif "CHF" in text:
        currency = "CHF"
    elif "HK$" in text or "HKD" in text:
        currency = "HKD"
    elif "¥" in text or "CNY" in text:
        currency = "CNY"

    # Extract numbers
    numbers = re.findall(r"[\d,]+", text)
    numbers = [int(n.replace(",", "")) for n in numbers if n.replace(",", "").isdigit()]

    if len(numbers) >= 2:
        return min(numbers), max(numbers), currency
    elif len(numbers) == 1:
        return numbers[0], None, currency
    return None, None, currency


def load_existing_data() -> dict:
    """Load existing JSON data, or return empty structure."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read existing data file, starting fresh")
    return {"last_updated": None, "lots": []}


def merge_lots(existing_lots: list, new_lots: list) -> list:
    """Merge new lots into existing, deduplicating by id."""
    by_id = {lot["id"]: lot for lot in existing_lots}
    for lot in new_lots:
        by_id[lot["id"]] = lot  # update or insert

    # Remove lots with past auction dates
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    active = [lot for lot in by_id.values() if (lot.get("auction_date") or "9999") >= today]

    return active


def save_data(data: dict):
    """Write data to JSON file."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Saved %d lots to %s", len(data["lots"]), DATA_FILE)


# ---------------------------------------------------------------------------
# Scraper for each auction house
# ---------------------------------------------------------------------------

async def scrape_liveauctioneers(pw) -> list:
    """Scrape upcoming Banksy lots from LiveAuctioneers."""
    email = os.environ.get("LIVEAUCTIONEERS_EMAIL")
    password = os.environ.get("LIVEAUCTIONEERS_PASSWORD")
    if not email or not password:
        log.warning("LiveAuctioneers credentials not set, skipping")
        return []

    lots = []
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Login
        log.info("LiveAuctioneers: logging in...")
        await page.goto("https://www.liveauctioneers.com/login/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"], input[name="email"]').first
        pass_input = page.locator('input[type="password"]').first
        await email_input.fill(email)
        await pass_input.fill(password)
        await page.locator('button[type="submit"]').first.click()
        await page.wait_for_timeout(5000)

        # Search for Banksy
        log.info("LiveAuctioneers: searching for Banksy...")
        await page.goto(
            "https://www.liveauctioneers.com/search/?keyword=banksy&status=open",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        # Extract lot cards
        cards = await page.query_selector_all('[class*="lot-tile"], [class*="LotTile"], [data-testid="lot-tile"]')
        if not cards:
            # Fallback: try generic item selectors
            cards = await page.query_selector_all(".item-card, .search-result-item, article")

        log.info("LiveAuctioneers: found %d result cards", len(cards))

        for card in cards:
            try:
                title_el = await card.query_selector("h3, h4, [class*='title'], a[class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""

                if not is_original_banksy_print(title):
                    continue

                # Link
                link_el = await card.query_selector("a[href*='/item/'], a[href*='/lot/']")
                url = ""
                lot_id = ""
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else "https://www.liveauctioneers.com" + href
                        id_match = re.search(r"/(?:item|lot)/(\d+)", href)
                        lot_id = id_match.group(1) if id_match else ""

                if not lot_id:
                    continue

                # Image
                img_el = await card.query_selector("img")
                image_url = ""
                if img_el:
                    image_url = await img_el.get_attribute("src") or ""

                # Auction house & date
                house_el = await card.query_selector("[class*='house'], [class*='auctioneer'], [class*='subtitle']")
                house = (await house_el.inner_text()).strip() if house_el else "Unknown"

                date_el = await card.query_selector("[class*='date'], time")
                date_text = ""
                if date_el:
                    date_text = await date_el.get_attribute("datetime") or (await date_el.inner_text()).strip()

                auction_date = ""
                if date_text:
                    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y"):
                        try:
                            auction_date = datetime.strptime(date_text[:10], fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue

                # Estimate
                est_el = await card.query_selector("[class*='estimate'], [class*='price']")
                est_text = (await est_el.inner_text()).strip() if est_el else ""
                low, high, currency = parse_estimate(est_text)

                lots.append({
                    "id": f"liveauctioneers-{lot_id}",
                    "print_name": title,
                    "auction_house": house,
                    "auction_date": auction_date,
                    "edition": "",
                    "low_estimate": low,
                    "high_estimate": high,
                    "currency": currency,
                    "url": url,
                    "image_url": image_url,
                    "source": "liveauctioneers",
                    "is_original": True,
                })
            except Exception as e:
                log.debug("LiveAuctioneers: error parsing card: %s", e)
                continue

    except Exception as e:
        log.error("LiveAuctioneers scrape failed: %s", e)
    finally:
        await browser.close()

    log.info("LiveAuctioneers: scraped %d lots", len(lots))
    return lots


async def scrape_phillips(pw) -> list:
    """Scrape upcoming Banksy lots from Phillips."""
    email = os.environ.get("PHILLIPS_EMAIL")
    password = os.environ.get("PHILLIPS_PASSWORD")
    if not email or not password:
        log.warning("Phillips credentials not set, skipping")
        return []

    lots = []
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Login
        log.info("Phillips: logging in...")
        await page.goto("https://www.phillips.com/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"], input[name="email"], #email').first
        pass_input = page.locator('input[type="password"]').first
        await email_input.fill(email)
        await pass_input.fill(password)
        await page.locator('button[type="submit"], input[type="submit"]').first.click()
        await page.wait_for_timeout(5000)

        # Search
        log.info("Phillips: searching for Banksy...")
        await page.goto(
            "https://www.phillips.com/search#q=banksy&layout=list",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("[class*='search-result'], [class*='lot-item'], .lot")

        log.info("Phillips: found %d result cards", len(cards))

        for card in cards:
            try:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='lot-name']")
                title = (await title_el.inner_text()).strip() if title_el else ""

                if not is_original_banksy_print(title):
                    continue

                link_el = await card.query_selector("a[href*='/lot/'], a[href*='/detail/']")
                url = ""
                lot_id = ""
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else "https://www.phillips.com" + href
                        id_match = re.search(r"/(?:lot|detail)/(\w+)", href)
                        lot_id = id_match.group(1) if id_match else ""

                if not lot_id:
                    continue

                img_el = await card.query_selector("img")
                image_url = ""
                if img_el:
                    image_url = await img_el.get_attribute("src") or ""

                house = "Phillips"

                date_el = await card.query_selector("[class*='date'], time")
                date_text = ""
                if date_el:
                    date_text = await date_el.get_attribute("datetime") or (await date_el.inner_text()).strip()

                auction_date = ""
                if date_text:
                    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d %B %Y"):
                        try:
                            auction_date = datetime.strptime(date_text[:10], fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue

                est_el = await card.query_selector("[class*='estimate'], [class*='price']")
                est_text = (await est_el.inner_text()).strip() if est_el else ""
                low, high, currency = parse_estimate(est_text)

                edition_el = await card.query_selector("[class*='edition'], [class*='medium']")
                edition = (await edition_el.inner_text()).strip() if edition_el else ""

                lots.append({
                    "id": f"phillips-{lot_id}",
                    "print_name": title,
                    "auction_house": house,
                    "auction_date": auction_date,
                    "edition": edition,
                    "low_estimate": low,
                    "high_estimate": high,
                    "currency": currency,
                    "url": url,
                    "image_url": image_url,
                    "source": "phillips",
                    "is_original": True,
                })
            except Exception as e:
                log.debug("Phillips: error parsing card: %s", e)
                continue

    except Exception as e:
        log.error("Phillips scrape failed: %s", e)
    finally:
        await browser.close()

    log.info("Phillips: scraped %d lots", len(lots))
    return lots


async def scrape_sothebys(pw) -> list:
    """Scrape upcoming Banksy lots from Sotheby's."""
    email = os.environ.get("SOTHEBYS_EMAIL")
    password = os.environ.get("SOTHEBYS_PASSWORD")
    if not email or not password:
        log.warning("Sotheby's credentials not set, skipping")
        return []

    lots = []
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Login
        log.info("Sotheby's: logging in...")
        await page.goto("https://www.sothebys.com/en/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"], input[name="email"]').first
        pass_input = page.locator('input[type="password"]').first
        await email_input.fill(email)
        await pass_input.fill(password)
        await page.locator('button[type="submit"]').first.click()
        await page.wait_for_timeout(5000)

        # Search
        log.info("Sotheby's: searching for Banksy...")
        await page.goto(
            "https://www.sothebys.com/en/results?from=&to=&q=banksy&f2=00000164-609b-d1db-a5e6-e9ff00080007",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("[class*='SearchResult'], [class*='lot-card'], [class*='Card']")

        log.info("Sotheby's: found %d result cards", len(cards))

        for card in cards:
            try:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='lotName']")
                title = (await title_el.inner_text()).strip() if title_el else ""

                if not is_original_banksy_print(title):
                    continue

                link_el = await card.query_selector("a[href*='/lot/'], a[href*='/buy/']")
                url = ""
                lot_id = ""
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else "https://www.sothebys.com" + href
                        id_match = re.search(r"/(?:lot|buy)/([a-zA-Z0-9-]+)", href)
                        lot_id = id_match.group(1) if id_match else ""

                if not lot_id:
                    continue

                img_el = await card.query_selector("img")
                image_url = ""
                if img_el:
                    image_url = await img_el.get_attribute("src") or ""

                house = "Sotheby's"

                date_el = await card.query_selector("[class*='date'], time, [class*='sale']")
                date_text = ""
                if date_el:
                    date_text = await date_el.get_attribute("datetime") or (await date_el.inner_text()).strip()

                auction_date = ""
                if date_text:
                    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d %B %Y"):
                        try:
                            auction_date = datetime.strptime(date_text[:10], fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue

                est_el = await card.query_selector("[class*='estimate'], [class*='price']")
                est_text = (await est_el.inner_text()).strip() if est_el else ""
                low, high, currency = parse_estimate(est_text)

                edition_el = await card.query_selector("[class*='edition'], [class*='medium'], [class*='description']")
                edition = (await edition_el.inner_text()).strip() if edition_el else ""

                lots.append({
                    "id": f"sothebys-{lot_id}",
                    "print_name": title,
                    "auction_house": house,
                    "auction_date": auction_date,
                    "edition": edition,
                    "low_estimate": low,
                    "high_estimate": high,
                    "currency": currency,
                    "url": url,
                    "image_url": image_url,
                    "source": "sothebys",
                    "is_original": True,
                })
            except Exception as e:
                log.debug("Sotheby's: error parsing card: %s", e)
                continue

    except Exception as e:
        log.error("Sotheby's scrape failed: %s", e)
    finally:
        await browser.close()

    log.info("Sotheby's: scraped %d lots", len(lots))
    return lots


async def scrape_christies(pw) -> list:
    """Scrape upcoming Banksy lots from Christie's."""
    email = os.environ.get("CHRISTIES_EMAIL")
    password = os.environ.get("CHRISTIES_PASSWORD")
    if not email or not password:
        log.warning("Christie's credentials not set, skipping")
        return []

    lots = []
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Login
        log.info("Christie's: logging in...")
        await page.goto("https://www.christies.com/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"], input[name="email"]').first
        pass_input = page.locator('input[type="password"]').first
        await email_input.fill(email)
        await pass_input.fill(password)
        await page.locator('button[type="submit"]').first.click()
        await page.wait_for_timeout(5000)

        # Search
        log.info("Christie's: searching for Banksy...")
        await page.goto(
            "https://www.christies.com/search?entry=banksy&action=paging&SortBy=relevance&StartFrom=0&PageSize=60&lid=1&language=en",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("[class*='search-result'], [class*='lot-tile'], [class*='LotTile']")

        log.info("Christie's: found %d result cards", len(cards))

        for card in cards:
            try:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='lot-name']")
                title = (await title_el.inner_text()).strip() if title_el else ""

                if not is_original_banksy_print(title):
                    continue

                link_el = await card.query_selector("a[href*='/lot/']")
                url = ""
                lot_id = ""
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else "https://www.christies.com" + href
                        id_match = re.search(r"/lot/(\d+)", href)
                        lot_id = id_match.group(1) if id_match else ""

                if not lot_id:
                    continue

                img_el = await card.query_selector("img")
                image_url = ""
                if img_el:
                    image_url = await img_el.get_attribute("src") or ""

                house = "Christie's"

                date_el = await card.query_selector("[class*='date'], time")
                date_text = ""
                if date_el:
                    date_text = await date_el.get_attribute("datetime") or (await date_el.inner_text()).strip()

                auction_date = ""
                if date_text:
                    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d %B %Y"):
                        try:
                            auction_date = datetime.strptime(date_text[:10], fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue

                est_el = await card.query_selector("[class*='estimate'], [class*='price']")
                est_text = (await est_el.inner_text()).strip() if est_el else ""
                low, high, currency = parse_estimate(est_text)

                edition_el = await card.query_selector("[class*='edition'], [class*='medium']")
                edition = (await edition_el.inner_text()).strip() if edition_el else ""

                lots.append({
                    "id": f"christies-{lot_id}",
                    "print_name": title,
                    "auction_house": house,
                    "auction_date": auction_date,
                    "edition": edition,
                    "low_estimate": low,
                    "high_estimate": high,
                    "currency": currency,
                    "url": url,
                    "image_url": image_url,
                    "source": "christies",
                    "is_original": True,
                })
            except Exception as e:
                log.debug("Christie's: error parsing card: %s", e)
                continue

    except Exception as e:
        log.error("Christie's scrape failed: %s", e)
    finally:
        await browser.close()

    log.info("Christie's: scraped %d lots", len(lots))
    return lots


async def run_all_scrapers() -> list:
    """Run all scrapers, collecting lots from each."""
    all_lots = []
    async with async_playwright() as pw:
        scrapers = [
            ("LiveAuctioneers", scrape_liveauctioneers),
            ("Phillips", scrape_phillips),
            ("Sotheby's", scrape_sothebys),
            ("Christie's", scrape_christies),
        ]
        for name, scraper_fn in scrapers:
            try:
                log.info("Starting %s scraper...", name)
                lots = await scraper_fn(pw)
                all_lots.extend(lots)
                log.info("%s: collected %d lots", name, len(lots))
            except Exception as e:
                log.error("%s scraper failed: %s", name, e)
                continue

    return all_lots


def main(dry_run: bool = False):
    """Main entry point."""
    log.info("Banksy Print Tracker - starting scrape")

    new_lots = asyncio.run(run_all_scrapers())
    log.info("Total new lots scraped: %d", len(new_lots))

    if dry_run:
        print(json.dumps(new_lots, indent=2))
        return

    existing = load_existing_data()
    merged = merge_lots(existing.get("lots", []), new_lots)

    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lots": merged,
    }

    save_data(data)
    log.info("Done. %d active lots in data file.", len(merged))


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
