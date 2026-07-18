#!/usr/bin/env python3
"""
Unit tests (+ optional live scraper smoke test) for the Banksy auction scraper.

Usage:
  python test_scraper.py                    # unit tests only
  python test_scraper.py liveauctioneers    # unit tests + live scraper
"""

from __future__ import annotations

import asyncio
import json
import sys

from scrape import (
    is_original_banksy_print,
    merge_lots,
    parse_auction_date,
    parse_estimate,
    scrape_bonhams,
    scrape_christies,
    scrape_liveauctioneers,
    scrape_phillips,
    scrape_sothebys,
)

from playwright.async_api import async_playwright


def test_filtering() -> int:
    """Test the is_original_banksy_print filter logic. Returns failure count."""
    print("=== Filter Logic Tests ===\n")

    cases = [
        ("Banksy - Girl With Balloon, screenprint, signed", True),
        ("Banksy - Love is in the Bin, print, numbered /25", True),
        ("Banksy - Flower Thrower, lithograph", True),
        ("After Banksy - Girl With Balloon poster", False),
        ("Banksy inspired tribute art", False),
        ("Banksy T-shirt merchandise", False),
        ("Banksy NFT collection", False),
        ("Banksy bronze sculpture", False),
        ("Banksy unsigned open edition print", False),
        ("Banksy - Laugh Now, screenprint, signed /150", True),
        ("Copy of Banksy Girl With Balloon", False),
        ("Random artist - landscape painting", False),
        # copyright must NOT be excluded (substring false positive)
        ("Banksy Girl With Balloon screenprint signed, copyright Pest Control", True),
        ("Banksy 'Bomb Love (Bomb Hugger) Print sold after", False),
        ("Banksy 'Gangsta Rat (Dark Grey)' Print after", False),
        ("Banksy acrylic painting flower thrower in the style of street art", False),
        ("Death NYC Banksy Kusama", False),
        ("Banksy (born 1974); Applause;", True),
        ("Banksy Dinner With Batman-D2, Canvas Mixed Media", False),
        ("Banksy - Dinner With Mona Lisa- D2, Limited Edition", False),
        ("Banksy acrylic on canvas painting flower thrower", False),
    ]

    failed = 0
    for title, expected in cases:
        result = is_original_banksy_print(title)
        if result != expected:
            print(f"  FAIL: '{title}' -> {result} (expected {expected})")
            failed += 1

    print(f"  {len(cases) - failed}/{len(cases)} tests passed\n")
    return failed


def test_estimate_parsing() -> int:
    print("=== Estimate Parsing Tests ===\n")

    cases = [
        ("£80,000 - £120,000", (80000, 120000, "GBP")),
        ("$50,000 - $75,000", (50000, 75000, "USD")),
        ("€10,000 - €15,000", (10000, 15000, "EUR")),
        ("Est. $1,000-$2,000", (1000, 2000, "USD")),
        ("US$20,000 - US$30,000", (20000, 30000, "USD")),
        ("Estimate on request", (None, None, "GBP")),
        ("", (None, None, "GBP")),
    ]

    failed = 0
    for text, expected in cases:
        result = parse_estimate(text)
        if result != expected:
            print(f"  FAIL: '{text}' -> {result} (expected {expected})")
            failed += 1

    print(f"  {len(cases) - failed}/{len(cases)} tests passed\n")
    return failed


def test_date_parsing() -> int:
    print("=== Date Parsing Tests ===\n")

    cases = [
        ("2026-04-15", "2026-04-15"),
        ("Jul 26, 2026", "2026-07-26"),
        ("26 Jul 2026", "2026-07-26"),
        ("July 26, 2026", "2026-07-26"),
        ("2026-07-30T06:59:59+00:00", "2026-07-30"),
        ("1 Day Left", ""),
        ("2 Hrs Left", ""),
        ("", ""),
    ]

    failed = 0
    for text, expected in cases:
        result = parse_auction_date(text)
        if result != expected:
            print(f"  FAIL: '{text}' -> {result!r} (expected {expected!r})")
            failed += 1

    print(f"  {len(cases) - failed}/{len(cases)} tests passed\n")
    return failed


def test_merge_lots() -> int:
    print("=== Merge Lots Tests ===\n")
    failed = 0

    existing = [
        {"id": "a", "auction_date": "2099-01-01", "print_name": "A"},
        {"id": "b", "auction_date": "2020-01-01", "print_name": "B"},
        {"id": "c", "auction_date": "", "print_name": "C"},
    ]
    new = [
        {"id": "d", "auction_date": "2099-06-01", "print_name": "D"},
        {"id": "c", "auction_date": "", "print_name": "C-updated"},
    ]
    merged = merge_lots(existing, new)
    ids = {lot["id"] for lot in merged}

    if "b" in ids:
        print("  FAIL: past-dated lot b should be removed")
        failed += 1
    if "a" not in ids or "d" not in ids:
        print("  FAIL: future lots a/d should remain")
        failed += 1
    if "c" not in ids:
        print("  FAIL: undated lot c re-scraped this run should remain")
        failed += 1
    # undated not in new should drop
    merged2 = merge_lots(
        [{"id": "x", "auction_date": "", "print_name": "X"}],
        [{"id": "y", "auction_date": "2099-01-01", "print_name": "Y"}],
    )
    if any(lot["id"] == "x" for lot in merged2):
        print("  FAIL: undated lot not re-scraped should drop")
        failed += 1

    if failed == 0:
        print("  2/2 tests passed\n")
    else:
        print(f"  merge tests failed: {failed}\n")
    return failed


async def test_scraper(name: str):
    scrapers = {
        "liveauctioneers": scrape_liveauctioneers,
        "bonhams": scrape_bonhams,
        "phillips": scrape_phillips,
        "sothebys": scrape_sothebys,
        "christies": scrape_christies,
    }

    fn = scrapers.get(name)
    if not fn:
        print(f"Unknown scraper: {name}")
        print(f"Available: {', '.join(scrapers.keys())}")
        return

    print(f"=== Testing {name} scraper ===\n")
    async with async_playwright() as pw:
        lots = await fn(pw)

    if lots:
        print(f"Found {len(lots)} lots:\n")
        print(json.dumps(lots, indent=2, ensure_ascii=False))
    else:
        print("No lots found (check credentials for optional scrapers)")


def main() -> int:
    failed = 0
    failed += test_filtering()
    failed += test_estimate_parsing()
    failed += test_date_parsing()
    failed += test_merge_lots()

    if len(sys.argv) > 1:
        name = sys.argv[1].lower()
        asyncio.run(test_scraper(name))
    else:
        print("To test a specific scraper, pass its name as an argument:")
        print("  python test_scraper.py liveauctioneers")
        print("  python test_scraper.py bonhams")
        print("  python test_scraper.py phillips")
        print("  python test_scraper.py sothebys")
        print("  python test_scraper.py christies")

    if failed:
        print(f"FAILED: {failed} unit test(s)")
        return 1
    print("All unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
