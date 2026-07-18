#!/usr/bin/env python3
"""Unit tests for multi-house Banksy scraper."""

from __future__ import annotations

import sys

from scrape import (
    TRACKED_HOUSES,
    cards_to_lots,
    extract_title_from_lines,
    is_original_banksy_print,
    is_plausible,
    make_lot,
    match_house,
    merge_lots,
    parse_auction_date,
    parse_estimate,
    parse_sold_price,
)


def run_cases(name, cases, fn) -> int:
    print(f"=== {name} ===")
    failed = 0
    for inp, expected in cases:
        got = fn(inp) if not isinstance(inp, tuple) else fn(*inp)
        if got != expected:
            print(f"  FAIL: {inp!r} -> {got!r} (expected {expected!r})")
            failed += 1
    print(f"  {len(cases) - failed}/{len(cases)} passed\n")
    return failed


def main() -> int:
    failed = 0
    failed += run_cases(
        "Filter",
        [
            ("Banksy - Girl With Balloon screenprint", True),
            ("After Banksy poster", False),
            ("Banksy Dinner With Batman", False),
            ("Banksy copyright Pest Control screenprint signed", True),
            ("Banksy - Applause", True),
        ],
        is_original_banksy_print,
    )
    failed += run_cases(
        "House match",
        [
            ("Phillips London", "phillips"),
            ("Sold at Sotheby's New York", "sothebys"),
            ("Tate Ward Auctions", "tateward"),
            ("Forum Auctions", "forum"),
            ("Random Gallery", None),
        ],
        match_house,
    )
    failed += run_cases(
        "Sold price",
        [
            ("Sold for £7,500 inc.premium", (7500, "GBP")),
            ("Lot sold: 63,000 GBP", (63000, "GBP")),
            ("PRICE REALISED: £28,840", (28840, "GBP")),
            ("Sold for $50,000", (50000, "USD")),
            ("USD48260", (48260, "USD")),
            ("GBP10880", (10880, "GBP")),
            ("Passed", (None, "GBP")),
        ],
        parse_sold_price,
    )
    failed += run_cases(
        "Dates",
        [
            ("26 June 2026", "2026-06-26"),
            ("Jul 26, 2026", "2026-07-26"),
            ("2026-07-29", "2026-07-29"),
            ("1 Day Left", ""),
        ],
        parse_auction_date,
    )
    failed += run_cases(
        "Estimates",
        [
            ("Est: $600 - $800", (600, 800, "USD")),
            ("Estimated at £6,000 - £8,000", (6000, 8000, "GBP")),
            ("US$20,000 - US$30,000", (20000, 30000, "USD")),
        ],
        parse_estimate,
    )

    assert len(TRACKED_HOUSES) == 9

    lot = make_lot(
        source="phillips",
        print_name="Banksy - Applause",
        auction_house="Phillips",
        auction_date="2026-06-04",
        realised_price=28380,
        status="completed",
    )
    if not is_plausible(lot, "completed"):
        print("FAIL plausible completed phillips")
        failed += 1

    merged = merge_lots(
        [{"id": "a", "auction_date": "2099-01-01"}],
        [{"id": "b", "auction_date": "2099-06-01"}],
        mode="upcoming",
    )
    if {x["id"] for x in merged} != {"a", "b"}:
        print("FAIL merge upcoming")
        failed += 1

    # Sotheby's wishlist UI puts "save" between artist and title
    sotheby_lines = ["Banksy", "save", "Trolleys (Color)", "Estimate", "30,000 USD - 50,000 USD"]
    title = extract_title_from_lines(sotheby_lines)
    if title != "Banksy - Trolleys (Color)":
        print(f"FAIL sotheby title: {title!r}")
        failed += 1

    cards = [
        {
            "href": "https://www.sothebys.com/en/buy/auction/2023/prints-multiples-including-jasper-johns-from-the-estate-of-mark-lancaster/trolleys-color",
            "lines": sotheby_lines,
            "img": "",
        },
        {
            "href": "https://www.sothebys.com/en/buy/auction/2023/prints-multiples-4/trolleys-color",
            "lines": ["Banksy", "save", "Trolleys (Color)", "Lot sold: 35,560 USD"],
            "img": "",
        },
    ]
    parsed = cards_to_lots(cards, source="sothebys", house="Sotheby's")
    if len(parsed) < 2:
        print(f"FAIL sotheby cards_to_lots got {len(parsed)}: {parsed}")
        failed += 1
    else:
        urls = {p["url"] for p in parsed}
        if "trolleys-color" not in "".join(urls):
            print("FAIL missing trolleys url", urls)
            failed += 1
        if not any(p.get("print_name", "").lower().find("trolleys") >= 0 for p in parsed):
            print("FAIL trolleys not in titles", [p.get("print_name") for p in parsed])
            failed += 1

    if failed:
        print(f"FAILED: {failed}")
        return 1
    print("All unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
