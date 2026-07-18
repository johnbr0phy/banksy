#!/usr/bin/env python3
"""
Banksy Print Tracker - Auction Scraper

Scrapes upcoming Banksy print auctions from major sources and writes
results to docs/data/upcoming.json (served by GitHub Pages) and
data/upcoming.json (kept in sync for tooling).

Public sources (no credentials required):
  - LiveAuctioneers
  - Bonhams

Optional sources (skipped if credentials missing):
  - Phillips, Sotheby's, Christie's
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
# GitHub Pages publishes /docs — this is the file the site actually serves.
DATA_FILE = REPO_ROOT / "docs" / "data" / "upcoming.json"
# Mirror for OpenClaw / local tooling that still look under data/.
DATA_FILE_MIRROR = REPO_ROOT / "data" / "upcoming.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

KNOWN_PRINTS = [
    "girl with balloon", "love is in the bin", "flower thrower", "thrower",
    "laugh now", "pulp fiction", "jack and jill", "soup can",
    "kate moss", "choose your weapon", "queue jumpers", "grannies",
    "happy choppers", "morons", "di-faced tenner", "barcode",
    "bomb hugger", "bomb love", "bombing middle england", "bomb middle england",
    "flag", "golf sale", "grin reaper", "have a nice day",
    "heavy weaponry", "i fought the law", "insect", "kissing coppers",
    "napalm", "nola", "rage flower thrower", "rude copper",
    "sale ends", "shopping trolleys", "stop and search",
    "toxic mary", "trolley hunters", "trolleys", "very little helps",
    "weston super mare", "wrong war", "gangsta rat", "monkey queen",
    "monkey parliament", "festival", "donuts", "applause",
    "bad meaning good", "brace yourself", "cnd soldiers", "dismaland",
    "flying copper", "forgive us our trespassing", "get out while you can",
    "love rat", "mean and vicious", "monkey detonator", "no ball games",
    "radar rat", "rude snowman", "season's greetings", "sunflowers",
    "welcome to hell", "queen vic", "hmv dog", "love is in the air",
    "because i'm worthless", "banksquiat", "christ with shopping bags",
]

# Multi-word / phrase excludes (substring match on lowercased text).
EXCLUDE_PHRASES = [
    "after banksy",
    "inspired by",
    "in the style of",
    "style of banksy",
    "style of street",
    "unsigned open edition",
    "reproduction",
    "poster only",
    "merchandise",
    "t-shirt",
    "phone case",
    "death nyc",
    "print after",
    "print sold after",
    "sold after",
    "attributed to",
    "school of",
    "homage to",
    "tribute to",
    # Common unauthorized / novelty listings on secondary marketplaces
    "dinner with",
    "dinner alone",
    "mixed media",
    "canvas mixed media",
    "acrylic on canvas",
    "painting on stretched canvas",
    "giclee on canvas",
    "giclée on canvas",
    "hand painted",
    "hand-painted",
    "oil on canvas",
]

# Single-word excludes matched with word boundaries (avoids "copy" in "copyright").
EXCLUDE_WORDS = [
    "copy", "tribute", "nft", "sculpture", "bronze", "ceramic",
    "resin", "figurine", "mug", "tshirt", "hoodie",
]


def is_original_banksy_print(title: str, description: str = "") -> bool:
    """Determine if a listing is likely an original Banksy print."""
    text = f"{title} {description}".lower()

    if "banksy" not in text:
        return False

    for phrase in EXCLUDE_PHRASES:
        if phrase in text:
            return False

    for word in EXCLUDE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return False

    print_indicators = [
        "print", "screenprint", "screen print", "lithograph",
        "giclée", "giclee", "signed", "numbered", "edition",
        "work on paper", "silkscreen", "offset lithograph",
    ]
    has_print_indicator = any(ind in text for ind in print_indicators)
    has_known_title = any(t in text for t in KNOWN_PRINTS)

    # Require a print medium for unknown titles; known titles may pass alone.
    if has_known_title:
        return True
    return has_print_indicator


def parse_estimate(text: str) -> tuple:
    """Parse estimate text into (low, high, currency)."""
    if not text:
        return None, None, "GBP"

    text = text.strip()

    currency = "GBP"
    if "HK$" in text or "HKD" in text:
        currency = "HKD"
    elif "US$" in text or ("$" in text and "£" not in text and "HK" not in text):
        currency = "USD"
    elif "€" in text or "EUR" in text:
        currency = "EUR"
    elif "CHF" in text:
        currency = "CHF"
    elif "¥" in text or "CNY" in text:
        currency = "CNY"
    elif "£" in text or "GBP" in text:
        currency = "GBP"

    numbers = re.findall(r"[\d,]+(?:\.\d+)?", text)
    ints = []
    for n in numbers:
        cleaned = n.replace(",", "")
        try:
            ints.append(int(float(cleaned)))
        except ValueError:
            continue

    if len(ints) >= 2:
        return min(ints), max(ints), currency
    if len(ints) == 1:
        return ints[0], None, currency
    return None, None, currency


def parse_auction_date(date_text: str) -> str:
    """Parse a free-form date string to YYYY-MM-DD, or '' if unknown."""
    if not date_text:
        return ""

    text = " ".join(str(date_text).strip().split())
    # Skip relative countdowns
    if re.search(r"\b(day|days|hr|hrs|hour|hours|left|ends in|buy now)\b", text, re.I):
        if not re.search(r"\d{4}", text):
            return ""

    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)

    cleaned = text.replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    candidates = [cleaned]
    # Extract month-name date substrings
    m = re.search(
        r"([A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})",
        cleaned,
    )
    if m:
        candidates.append(m.group(1))
    m = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        cleaned,
    )
    if m:
        candidates.append(m.group(1))
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", cleaned)
    if m:
        candidates.append(m.group(1))

    formats = (
        "%b %d %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    )
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return ""


def load_existing_data() -> dict:
    """Load existing JSON data from primary or mirror path."""
    for path in (DATA_FILE, DATA_FILE_MIRROR):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                log.warning("Could not read %s", path)
    return {"last_updated": None, "lots": []}


def merge_lots(existing_lots: list, new_lots: list) -> list:
    """Merge new lots into existing, deduplicating by id. Drop past-dated lots."""
    by_id = {lot["id"]: lot for lot in existing_lots if lot.get("id")}
    for lot in new_lots:
        if lot.get("id"):
            by_id[lot["id"]] = lot

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    active = []
    for lot in by_id.values():
        date = (lot.get("auction_date") or "").strip()
        if not date:
            # Keep undated lots only if freshly scraped this run (present in new_lots).
            if any(n.get("id") == lot["id"] for n in new_lots):
                active.append(lot)
            continue
        if date >= today:
            active.append(lot)

    active.sort(key=lambda lot: lot.get("auction_date") or "9999-99-99")
    return active


def save_data(data: dict) -> None:
    """Write data to both primary (Pages) and mirror paths."""
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for path in (DATA_FILE, DATA_FILE_MIRROR):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        log.info("Saved %d lots to %s", len(data["lots"]), path)


def make_lot(
    *,
    lot_id: str,
    print_name: str,
    auction_house: str,
    auction_date: str,
    edition: str,
    low_estimate: Optional[int],
    high_estimate: Optional[int],
    currency: str,
    url: str,
    image_url: str,
    source: str,
) -> dict:
    return {
        "id": lot_id,
        "print_name": print_name,
        "auction_house": auction_house,
        "auction_date": auction_date,
        "edition": edition or "",
        "low_estimate": low_estimate,
        "high_estimate": high_estimate,
        "currency": currency or "GBP",
        "url": url,
        "image_url": image_url or "",
        "source": source,
        "is_original": True,
    }


# Major houses: trust their cataloguing more than regional secondary listings.
MAJOR_SOURCES = frozenset({"bonhams", "phillips", "sothebys", "christies"})


def is_plausible_lot(lot: dict) -> bool:
    """Drop obvious low-end / buy-now junk that still passed the text filter."""
    title = (lot.get("print_name") or "").lower()
    source = lot.get("source") or ""
    low = lot.get("low_estimate")

    if "buy it now" in title or "buy now" in title:
        return False

    # Major houses: trust cataloguing more.
    if source in MAJOR_SOURCES:
        return True

    # Secondary market (e.g. LiveAuctioneers): must match a known print title.
    # High estimates alone are not enough — fakes often list absurd numbers.
    has_known = any(t in title for t in KNOWN_PRINTS)
    if has_known and (low is None or low >= 1000):
        return True
    return False


async def new_browser_page(pw):
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    return browser, page


# ---------------------------------------------------------------------------
# Public scrapers (no credentials)
# ---------------------------------------------------------------------------

async def scrape_liveauctioneers(pw) -> list:
    """Scrape upcoming Banksy lots from LiveAuctioneers (public, no login)."""
    lots = []
    browser = None
    try:
        browser, page = await new_browser_page(pw)
        url = "https://www.liveauctioneers.com/c/art/creator/banksy/"
        log.info("LiveAuctioneers: loading %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(7000)

        # Scroll to load more results
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(1200)

        cards = await page.evaluate(
            """() => {
              const anchors = [...document.querySelectorAll("a[href*='/item/']")];
              const seen = new Set();
              const out = [];
              for (const a of anchors) {
                const m = a.href.match(/\\/item\\/(\\d+)/);
                if (!m || seen.has(m[1])) continue;
                seen.add(m[1]);
                let best = a, el = a;
                for (let i = 0; i < 10 && el.parentElement; i++) {
                  el = el.parentElement;
                  const t = (el.innerText || "");
                  if (t.length > 40 && t.length < 900 && /Est\\.|Estimate|\\$|£|€/i.test(t)) {
                    best = el;
                    break;
                  }
                  if (t.length > 40 && t.length < 500) best = el;
                }
                const text = (best.innerText || "").trim();
                const lines = text.split("\\n").map(s => s.trim()).filter(Boolean);
                const img = best.querySelector("img");
                out.push({
                  id: m[1],
                  href: a.href.split("?")[0],
                  lines,
                  img: img ? (img.currentSrc || img.src || "") : ""
                });
              }
              return out;
            }"""
        )

        log.info("LiveAuctioneers: found %d candidate cards", len(cards))

        for card in cards:
            try:
                lines = card.get("lines") or []
                # Title: first line that mentions Banksy or looks like a title
                title = ""
                for line in lines:
                    if re.search(r"banksy", line, re.I):
                        title = line
                        break
                if not title and len(lines) >= 2:
                    title = lines[1]
                if not title:
                    # Fallback: slug from URL
                    slug = card["href"].split("/item/")[-1]
                    slug = re.sub(r"^\d+_", "", slug)
                    title = slug.replace("-", " ")

                if not is_original_banksy_print(title, " ".join(lines)):
                    continue

                date_text = ""
                for line in lines:
                    if parse_auction_date(line):
                        date_text = line
                        break
                    if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", line):
                        date_text = line
                        break

                auction_date = parse_auction_date(date_text)

                est_text = ""
                for line in lines:
                    if re.search(r"Est\.|Estimate", line, re.I):
                        est_text = line
                        break
                low, high, currency = parse_estimate(est_text)

                # House: usually near the end, after bids
                house = "Unknown"
                skip_bits = re.compile(
                    r"est\.|estimate|bid|banksy|\$|£|€|\d{4}|day|hr|left|ends",
                    re.I,
                )
                for line in reversed(lines):
                    if len(line) < 3 or skip_bits.search(line):
                        continue
                    if re.match(r"^[A-Z][A-Za-z0-9 &.'\-]{2,60}$", line) or (
                        "," not in line and len(line) > 4 and not line.startswith("(")
                    ):
                        # Prefer non-location lines
                        if re.search(r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV)\b", line):
                            continue
                        house = line
                        break

                lots.append(
                    make_lot(
                        lot_id=f"liveauctioneers-{card['id']}",
                        print_name=title,
                        auction_house=house,
                        auction_date=auction_date,
                        edition="",
                        low_estimate=low,
                        high_estimate=high,
                        currency=currency,
                        url=card["href"] if card["href"].startswith("http") else f"https://www.liveauctioneers.com{card['href']}",
                        image_url=card.get("img") or "",
                        source="liveauctioneers",
                    )
                )
            except Exception as e:
                log.debug("LiveAuctioneers: card parse error: %s", e)
                continue

    except Exception as e:
        log.error("LiveAuctioneers scrape failed: %s", e)
    finally:
        if browser:
            await browser.close()

    log.info("LiveAuctioneers: scraped %d lots", len(lots))
    return lots


async def scrape_bonhams(pw) -> list:
    """Scrape upcoming Banksy lots from Bonhams via their public search API."""
    lots = []
    browser = None
    docs: list[dict] = []

    try:
        browser, page = await new_browser_page(pw)

        async def on_response(resp):
            if "multi_search" not in resp.url or resp.status != 200:
                return
            try:
                payload = await resp.json()
                for hit in payload.get("results", [{}])[0].get("hits", []):
                    doc = hit.get("document")
                    if doc:
                        docs.append(doc)
            except Exception as e:
                log.debug("Bonhams: response parse error: %s", e)

        page.on("response", on_response)

        url = "https://www.bonhams.com/search/?q=banksy&main_index_key=lot"
        log.info("Bonhams: loading %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(8000)

        log.info("Bonhams: captured %d search documents", len(docs))

        for doc in docs:
            try:
                title = (doc.get("title") or doc.get("slug") or "").replace(";", " ").strip()
                description = doc.get("styledDescription") or ""
                # Strip HTML for filter
                description = re.sub(r"<[^>]+>", " ", description)

                if not is_original_banksy_print(title, description):
                    continue

                auction_id = str(doc.get("auctionId") or "")
                lot_id = str(doc.get("lotId") or doc.get("id") or "")
                if not auction_id or not lot_id:
                    continue

                slug = doc.get("slug") or ""
                lot_url = (
                    f"https://www.bonhams.com/auction/{auction_id}/lot/{lot_id}/{slug}/"
                    if slug
                    else f"https://www.bonhams.com/auction/{auction_id}/lot/{lot_id}/"
                )

                price = doc.get("price") or {}
                low = price.get("estimateLow")
                high = price.get("estimateHigh")
                if low is not None:
                    low = int(float(low))
                if high is not None:
                    high = int(float(high))
                currency = (doc.get("currency") or {}).get("iso_code") or "GBP"

                hammer = doc.get("hammerTime") or doc.get("auctionEndDate") or {}
                auction_date = parse_auction_date(hammer.get("datetime") or "")

                image = doc.get("image") or {}
                image_url = image.get("url") or ""

                lots.append(
                    make_lot(
                        lot_id=f"bonhams-{auction_id}-{lot_id}",
                        print_name=title,
                        auction_house="Bonhams",
                        auction_date=auction_date,
                        edition="",
                        low_estimate=low,
                        high_estimate=high,
                        currency=currency,
                        url=lot_url,
                        image_url=image_url,
                        source="bonhams",
                    )
                )
            except Exception as e:
                log.debug("Bonhams: document parse error: %s", e)
                continue

    except Exception as e:
        log.error("Bonhams scrape failed: %s", e)
    finally:
        if browser:
            await browser.close()

    log.info("Bonhams: scraped %d lots", len(lots))
    return lots


# ---------------------------------------------------------------------------
# Optional credential scrapers
# ---------------------------------------------------------------------------

async def _login_and_search(
    pw,
    *,
    name: str,
    email_env: str,
    password_env: str,
    login_url: str,
    search_url: str,
    source: str,
    house_default: str,
    card_selectors: str,
    id_regex: str,
    link_selector: str,
) -> list:
    email = os.environ.get(email_env)
    password = os.environ.get(password_env)
    if not email or not password:
        log.warning("%s credentials not set, skipping", name)
        return []

    lots = []
    browser = None
    try:
        browser, page = await new_browser_page(pw)
        log.info("%s: logging in...", name)
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"], input[name="email"], #email').first
        pass_input = page.locator('input[type="password"]').first
        await email_input.fill(email)
        await pass_input.fill(password)
        await page.locator('button[type="submit"], input[type="submit"]').first.click()
        await page.wait_for_timeout(5000)

        log.info("%s: searching...", name)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        cards = await page.query_selector_all(card_selectors)
        log.info("%s: found %d result cards", name, len(cards))

        for card in cards:
            try:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='lot-name'], [class*='lotName']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not is_original_banksy_print(title):
                    continue

                link_el = await card.query_selector(link_selector)
                url = ""
                lot_id = ""
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else href
                        id_match = re.search(id_regex, href)
                        lot_id = id_match.group(1) if id_match else ""
                if not lot_id:
                    continue

                img_el = await card.query_selector("img")
                image_url = ""
                if img_el:
                    image_url = await img_el.get_attribute("src") or ""

                date_el = await card.query_selector("[class*='date'], time, [class*='sale']")
                date_text = ""
                if date_el:
                    date_text = (
                        await date_el.get_attribute("datetime")
                        or (await date_el.inner_text()).strip()
                    )
                auction_date = parse_auction_date(date_text)

                est_el = await card.query_selector("[class*='estimate'], [class*='price']")
                est_text = (await est_el.inner_text()).strip() if est_el else ""
                low, high, currency = parse_estimate(est_text)

                edition_el = await card.query_selector("[class*='edition'], [class*='medium']")
                edition = (await edition_el.inner_text()).strip() if edition_el else ""

                lots.append(
                    make_lot(
                        lot_id=f"{source}-{lot_id}",
                        print_name=title,
                        auction_house=house_default,
                        auction_date=auction_date,
                        edition=edition,
                        low_estimate=low,
                        high_estimate=high,
                        currency=currency,
                        url=url,
                        image_url=image_url,
                        source=source,
                    )
                )
            except Exception as e:
                log.debug("%s: card parse error: %s", name, e)
                continue

    except Exception as e:
        log.error("%s scrape failed: %s", name, e)
    finally:
        if browser:
            await browser.close()

    log.info("%s: scraped %d lots", name, len(lots))
    return lots


async def scrape_phillips(pw) -> list:
    return await _login_and_search(
        pw,
        name="Phillips",
        email_env="PHILLIPS_EMAIL",
        password_env="PHILLIPS_PASSWORD",
        login_url="https://www.phillips.com/login",
        search_url="https://www.phillips.com/search#q=banksy&layout=list",
        source="phillips",
        house_default="Phillips",
        card_selectors="[class*='search-result'], [class*='lot-item'], .lot",
        id_regex=r"/(?:lot|detail)/(\w+)",
        link_selector="a[href*='/lot/'], a[href*='/detail/']",
    )


async def scrape_sothebys(pw) -> list:
    # Prefer buy/calendar-style search over past results where possible.
    return await _login_and_search(
        pw,
        name="Sotheby's",
        email_env="SOTHEBYS_EMAIL",
        password_env="SOTHEBYS_PASSWORD",
        login_url="https://www.sothebys.com/en/login",
        search_url="https://www.sothebys.com/en/search?query=banksy",
        source="sothebys",
        house_default="Sotheby's",
        card_selectors="[class*='SearchResult'], [class*='lot-card'], [class*='Card']",
        id_regex=r"/(?:lot|buy)/([a-zA-Z0-9-]+)",
        link_selector="a[href*='/lot/'], a[href*='/buy/']",
    )


async def scrape_christies(pw) -> list:
    return await _login_and_search(
        pw,
        name="Christie's",
        email_env="CHRISTIES_EMAIL",
        password_env="CHRISTIES_PASSWORD",
        login_url="https://www.christies.com/login",
        search_url="https://www.christies.com/search?entry=banksy&action=paging&SortBy=relevance&StartFrom=0&PageSize=60&lid=1&language=en",
        source="christies",
        house_default="Christie's",
        card_selectors="[class*='search-result'], [class*='lot-tile'], [class*='LotTile']",
        id_regex=r"/lot/(\d+)",
        link_selector="a[href*='/lot/']",
    )


async def run_all_scrapers() -> list:
    """Run all scrapers, collecting lots from each."""
    all_lots: list = []
    scrapers: list[tuple[str, Callable]] = [
        ("LiveAuctioneers", scrape_liveauctioneers),
        ("Bonhams", scrape_bonhams),
        ("Phillips", scrape_phillips),
        ("Sotheby's", scrape_sothebys),
        ("Christie's", scrape_christies),
    ]

    async with async_playwright() as pw:
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


def main(dry_run: bool = False) -> int:
    """Main entry point. Returns process exit code."""
    log.info("Banksy Print Tracker - starting scrape")

    new_lots = asyncio.run(run_all_scrapers())
    log.info("Total new lots scraped (pre-quality filter): %d", len(new_lots))
    new_lots = [lot for lot in new_lots if is_plausible_lot(lot)]
    log.info("Total new lots after quality filter: %d", len(new_lots))

    if dry_run:
        print(json.dumps(new_lots, indent=2, ensure_ascii=False))
        return 0

    existing = load_existing_data()
    merged = merge_lots(existing.get("lots", []), new_lots)

    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lots": merged,
    }
    save_data(data)
    log.info("Done. %d active lots in data file.", len(merged))

    # Non-zero if nothing found — helps surface broken scrapers in CI.
    if not new_lots:
        log.warning("No lots scraped from any source")
        return 0  # still succeed so last_updated / expiry cleanup can commit
    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(main(dry_run=dry_run))
