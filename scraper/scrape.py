#!/usr/bin/env python3
"""
Banksy Print Tracker – scrape upcoming + completed lots from target houses:

  Bonhams, Christie's, Forum Auctions, Heritage Auctions, Koller Auctions,
  Phillips, Roseberys, Sotheby's, Tate Ward

Writes:
  docs/data/upcoming.json  + data/upcoming.json
  docs/data/completed.json + data/completed.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
DOCS_DATA = REPO / "docs" / "data"
MIRROR = REPO / "data"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Canonical house keys + display names
TRACKED_HOUSES = {
    "bonhams": "Bonhams",
    "christies": "Christie's",
    "forum": "Forum Auctions",
    "heritage": "Heritage Auctions",
    "koller": "Koller Auctions",
    "phillips": "Phillips",
    "roseberys": "Roseberys",
    "sothebys": "Sotheby's",
    "tateward": "Tate Ward",
}

# Match free-text house names from aggregators
HOUSE_ALIASES = {
    "bonhams": ["bonhams"],
    "christies": ["christie's", "christies", "christie"],
    "forum": ["forum auctions", "forum auction"],
    "heritage": ["heritage auctions", "heritage"],
    "koller": ["koller"],
    "phillips": ["phillips"],
    "roseberys": ["roseberys", "rosebery"],
    "sothebys": ["sotheby's", "sothebys", "sotheby"],
    "tateward": ["tate ward", "tateward"],
}

KNOWN_PRINTS = [
    "girl with balloon", "love is in the bin", "flower thrower", "thrower",
    "laugh now", "pulp fiction", "jack and jill", "soup can", "kate moss",
    "kate (colored)", "kate", "choose your weapon", "queue jumpers", "grannies",
    "happy choppers", "happy chopper", "morons", "di-faced tenner", "barcode",
    "bomb hugger", "bomb love", "bombing middle england", "bomb middle england",
    "flag", "golf sale", "grin reaper", "have a nice day", "heavy weaponry",
    "i fought the law", "kissing coppers", "napalm", "nola", "rude copper",
    "sale ends", "stop and search", "toxic mary", "trolleys", "very little helps",
    "weston super mare", "wrong war", "gangsta rat", "monkey queen", "donuts",
    "applause", "cnd soldiers", "flying copper", "love rat", "no ball games",
    "welcome to hell", "queen vic", "queen victoria", "hmv", "hmv dog",
    "love is in the air", "because i'm worthless", "banksquiat",
    "christ with shopping bags", "smiling copper", "bullet hole", "lenin",
    "festival", "soup cans", "radar rat", "get out while you can",
    "mickey snake", "3d rat", "rat with scalpel", "barely legal", "met ball",
    "kids on guns", "brick handbag", "any person found", "crude oil",
    "people who enjoy waving flags", "axe", "monkey detonator", "record",
    "sunflowers", "season's greetings", "brace yourself", "bad meaning good",
    "forgive us our trespassing", "mean and vicious", "monkey parliament",
    "shopping trolleys", "trolley hunters", "sale ends", "nola",
]

EXCLUDE_PHRASES = [
    "after banksy", "inspired by", "in the style of", "style of banksy",
    "style of street", "unsigned open edition", "reproduction", "poster only",
    "merchandise", "t-shirt", "phone case", "death nyc", "print after",
    "print sold after", "sold after", "attributed to", "school of",
    "homage to", "tribute to", "dinner with", "dinner alone", "mixed media",
    "acrylic on canvas", "painting on stretched canvas", "hand painted",
    "hand-painted", "oil on canvas", "buy it now", "buy now", "museum guard",
    "charlie brown", "caveman fast food", "mona lisa ak",
]

# Word-boundary excludes for untrusted secondary-market scrapes only.
# Do NOT use these to reject banksy-value / major-house completed catalogues
# (originals and editions both appear there).
EXCLUDE_WORDS = [
    "copy", "tribute", "nft", "figurine", "mug", "tshirt", "hoodie",
]

PRINT_INDICATORS = [
    "print", "screenprint", "screen print", "lithograph", "giclée", "giclee",
    "signed", "numbered", "edition", "work on paper", "silkscreen", "editions",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_original_banksy_print(title: str, description: str = "") -> bool:
    text = f"{title} {description}".lower()
    if "banksy" not in text:
        return False
    for p in EXCLUDE_PHRASES:
        if p in text:
            return False
    for w in EXCLUDE_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return False
    has_print = any(i in text for i in PRINT_INDICATORS)
    has_known = any(k in text for k in KNOWN_PRINTS)
    return has_print or has_known


def has_known_title(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in KNOWN_PRINTS)


def match_house(text: str) -> Optional[str]:
    """Return tracked house key if text mentions one of our houses."""
    t = text.lower()
    for key, aliases in HOUSE_ALIASES.items():
        for a in aliases:
            if a in t:
                return key
    return None


def parse_estimate(text: str) -> tuple:
    if not text:
        return None, None, "GBP"
    text = text.strip()
    currency = "GBP"
    if "HK$" in text or "HKD" in text:
        currency = "HKD"
    elif "US$" in text or ("USD" in text.upper() and "£" not in text):
        currency = "USD"
    elif "$" in text and "£" not in text and "HK" not in text:
        currency = "USD"
    elif "€" in text or "EUR" in text:
        currency = "EUR"
    elif "CHF" in text:
        currency = "CHF"
    elif "£" in text or "GBP" in text:
        currency = "GBP"

    nums = []
    for n in re.findall(r"[\d,]+(?:\.\d+)?", text):
        try:
            nums.append(int(float(n.replace(",", ""))))
        except ValueError:
            pass
    if len(nums) >= 2:
        return min(nums), max(nums), currency
    if len(nums) == 1:
        return nums[0], None, currency
    return None, None, currency


def parse_sold_price(text: str) -> tuple:
    """Parse hammer/realised text. Returns (amount|None, currency)."""
    if not text:
        return None, "GBP"
    raw = text.strip()
    if re.search(r"\bpass(ed)?\b", raw, re.I):
        return None, "GBP"

    # banksy-value style: USD48260 / GBP10880 / EUR323750 (no space or symbol)
    m = re.match(r"^(USD|GBP|EUR|CHF|HKD)\s*([\d,]+(?:\.\d+)?)\s*$", raw, re.I)
    if m:
        try:
            return int(float(m.group(2).replace(",", ""))), m.group(1).upper()
        except ValueError:
            pass

    # Range that is really an estimate, not a hammer (e.g. GBP60000-80000)
    m = re.match(
        r"^(USD|GBP|EUR|CHF|HKD)\s*([\d,]+)\s*[-–—]\s*([\d,]+)\s*$",
        raw,
        re.I,
    )
    if m:
        # Not a single realised price
        return None, m.group(1).upper()

    # Sold for £7,500 / Lot sold: 63,000 GBP / PRICE REALISED: £28,840
    patterns = [
        r"(?:sold\s+for|lot\s+sold|price\s+realised|price\s+realized|realised|realized)\s*[: ]*\s*(US\$|HK\$|£|€|\$|CHF)?\s*([\d,]+(?:\.\d+)?)\s*(GBP|USD|EUR|CHF|HKD)?",
        r"(US\$|HK\$|£|€|\$)\s*([\d,]+(?:\.\d+)?)",
        r"\b(USD|GBP|EUR|CHF|HKD)\s*([\d,]+(?:\.\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if not m:
            continue
        groups = m.groups()
        sym = (groups[0] or "").upper() if groups[0] else ""
        amount_s = groups[1]
        code = (groups[2] or "").upper() if len(groups) > 2 and groups[2] else ""
        try:
            amount = int(float(amount_s.replace(",", "")))
        except (ValueError, AttributeError):
            continue
        if code in ("GBP", "USD", "EUR", "CHF", "HKD"):
            cur = code
        elif sym in ("£",):
            cur = "GBP"
        elif sym in ("$", "US$", "USD"):
            cur = "USD"
        elif sym in ("€", "EUR"):
            cur = "EUR"
        elif "HK" in sym:
            cur = "HKD"
        elif "CHF" in sym:
            cur = "CHF"
        elif sym == "GBP":
            cur = "GBP"
        else:
            cur = "GBP"
        return amount, cur
    return None, "GBP"


def parse_dd_mm_yyyy(date_text: str) -> str:
    """Parse DD/MM/YYYY (banksy-value) → YYYY-MM-DD."""
    if not date_text:
        return ""
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", date_text.strip())
    if not m:
        return ""
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def normalize_house_name(name: str) -> str:
    """Map free-text house labels to our display names."""
    key = match_house(name or "")
    if key:
        return TRACKED_HOUSES[key]
    # banksy-value sometimes omits apostrophes
    cleaned = (name or "").strip()
    aliases = {
        "sothebys": "Sotheby's",
        "christies": "Christie's",
        "heritage auctions": "Heritage Auctions",
        "forum auctions": "Forum Auctions",
        "tate ward": "Tate Ward",
        "koller auctions": "Koller Auctions",
    }
    return aliases.get(cleaned.lower(), cleaned or "Unknown")


def parse_auction_date(date_text: str) -> str:
    if not date_text:
        return ""
    text = " ".join(str(date_text).strip().split())
    if re.search(r"\b(day|days|hr|hrs|hour|hours|left|ends in|live today)\b", text, re.I):
        if not re.search(r"\d{4}", text):
            return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    cleaned = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
    candidates = [cleaned]
    for rx in (
        r"([A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ):
        m = re.search(rx, cleaned)
        if m:
            candidates.append(m.group(1))
    for candidate in candidates:
        for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return ""


def stable_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def make_lot(
    *,
    source: str,
    print_name: str,
    auction_house: str,
    auction_date: str = "",
    edition: str = "",
    low_estimate: Optional[int] = None,
    high_estimate: Optional[int] = None,
    realised_price: Optional[int] = None,
    currency: str = "GBP",
    url: str = "",
    image_url: str = "",
    status: str = "upcoming",
    lot_id: Optional[str] = None,
) -> dict:
    if not lot_id:
        lot_id = f"{source}-{stable_id(url or print_name, auction_date)}"
    return {
        "id": lot_id,
        "print_name": print_name.strip(),
        "auction_house": auction_house,
        "auction_date": auction_date,
        "edition": edition or "",
        "low_estimate": low_estimate,
        "high_estimate": high_estimate,
        "realised_price": realised_price,
        "currency": currency or "GBP",
        "url": url,
        "image_url": image_url or "",
        "source": source,
        "status": status,
        "is_original": True,
    }


def is_plausible(lot: dict, mode: str) -> bool:
    title = (lot.get("print_name") or "").strip()
    title_l = title.lower()
    source = lot.get("source") or ""
    if any(x in title_l for x in ("dinner with", "dinner alone", "death nyc", "buy it now")):
        return False
    # Reject nav/department junk and bare artist labels
    if re.match(r"^banksy\.?$", title_l):
        return False
    if len(title) < 8:
        return False
    if re.search(r"books and manuscripts|departments|modern & contemporary art and editions", title_l):
        return False
    if "save" == title_l or title_l.startswith("auctions |"):
        return False

    major = source in TRACKED_HOUSES or match_house(lot.get("auction_house") or "") in TRACKED_HOUSES

    if mode == "completed":
        # banksy-value is already curated — trust it wholesale
        if source == "banksyvalue":
            return bool(title) and len(title) >= 2
        price = lot.get("realised_price")
        if price and price > 0:
            if major or source in TRACKED_HOUSES:
                return has_known_title(title) or len(title) > 8
            return has_known_title(title) and price >= 1000
        # Major houses sometimes hide hammer behind login; still list known prints
        # when we have an estimate and a past sale signal.
        if (major or source in TRACKED_HOUSES) and has_known_title(title):
            if lot.get("low_estimate") or lot.get("high_estimate"):
                return True
        return False

    # upcoming: prefer known titles or real estimates from major houses
    if has_known_title(title):
        return True
    if (source in TRACKED_HOUSES or major) and lot.get("low_estimate"):
        return True
    return False


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read %s", path)
    return {"last_updated": None, "lots": []}


def save_pair(name: str, data: dict) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for base in (DOCS_DATA, MIRROR):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        log.info("Saved %d lots → %s", len(data.get("lots", [])), path)


def merge_lots(existing: list, new: list, *, mode: str) -> list:
    by_id = {lot["id"]: lot for lot in existing if lot.get("id")}
    for lot in new:
        if lot.get("id"):
            by_id[lot["id"]] = lot

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_ids = {n.get("id") for n in new}
    active = []
    for lot in by_id.values():
        date = (lot.get("auction_date") or "").strip()
        if mode == "upcoming":
            if not date:
                if lot.get("id") in new_ids:
                    active.append(lot)
                continue
            if date >= today:
                active.append(lot)
        else:
            if not date:
                if lot.get("id") in new_ids:
                    active.append(lot)
                continue
            if date <= today:
                active.append(lot)

    if mode == "upcoming":
        active.sort(key=lambda x: x.get("auction_date") or "9999")
    else:
        active.sort(key=lambda x: x.get("auction_date") or "0000", reverse=True)
    return active


async def new_page(pw):
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT, locale="en-GB")
    page = await context.new_page()
    return browser, page


async def scroll(page, n=5, dy=2800, pause=600):
    for _ in range(n):
        await page.mouse.wheel(0, dy)
        await page.wait_for_timeout(pause)


EXTRACT_CARDS_JS = """
() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href.split('?')[0];
    const label = ((a.innerText || '') + ' ' + (a.getAttribute('aria-label') || '')).trim();
    if (!/banksy/i.test(label + ' ' + href)) continue;
    if (href.length > 220 || href.endsWith('#')) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    let el = a;
    for (let i = 0; i < 7 && el.parentElement; i++) {
      el = el.parentElement;
      const t = el.innerText || '';
      if (t.length > 40 && t.length < 1000) break;
    }
    const lines = (el.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 14);
    if (lines.join(' ').length < 12) continue;
    const img = el.querySelector('img');
    out.push({
      href,
      lines,
      img: img ? (img.currentSrc || img.src || '') : ''
    });
    if (out.length >= 80) break;
  }
  return out;
}
"""


def extract_title_from_lines(lines: list) -> str:
    """
    Build a print title from card lines.

    Sotheby's search cards look like:
      ['Banksy', 'save', 'Trolleys (Color)', 'Estimate', '30,000 USD - 50,000 USD']
    The intervening 'save' (wishlist UI) previously made us keep title='Banksy' only,
    which then failed the authenticity filter.
    """
    if not lines:
        return ""

    ui_only = re.compile(
        r"^(save|saved|estimate|est\.?|lot sold.*|sold for.*|lot closed|log in.*|"
        r"follow|share|bid|login|register|view results.*)$",
        re.I,
    )
    moneyish = re.compile(
        r"(usd|gbp|eur|chf|hkd|estimate|\d{1,3}(?:,\d{3})+|\£|\$|€)",
        re.I,
    )

    banksy_i = next(
        (i for i, line in enumerate(lines) if re.search(r"\bbanksy\b", line, re.I)),
        None,
    )
    if banksy_i is None:
        return lines[0]

    # Prefer a following line that looks like a work title (skip UI chrome).
    for j in range(banksy_i + 1, len(lines)):
        line = (lines[j] or "").strip()
        if not line or len(line) < 2:
            continue
        if ui_only.match(line):
            continue
        # Pure price lines
        if moneyish.search(line) and not re.search(r"[A-Za-z]{3,}", re.sub(r"banksy", "", line, flags=re.I)):
            continue
        if re.match(r"^banksy\.?$", line, re.I):
            continue
        artist = lines[banksy_i].strip()
        if re.match(r"^banksy\.?$", artist, re.I):
            return f"Banksy - {line}"
        if re.search(r"\bbanksy\b", line, re.I):
            return line
        return f"Banksy - {line}"

    # Fallback: artist line may already include the title
    return lines[banksy_i].strip()


def date_from_url(href: str) -> str:
    """Sotheby's etc. embed sale year in the path: /auction/2023/..."""
    if not href:
        return ""
    m = re.search(r"/auction/(\d{4})/", href)
    if m:
        # Year-only; use mid-year so it sorts into that year on completed.
        return f"{m.group(1)}-06-15"
    m = re.search(r"/(20\d{2})/", href)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2100:
            return f"{year}-06-15"
    return ""


def cards_to_lots(
    cards: list,
    *,
    source: str,
    house: str,
    prefer_completed: bool = False,
) -> list:
    lots = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for card in cards:
        lines = card.get("lines") or []
        blob = " ".join(lines)
        href = card.get("href") or ""
        if not re.search(r"banksy", blob + " " + href, re.I):
            continue

        title = extract_title_from_lines(lines)
        if not title:
            title = lines[0] if lines else ""
        if not is_original_banksy_print(title, blob):
            continue

        sold_line = next(
            (l for l in lines if re.search(r"sold|realised|realized|lot sold", l, re.I)),
            "",
        )
        realised, sold_cur = parse_sold_price(sold_line or blob)

        # Estimate may be on the line after "Estimate"
        est_line = ""
        for i, line in enumerate(lines):
            if re.search(r"estimate|est\.|estimated", line, re.I):
                est_line = line
                if i + 1 < len(lines) and re.search(r"\d", lines[i + 1]):
                    est_line = lines[i + 1]
                break
        if not est_line:
            est_line = next(
                (
                    l
                    for l in lines
                    if re.search(r"£|\$|€|USD|GBP", l) and not re.search(r"sold", l, re.I)
                ),
                "",
            )
        low, high, est_cur = parse_estimate(est_line)

        date = ""
        for line in lines:
            d = parse_auction_date(line)
            if d:
                date = d
                break
        if not date:
            m = re.search(
                r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})",
                blob,
            )
            if m:
                date = parse_auction_date(m.group(1))
        if not date:
            date = date_from_url(href)

        currency = sold_cur if realised else est_cur

        lot_closed = bool(re.search(r"lot closed|lot sold|sold for|price realised|price realized", blob, re.I))
        is_sold = bool(realised) or lot_closed
        # Past-year URLs are completed even when hammer is login-gated.
        url_year = re.search(r"/auction/(20\d{2})/", href)
        past_by_url = bool(url_year and int(url_year.group(1)) < int(today[:4]))

        if prefer_completed or is_sold or past_by_url:
            status = "completed"
            if date and date > today and not is_sold and not past_by_url:
                status = "upcoming"
        else:
            status = "upcoming"
            if date and date < today:
                status = "completed"

        lot = make_lot(
            source=source,
            print_name=title,
            auction_house=house,
            auction_date=date,
            low_estimate=low,
            high_estimate=high,
            realised_price=realised if status == "completed" else None,
            currency=currency,
            url=href,
            image_url=card.get("img") or "",
            status=status,
            lot_id=f"{source}-{stable_id(href)}",
        )
        # Keep closed major-house lots even when hammer is hidden ("Log in to view results")
        if status == "completed" and not lot.get("realised_price"):
            if (
                source in TRACKED_HOUSES
                and has_known_title(title)
                and (lot.get("low_estimate") or lot_closed or past_by_url)
            ):
                lots.append(lot)
                continue
        if is_plausible(lot, status):
            lots.append(lot)
    return lots


async def scrape_url_cards(pw, url: str, *, source: str, house: str, prefer_completed=False, scrolls=5) -> list:
    browser = None
    try:
        browser, page = await new_page(pw)
        log.info("%s: %s", source, url)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        # cookie banners
        for label in ("Accept", "Got it", "OK", "I Agree", "Accept all"):
            try:
                await page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=1200)
                await page.wait_for_timeout(500)
                break
            except Exception:
                pass
        await scroll(page, n=scrolls)
        cards = await page.evaluate(EXTRACT_CARDS_JS)
        log.info("%s: %d raw cards", source, len(cards))
        return cards_to_lots(cards, source=source, house=house, prefer_completed=prefer_completed)
    except Exception as e:
        log.error("%s scrape failed (%s): %s", source, url, e)
        return []
    finally:
        if browser:
            await browser.close()


# ---------------------------------------------------------------------------
# House-specific scrapers
# ---------------------------------------------------------------------------

async def scrape_bonhams(pw) -> tuple[list, list]:
    upcoming, completed = [], []
    browser = None
    try:
        browser, page = await new_page(pw)

        async def collect(past: bool) -> list:
            docs = []
            active = {"on": True}

            async def on_resp(resp):
                if not active["on"] or "multi_search" not in resp.url or resp.status != 200:
                    return
                try:
                    data = await resp.json()
                    for hit in data.get("results", [{}])[0].get("hits", []):
                        if hit.get("document"):
                            docs.append(hit["document"])
                except Exception:
                    pass

            page.on("response", on_resp)
            try:
                await page.goto(
                    "https://www.bonhams.com/search/?q=banksy&main_index_key=lot",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await page.wait_for_timeout(5000)
                if past:
                    for label in ("PAST LOTS", "Past lots"):
                        try:
                            await page.get_by_text(label, exact=False).first.click(timeout=2500)
                            await page.wait_for_timeout(5000)
                            break
                        except Exception:
                            continue
            finally:
                active["on"] = False
            return docs

        for past, bucket, status in ((False, upcoming, "upcoming"), (True, completed, "completed")):
            docs = await collect(past)
            seen = set()
            for doc in docs:
                did = doc.get("id")
                if did in seen:
                    continue
                seen.add(did)
                title = (doc.get("title") or "").replace(";", " ").strip()
                desc = re.sub(r"<[^>]+>", " ", doc.get("styledDescription") or "")
                if not is_original_banksy_print(title, desc):
                    continue
                auction_id = str(doc.get("auctionId") or "")
                lot_no = str(doc.get("lotId") or "")
                if not auction_id or not lot_no:
                    continue
                slug = doc.get("slug") or ""
                url = f"https://www.bonhams.com/auction/{auction_id}/lot/{lot_no}/{slug}/"
                price = doc.get("price") or {}
                low = price.get("estimateLow")
                high = price.get("estimateHigh")
                hammer = price.get("hammerPrice")
                low = int(float(low)) if low is not None else None
                high = int(float(high)) if high is not None else None
                realised = int(float(hammer)) if hammer else None
                if realised == 0:
                    realised = None
                currency = (doc.get("currency") or {}).get("iso_code") or "GBP"
                ht = doc.get("hammerTime") or doc.get("auctionEndDate") or {}
                date = parse_auction_date(ht.get("datetime") or "")
                image = (doc.get("image") or {}).get("url") or ""
                lot = make_lot(
                    source="bonhams",
                    print_name=title,
                    auction_house="Bonhams",
                    auction_date=date,
                    low_estimate=low,
                    high_estimate=high,
                    realised_price=realised if status == "completed" else None,
                    currency=currency,
                    url=url,
                    image_url=image,
                    status=status,
                    lot_id=f"bonhams-{auction_id}-{lot_no}",
                )
                if is_plausible(lot, status):
                    if status == "completed" and not lot.get("realised_price"):
                        continue
                    bucket.append(lot)
            log.info("Bonhams %s: %d", status, len(bucket))
    except Exception as e:
        log.error("Bonhams failed: %s", e)
    finally:
        if browser:
            await browser.close()
    return upcoming, completed


async def scrape_phillips(pw) -> tuple[list, list]:
    upcoming, completed = [], []
    for page_num in range(1, 5):
        url = (
            "https://www.phillips.com/search?search=banksy"
            if page_num == 1
            else f"https://www.phillips.com/search?search=banksy&page={page_num}"
        )
        lots = await scrape_url_cards(
            pw, url, source="phillips", house="Phillips", prefer_completed=False, scrolls=3
        )
        for lot in lots:
            if lot["status"] == "completed":
                completed.append(lot)
            else:
                upcoming.append(lot)
    log.info("Phillips: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_sothebys(pw) -> tuple[list, list]:
    up = await scrape_url_cards(
        pw,
        "https://www.sothebys.com/en/search?query=banksy",
        source="sothebys",
        house="Sotheby's",
        scrolls=6,
    )
    upcoming = [l for l in up if l["status"] == "upcoming"]
    completed = [l for l in up if l["status"] == "completed"]
    # also try past filter if UI supports it via URL
    past = await scrape_url_cards(
        pw,
        "https://www.sothebys.com/en/search?query=banksy&pfilters.dateRange=past",
        source="sothebys",
        house="Sotheby's",
        prefer_completed=True,
        scrolls=4,
    )
    completed.extend(past)
    log.info("Sotheby's: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_tateward(pw) -> tuple[list, list]:
    lots = await scrape_url_cards(
        pw,
        "https://www.tateward.com/?s=banksy",
        source="tateward",
        house="Tate Ward",
        prefer_completed=True,
        scrolls=4,
    )
    # search pages often return realised; also try live/upcoming auction index
    more = await scrape_url_cards(
        pw,
        "https://www.tateward.com/auctions/",
        source="tateward",
        house="Tate Ward",
        scrolls=3,
    )
    all_lots = lots + more
    upcoming = [l for l in all_lots if l["status"] == "upcoming"]
    completed = [l for l in all_lots if l["status"] == "completed"]
    log.info("Tate Ward: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_roseberys(pw) -> tuple[list, list]:
    lots = []
    for url in (
        "https://www.roseberys.co.uk/?s=banksy",
        "https://www.roseberys.co.uk/departments/prints-and-multiples",
    ):
        lots.extend(
            await scrape_url_cards(
                pw, url, source="roseberys", house="Roseberys", prefer_completed=True, scrolls=3
            )
        )
    upcoming = [l for l in lots if l["status"] == "upcoming"]
    completed = [l for l in lots if l["status"] == "completed"]
    log.info("Roseberys: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_forum(pw) -> tuple[list, list]:
    lots = []
    for url in (
        "https://www.forumauctions.co.uk/departments/banksy",
        "https://www.forumauctions.co.uk/index.php?option=com_auction&task=search&searchword=Banksy",
        "https://www.forumauctions.co.uk/Departments/Modern-and-Contemporary-Art-and-Editions",
    ):
        lots.extend(
            await scrape_url_cards(
                pw, url, source="forum", house="Forum Auctions", scrolls=4
            )
        )
    upcoming = [l for l in lots if l["status"] == "upcoming"]
    completed = [l for l in lots if l["status"] == "completed"]
    log.info("Forum: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_christies(pw) -> tuple[list, list]:
    # Christie's is heavily bot-protected; try a few URLs with short timeouts
    lots = []
    for url in (
        "https://www.christies.com/en/results?keyword=Banksy",
        "https://www.christies.com/en/search?entry=banksy",
    ):
        browser = None
        try:
            browser, page = await new_page(pw)
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(5000)
            await scroll(page, n=3)
            cards = await page.evaluate(EXTRACT_CARDS_JS)
            lots.extend(cards_to_lots(cards, source="christies", house="Christie's"))
        except Exception as e:
            log.warning("Christie's %s: %s", url, e)
        finally:
            if browser:
                await browser.close()
    upcoming = [l for l in lots if l["status"] == "upcoming"]
    completed = [l for l in lots if l["status"] == "completed"]
    log.info("Christie's: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_heritage(pw) -> tuple[list, list]:
    lots = []
    for url in (
        "https://fineart.ha.com/c/search-results.zx?Ntt=banksy&Nty=1",
        "https://www.ha.com/c/search-results.zx?Ntt=banksy+print&Nty=1",
    ):
        lots.extend(
            await scrape_url_cards(
                pw, url, source="heritage", house="Heritage Auctions", scrolls=3
            )
        )
    upcoming = [l for l in lots if l["status"] == "upcoming"]
    completed = [l for l in lots if l["status"] == "completed"]
    log.info("Heritage: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_koller(pw) -> tuple[list, list]:
    lots = []
    for url in (
        "https://www.kollerauktionen.ch/en/search/?q=banksy",
        "https://www.kollerauktionen.ch/en/?s=banksy",
    ):
        browser = None
        try:
            browser, page = await new_page(pw)
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(4000)
            await scroll(page, n=3)
            cards = await page.evaluate(EXTRACT_CARDS_JS)
            lots.extend(cards_to_lots(cards, source="koller", house="Koller Auctions"))
        except Exception as e:
            log.warning("Koller %s: %s", url, e)
        finally:
            if browser:
                await browser.close()
    upcoming = [l for l in lots if l["status"] == "upcoming"]
    completed = [l for l in lots if l["status"] == "completed"]
    log.info("Koller: %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_invaluable_filtered(pw) -> tuple[list, list]:
    """Aggregator: keep lots only from TRACKED_HOUSES."""
    lots = await scrape_url_cards(
        pw,
        "https://www.invaluable.com/search?keyword=banksy",
        source="invaluable",
        house="Unknown",
        scrolls=6,
    )
    upcoming, completed = [], []
    for lot in lots:
        house_key = match_house(lot.get("auction_house") or "") or match_house(
            " ".join([lot.get("print_name") or "", lot.get("url") or ""])
        )
        # Invaluable cards put house in lines; re-parse from print blob via auction_house field
        # cards_to_lots set auction_house to "Unknown" — fix from known patterns in url/name
        blob = f"{lot.get('print_name','')} {lot.get('auction_house','')} {lot.get('url','')}"
        # re-extract house from raw is hard; use card lines stored? We only have auction_house.
        # For invaluable, auction_house often appears as title context — improve by re-scraping
        # with house detection inside cards_to_lots for invaluable specifically.
        if house_key:
            lot["auction_house"] = TRACKED_HOUSES[house_key]
            lot["source"] = house_key
            lot["id"] = f"{house_key}-inv-{stable_id(lot.get('url',''))}"
            if lot["status"] == "completed":
                completed.append(lot)
            else:
                upcoming.append(lot)
    log.info("Invaluable (filtered): %d upcoming, %d completed", len(upcoming), len(completed))
    return upcoming, completed


async def scrape_invaluable(pw) -> tuple[list, list]:
    """Invaluable with proper house extraction from card lines."""
    browser = None
    upcoming, completed = [], []
    try:
        browser, page = await new_page(pw)
        await page.goto(
            "https://www.invaluable.com/search?keyword=banksy",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await page.wait_for_timeout(4000)
        await scroll(page, n=8)
        cards = await page.evaluate(EXTRACT_CARDS_JS)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for card in cards:
            lines = card.get("lines") or []
            blob = " ".join(lines)
            house_key = match_house(blob)
            if not house_key:
                continue
            house = TRACKED_HOUSES[house_key]
            title = next((l for l in lines if re.search(r"banksy", l, re.I)), "")
            if not title or not is_original_banksy_print(title, blob):
                continue
            if not has_known_title(title) and house_key not in (
                "phillips", "sothebys", "christies", "bonhams", "forum", "tateward", "roseberys", "heritage", "koller",
            ):
                continue
            # For secondary-looking estimates on major houses only
            est_line = next((l for l in lines if re.search(r"Est|Estimate|£|\$", l, re.I)), "")
            low, high, cur = parse_estimate(est_line)
            sold_line = next((l for l in lines if re.search(r"sold", l, re.I)), "")
            realised, scur = parse_sold_price(sold_line)
            date = ""
            for line in lines:
                d = parse_auction_date(line)
                if d:
                    date = d
                    break
            # "Jul 28, 11:00 AM EDT" without year — skip yearless
            status = "completed" if realised else "upcoming"
            if date and date < today and not realised:
                status = "completed"
            lot = make_lot(
                source=house_key,
                print_name=title,
                auction_house=house,
                auction_date=date,
                low_estimate=low,
                high_estimate=high,
                realised_price=realised,
                currency=scur if realised else cur,
                url=card.get("href") or "",
                image_url=card.get("img") or "",
                status=status,
                lot_id=f"{house_key}-inv-{stable_id(card.get('href',''))}",
            )
            if is_plausible(lot, status):
                if status == "upcoming":
                    upcoming.append(lot)
                else:
                    completed.append(lot)
        log.info("Invaluable: %d upcoming, %d completed (tracked houses)", len(upcoming), len(completed))
    except Exception as e:
        log.error("Invaluable failed: %s", e)
    finally:
        if browser:
            await browser.close()
    return upcoming, completed


async def scrape_liveauctioneers(pw) -> tuple[list, list]:
    """LA as aggregator for tracked houses + known print titles."""
    browser = None
    upcoming = []
    try:
        browser, page = await new_page(pw)
        urls = [
            "https://www.liveauctioneers.com/c/art/creator/banksy/",
            "https://www.liveauctioneers.com/search/?keyword=banksy&status=open",
        ]
        seen = set()
        for url in urls:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(5000)
                await scroll(page, n=8)
            except Exception as e:
                log.warning("LA %s: %s", url, e)
                continue
            cards = await page.evaluate(
                """() => {
                  const out=[], seen=new Set();
                  for (const a of document.querySelectorAll("a[href*='/item/']")) {
                    const m = a.href.match(/\\/item\\/(\\d+)/);
                    if (!m || seen.has(m[1])) continue;
                    seen.add(m[1]);
                    let el=a;
                    for (let i=0;i<10&&el.parentElement;i++){
                      el=el.parentElement;
                      const t=el.innerText||'';
                      if (t.length>40 && t.length<900 && /Est\\.|\\$|£|€/i.test(t)) break;
                    }
                    const lines=(el.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
                    const img=el.querySelector('img');
                    out.push({id:m[1], href:a.href.split('?')[0], lines, img: img?(img.currentSrc||img.src||''):''});
                  }
                  return out;
                }"""
            )
            for card in cards:
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                lines = card.get("lines") or []
                blob = " ".join(lines)
                title = next((l for l in lines if re.search(r"banksy", l, re.I)), "")
                if not title or not is_original_banksy_print(title, blob):
                    continue
                house_key = match_house(blob)
                house = TRACKED_HOUSES.get(house_key, "") if house_key else ""
                # Keep if tracked house OR known major print title with decent estimate
                est = next((l for l in lines if re.search(r"Est", l, re.I)), "")
                low, high, cur = parse_estimate(est)
                if not house_key:
                    if not has_known_title(title):
                        continue
                    if low is not None and low < 2000:
                        continue
                    house = next(
                        (l for l in reversed(lines) if len(l) > 3 and not re.search(r"Est|bid|\$|£", l, re.I)),
                        "Unknown",
                    )
                    source = "liveauctioneers"
                else:
                    source = house_key
                    house = TRACKED_HOUSES[house_key]

                date = ""
                for line in lines:
                    d = parse_auction_date(line)
                    if d:
                        date = d
                        break
                lot = make_lot(
                    source=source,
                    print_name=title,
                    auction_house=house,
                    auction_date=date,
                    low_estimate=low,
                    high_estimate=high,
                    currency=cur,
                    url=card["href"] if card["href"].startswith("http") else f"https://www.liveauctioneers.com{card['href']}",
                    image_url=card.get("img") or "",
                    status="upcoming",
                    lot_id=f"liveauctioneers-{card['id']}",
                )
                if is_plausible(lot, "upcoming"):
                    upcoming.append(lot)
        log.info("LiveAuctioneers: %d upcoming", len(upcoming))
    except Exception as e:
        log.error("LiveAuctioneers failed: %s", e)
    finally:
        if browser:
            await browser.close()
    return upcoming, []


# ---------------------------------------------------------------------------
# banksy-value.com realised results (best completed coverage)
# ---------------------------------------------------------------------------

async def scrape_banksy_value_completed(pw) -> tuple[list, list]:
    """
    Parse https://www.banksy-value.com/realised.php

    This is the densest public catalogue of Banksy print (and original) results.
    We treat it as a curated feed so filters stay permissive.
    """
    completed: list = []
    browser = None
    try:
        browser, page = await new_page(pw)
        url = "https://www.banksy-value.com/realised.php"
        log.info("banksy-value: %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        for _ in range(18):
            await page.mouse.wheel(0, 4500)
            await page.wait_for_timeout(200)

        rows = await page.evaluate(
            """() => {
              const out = [];
              for (const tr of document.querySelectorAll('table tr')) {
                const cells = [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim());
                if (cells.length < 5) continue;
                // Print name | Auction | Date | Edition | Sold for | Comments
                out.push({
                  print_name: cells[0],
                  auction_house: cells[1],
                  date: cells[2],
                  edition: cells[3],
                  sold: cells[4],
                  comments: cells[5] || ''
                });
              }
              return out;
            }"""
        )
        log.info("banksy-value: %d table rows", len(rows))

        for row in rows:
            name = (row.get("print_name") or "").strip()
            if not name or name.lower() in ("print name", "prints"):
                continue
            house_raw = (row.get("auction_house") or "").strip()
            house = normalize_house_name(house_raw)
            # Prefer our tracked houses, but keep other named houses from the feed
            if not house or house.lower() in ("auction", "auction house"):
                continue

            date = parse_dd_mm_yyyy(row.get("date") or "")
            if not date:
                date = parse_auction_date(row.get("date") or "")

            sold_text = (row.get("sold") or "").strip()
            realised, currency = parse_sold_price(sold_text)
            low = high = None
            # Estimate-style ranges in the sold column
            m = re.match(
                r"^(USD|GBP|EUR|CHF|HKD)\s*([\d,]+)\s*[-–—]\s*([\d,]+)\s*$",
                sold_text,
                re.I,
            )
            if m and realised is None:
                currency = m.group(1).upper()
                low = int(m.group(2).replace(",", ""))
                high = int(m.group(3).replace(",", ""))

            edition = (row.get("edition") or "").strip()
            comments = (row.get("comments") or "").strip()
            if comments and edition:
                edition = f"{edition}, {comments}" if comments not in edition else edition
            elif comments:
                edition = comments

            # Passed lots: still record with null realised so history is complete
            is_passed = bool(re.search(r"\bpass(ed)?\b", sold_text, re.I))

            print_name = name if re.search(r"banksy", name, re.I) else f"Banksy - {name}"

            lot = make_lot(
                source="banksyvalue",
                print_name=print_name,
                auction_house=house,
                auction_date=date,
                edition=edition,
                low_estimate=low,
                high_estimate=high,
                realised_price=None if is_passed else realised,
                currency=currency,
                url="https://www.banksy-value.com/realised.php",
                image_url="",
                status="completed",
                lot_id=f"bv-{stable_id(house, date, name, sold_text, comments)}",
            )
            # Keep sold, estimate-only, and passed lots from this curated feed
            if is_passed or lot.get("realised_price") or lot.get("low_estimate") or is_plausible(lot, "completed"):
                completed.append(lot)

        log.info("banksy-value: %d completed lots", len(completed))
    except Exception as e:
        log.error("banksy-value scrape failed: %s", e)
    finally:
        if browser:
            await browser.close()
    return [], completed


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_all() -> tuple[list, list]:
    upcoming: list = []
    completed: list = []

    scrapers = [
        # densest completed feed first
        ("banksy-value realised", scrape_banksy_value_completed),
        ("Bonhams", scrape_bonhams),
        ("Phillips", scrape_phillips),
        ("Sotheby's", scrape_sothebys),
        ("Tate Ward", scrape_tateward),
        ("Roseberys", scrape_roseberys),
        ("Forum Auctions", scrape_forum),
        ("Christie's", scrape_christies),
        ("Heritage Auctions", scrape_heritage),
        ("Koller Auctions", scrape_koller),
        ("Invaluable (tracked houses)", scrape_invaluable),
        ("LiveAuctioneers", scrape_liveauctioneers),
    ]

    async with async_playwright() as pw:
        for name, fn in scrapers:
            try:
                log.info("=== %s ===", name)
                up, done = await fn(pw)
                upcoming.extend(up)
                completed.extend(done)
                log.info("%s done: +%d upcoming, +%d completed", name, len(up), len(done))
            except Exception as e:
                log.error("%s crashed: %s", name, e)

    return upcoming, completed


def dedupe(lots: list) -> list:
    by_id = {}
    for lot in lots:
        by_id[lot["id"]] = lot
    return list(by_id.values())


def main(dry_run: bool = False) -> int:
    log.info("Starting multi-house scrape for: %s", ", ".join(TRACKED_HOUSES.values()))
    new_up, new_done = asyncio.run(run_all())
    new_up = dedupe(new_up)
    new_done = dedupe(new_done)
    log.info("Raw totals: %d upcoming, %d completed", len(new_up), len(new_done))

    if dry_run:
        print(json.dumps({"upcoming": new_up, "completed": new_done}, indent=2, ensure_ascii=False))
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    existing_up = load_json(DOCS_DATA / "upcoming.json")
    if not existing_up.get("lots"):
        existing_up = load_json(MIRROR / "upcoming.json")
    merged_up = merge_lots(existing_up.get("lots", []), new_up, mode="upcoming")
    save_pair("upcoming.json", {"last_updated": now, "lots": merged_up})

    existing_done = load_json(DOCS_DATA / "completed.json")
    if not existing_done.get("lots"):
        existing_done = load_json(MIRROR / "completed.json")
    merged_done = merge_lots(existing_done.get("lots", []), new_done, mode="completed")
    # Keep a deep history (banksy-value alone is 250+ rows)
    merged_done = merged_done[:2500]
    save_pair("completed.json", {"last_updated": now, "lots": merged_done})

    # 2025 coverage snapshot
    y2025 = [l for l in merged_done if (l.get("auction_date") or "").startswith("2025")]
    log.info("2025 completed lots: %d", len(y2025))

    # House coverage report
    houses_up = {}
    houses_done = {}
    for lot in merged_up:
        h = lot.get("auction_house") or "?"
        houses_up[h] = houses_up.get(h, 0) + 1
    for lot in merged_done:
        h = lot.get("auction_house") or "?"
        houses_done[h] = houses_done.get(h, 0) + 1
    log.info("Upcoming by house: %s", houses_up)
    log.info("Completed by house: %s", houses_done)
    log.info("Final: %d upcoming, %d completed", len(merged_up), len(merged_done))
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
