#!/usr/bin/env python3
"""
Dry-run test for the Banksy auction scraper.

Runs each scraper individually and prints results without writing to JSON.
Usage: python scraper/test_scraper.py [liveauctioneers|phillips|sothebys|christies]
"""

import asyncio
import json
import sys

from scrape import (
    is_original_banksy_print,
    parse_estimate,
    scrape_christies,
    scrape_liveauctioneers,
    scrape_phillips,
    scrape_sothebys,
)

from playwright.async_api import async_playwright


def test_filtering():
    """Test the is_original_banksy_print filter logic."""
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
    ]

    passed = 0
    for title, expected in cases:
        result = is_original_banksy_print(title)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            print(f"  {status}: '{title}' -> {result} (expected {expected})")
        else:
            passed += 1

    print(f"  {passed}/{len(cases)} tests passed\n")


def test_estimate_parsing():
    """Test the estimate parser."""
    print("=== Estimate Parsing Tests ===\n")

    cases = [
        ("£80,000 - £120,000", (80000, 120000, "GBP")),
        ("$50,000 - $75,000", (50000, 75000, "USD")),
        ("€10,000 - €15,000", (10000, 15000, "EUR")),
        ("Estimate on request", (None, None, "GBP")),
        ("", (None, None, "GBP")),
    ]

    passed = 0
    for text, expected in cases:
        result = parse_estimate(text)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            print(f"  {status}: '{text}' -> {result} (expected {expected})")
        else:
            passed += 1

    print(f"  {passed}/{len(cases)} tests passed\n")


async def test_scraper(name: str):
    """Run a single scraper in dry-run mode."""
    scrapers = {
        "liveauctioneers": scrape_liveauctioneers,
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
        print(json.dumps(lots, indent=2))
    else:
        print("No lots found (check credentials are set as env vars)")


def main():
    # Always run unit tests
    test_filtering()
    test_estimate_parsing()

    # If a scraper name is given, run that scraper too
    if len(sys.argv) > 1:
        name = sys.argv[1].lower()
        asyncio.run(test_scraper(name))
    else:
        print("To test a specific scraper, pass its name as an argument:")
        print("  python test_scraper.py liveauctioneers")
        print("  python test_scraper.py phillips")
        print("  python test_scraper.py sothebys")
        print("  python test_scraper.py christies")


if __name__ == "__main__":
    main()
