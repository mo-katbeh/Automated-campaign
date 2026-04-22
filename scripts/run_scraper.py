from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import (  # noqa: E402
    DEFAULT_DISCOVERY_MODE,
    DEFAULT_END_YEAR,
    DEFAULT_MIN_CAMPAIGN_ID,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_START_YEAR,
)
from src.scraper.client import HttpClient  # noqa: E402
from src.scraper.scraper import CampaignScraper  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Molham campaign data into CSV.")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument(
        "--all-years",
        action="store_true",
        help="Disable year filtering and keep every campaign reachable from the listing pages.",
    )
    parser.add_argument(
        "--discovery-mode",
        choices=["listing", "id_range", "combined"],
        default=DEFAULT_DISCOVERY_MODE,
        help="How to discover campaign URLs before scraping details.",
    )
    parser.add_argument("--min-campaign-id", type=int, default=DEFAULT_MIN_CAMPAIGN_ID)
    parser.add_argument("--max-campaign-id", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_REQUEST_DELAY)
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.all_years:
        args.start_year = None
        args.end_year = None

    client = HttpClient(delay=args.delay)
    scraper = CampaignScraper(client)

    try:
        summary = scraper.scrape_to_csv(
            output_path=args.output,
            start_year=args.start_year,
            end_year=args.end_year,
            discovery_mode=args.discovery_mode,
            max_pages=args.max_pages,
            min_campaign_id=args.min_campaign_id,
            max_campaign_id=args.max_campaign_id,
            resume=args.resume,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    finally:
        client.close()

    print(
        "Run summary: "
        f"pages_visited={summary.pages_visited}, "
        f"campaigns_found={summary.campaigns_found}, "
        f"campaigns_written={summary.campaigns_written}, "
        f"uncertain_date_count={summary.uncertain_date_count}, "
        f"skipped_out_of_range={summary.skipped_out_of_range}, "
        f"failed_details={summary.failed_details}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
