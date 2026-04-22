from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.scraper.parsers import (
    CampaignSeed,
    build_paginated_url,
    extract_listing_page,
    is_not_found_campaign_page,
    parse_campaign_detail,
    should_keep_campaign,
)
from src.scraper.scraper import CampaignScraper


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_extract_listing_page(self) -> None:
        html = load_fixture("listing_page.html")

        parsed = extract_listing_page(html, "https://molhamteam.com/en/campaigns")

        self.assertEqual(2, len(parsed.campaigns))
        self.assertEqual("414", parsed.campaigns[0].campaign_id)
        self.assertEqual("Tenth Anniversary Campaign", parsed.campaigns[0].title)
        self.assertEqual("Build homes for displaced families", parsed.campaigns[0].subtitle)
        self.assertEqual(
            "https://molhamteam.com/images/campaign-414.jpg",
            parsed.campaigns[0].image_url,
        )
        self.assertEqual(
            [
                "https://molhamteam.com/en/campaigns?page=2",
                "https://molhamteam.com/en/campaigns?page=3",
            ],
            parsed.next_page_urls,
        )

    def test_parse_campaign_detail(self) -> None:
        html = load_fixture("detail_page.html")
        seed = CampaignSeed(
            campaign_id="414",
            url="https://molhamteam.com/en/campaigns/414",
            title="Tenth Anniversary Campaign",
            subtitle="Build homes for displaced families",
            image_url="",
        )

        row = parse_campaign_detail(
            html,
            seed.url,
            fallback_seed=seed,
            start_year=2020,
            end_year=2025,
        )

        self.assertEqual("414", row["campaign_id"])
        self.assertEqual("4000", row["required_amount_raw"])
        self.assertEqual(2500, row["paid_amount"])
        self.assertEqual(1500, row["left_amount"])
        self.assertEqual(289, row["donations_count"])
        self.assertEqual(5, row["comments_count"])
        self.assertEqual(3, row["updates_count"])
        self.assertEqual(4, row["shares_count"])
        self.assertEqual("2024", row["year_detected"])
        self.assertEqual("certain", row["date_status"])
        self.assertIn("housing campaign in 2024", str(row["overview_text"]))

    def test_parse_campaign_detail_prefers_next_data_amounts(self) -> None:
        html = """
        <html>
          <head>
            <script id="__NEXT_DATA__" type="application/json">
              {
                "props": {
                  "pageProps": {
                    "singleCase": {
                      "id": 910,
                      "required_amount": {"label": "Required", "amount": {"usd": 50000}},
                      "funding_progress_bar": {
                        "blocks": [
                          {"label": "Paid", "amount": {"usd": 2255}},
                          {"label": "Left", "amount": {"usd": 47745}}
                        ]
                      },
                      "counters": {"donations": 21, "comments": 0, "shares": 0, "updates": 0},
                      "metadata": [{"name": "publishing_date", "value": "2026-04-12"}],
                      "contents": {
                        "title": "Zakat al-Mal",
                        "body": "Structured overview from JSON"
                      }
                    }
                  }
                }
              }
            </script>
          </head>
          <body>
            <main>
              <h1>Zakat al-Mal</h1>
              <p>Required $ NaN</p>
              <p>Paid $ 0</p>
              <p>Left $ NaN</p>
            </main>
          </body>
        </html>
        """

        row = parse_campaign_detail(
            html,
            "https://molhamteam.com/en/campaigns/910",
            fallback_seed=None,
            start_year=None,
            end_year=None,
        )

        self.assertEqual("50000", row["required_amount_raw"])
        self.assertEqual("2255", row["paid_amount_raw"])
        self.assertEqual("47745", row["left_amount_raw"])
        self.assertEqual(50000, row["required_amount"])
        self.assertEqual(2255, row["paid_amount"])
        self.assertEqual(47745, row["left_amount"])
        self.assertEqual(21, row["donations_count"])
        self.assertEqual("2026", row["year_detected"])
        self.assertEqual("publishing_date", row["year_source"])

    def test_uncertain_date_is_kept(self) -> None:
        html = """
        <html>
          <body>
            <main>
              <h1>No Explicit Year</h1>
              <p>Required $ 100</p>
              <p>Paid $ 0</p>
              <p>Left $ 100</p>
              <p>Donations 1</p>
            </main>
          </body>
        </html>
        """

        row = parse_campaign_detail(
            html,
            "https://molhamteam.com/en/campaigns/999",
            fallback_seed=None,
            start_year=2020,
            end_year=2025,
        )

        self.assertEqual("uncertain", row["date_status"])
        self.assertTrue(should_keep_campaign(row, 2020, 2025))

    def test_out_of_range_year_is_skipped(self) -> None:
        html = """
        <html>
          <body>
            <main>
              <h1>Campaign 2019</h1>
              <p>Required $ 100</p>
            </main>
          </body>
        </html>
        """

        row = parse_campaign_detail(
            html,
            "https://molhamteam.com/en/campaigns/998",
            fallback_seed=None,
            start_year=2020,
            end_year=2025,
        )

        self.assertEqual("2019", row["year_detected"])
        self.assertEqual("certain", row["date_status"])
        self.assertFalse(should_keep_campaign(row, 2020, 2025))

    def test_build_paginated_url(self) -> None:
        self.assertEqual(
            "https://molhamteam.com/en/campaigns?page=4",
            build_paginated_url("https://molhamteam.com/en/campaigns?page=2", 4),
        )

    def test_keep_campaign_without_year_filter(self) -> None:
        row = {
            "year_detected": "2019",
            "date_status": "certain",
        }

        self.assertTrue(should_keep_campaign(row, None, None))

    def test_not_found_campaign_page_detection(self) -> None:
        html = """
        <html>
          <head>
            <title>Molham Volunteering Team</title>
            <link rel="canonical" href="https://molhamteam.com/en/campaigns/1500?nxtPdonate=campaigns&nxtPid=1500" />
          </head>
          <body>
            <main><h1>Error 404</h1></main>
          </body>
        </html>
        """

        self.assertTrue(is_not_found_campaign_page(html))


class CampaignScraperTests(unittest.TestCase):
    def test_scrape_to_csv_deduplicates_and_writes(self) -> None:
        listing_html = load_fixture("listing_page.html")
        detail_html = load_fixture("detail_page.html")
        empty_listing_html = load_fixture("empty_listing_page.html")

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get(self, url: str) -> str:
                self.calls.append(url)
                if url == "https://molhamteam.com/en/campaigns":
                    return listing_html
                if url == "https://molhamteam.com/en/campaigns?page=2":
                    return empty_listing_html
                if url == "https://molhamteam.com/en/campaigns?page=3":
                    return empty_listing_html
                if url == "https://molhamteam.com/en/campaigns/414":
                    return detail_html
                if url == "https://molhamteam.com/en/campaigns/529":
                    return detail_html.replace(
                        "Campaign 414",
                        "Campaign 529",
                    ).replace(
                        "Tenth Anniversary Campaign",
                        "Simple Dreams Fund",
                    )
                raise AssertionError(f"Unexpected URL: {url}")

        output_dir = Path("data") / "test_tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "campaigns.csv"
        if output_path.exists():
            output_path.unlink()

        scraper = CampaignScraper(FakeClient())
        summary = scraper.scrape_to_csv(
            output_path=output_path,
            start_year=2020,
            end_year=2025,
            discovery_mode="listing",
            max_pages=3,
            resume=False,
        )

        self.assertEqual(3, summary.pages_visited)
        self.assertEqual(2, summary.campaigns_found)
        self.assertEqual(2, summary.campaigns_written)

        with output_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(2, len(rows))
        self.assertEqual(["414", "529"], [row["campaign_id"] for row in rows])

        output_path.unlink(missing_ok=True)

    def test_scrape_to_csv_with_id_range_discovery(self) -> None:
        valid_campaign = """
        <html>
          <head><meta property="og:image" content="https://molhamteam.com/images/campaign-2.jpg" /></head>
          <body>
            <main>
              <h1>Historic Campaign</h1>
              <p>Required $ 500</p>
              <p>Paid $ 300</p>
              <p>Left $ 200</p>
              <p>Donations 42</p>
              <p>This campaign helped families long before the current listing page.</p>
            </main>
          </body>
        </html>
        """
        not_found = """
        <html>
          <head>
            <title>Molham Volunteering Team</title>
            <link rel="canonical" href="https://molhamteam.com/en/campaigns/3?nxtPdonate=campaigns&nxtPid=3" />
          </head>
          <body><main><h1>Error 404</h1></main></body>
        </html>
        """

        class FakeClient:
            def get(self, url: str) -> str:
                if url == "https://molhamteam.com/en/campaigns/1":
                    return valid_campaign.replace("Historic Campaign", "Campaign One")
                if url == "https://molhamteam.com/en/campaigns/2":
                    return valid_campaign
                if url == "https://molhamteam.com/en/campaigns/3":
                    return not_found
                raise AssertionError(f"Unexpected URL: {url}")

        output_dir = Path("data") / "test_tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "campaigns_range.csv"
        if output_path.exists():
            output_path.unlink()

        scraper = CampaignScraper(FakeClient())
        summary = scraper.scrape_to_csv(
            output_path=output_path,
            start_year=None,
            end_year=None,
            discovery_mode="id_range",
            min_campaign_id=1,
            max_campaign_id=3,
            resume=False,
        )

        self.assertEqual(3, summary.pages_visited)
        self.assertEqual(2, summary.campaigns_found)
        self.assertEqual(2, summary.campaigns_written)

        with output_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(["1", "2"], [row["campaign_id"] for row in rows])
        output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
