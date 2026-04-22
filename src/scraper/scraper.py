from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import CAMPAIGNS_URL, DEFAULT_MIN_CAMPAIGN_ID
from src.scraper.client import HttpClient
from src.scraper.exporter import CampaignCsvWriter, load_existing_campaign_keys
from src.scraper.parsers import (
    CampaignSeed,
    build_paginated_url,
    extract_page_number,
    extract_listing_page,
    is_not_found_campaign_page,
    parse_campaign_detail,
    should_keep_campaign,
)


@dataclass(frozen=True)
class ScrapeSummary:
    pages_visited: int
    campaigns_found: int
    campaigns_written: int
    uncertain_date_count: int
    skipped_out_of_range: int
    failed_details: int


class CampaignScraper:
    def __init__(self, client: HttpClient) -> None:
        self.client = client
        self._detail_html_cache: dict[str, str] = {}

    def _collect_listing_campaign_seeds(
        self,
        *,
        max_pages: int | None,
        existing_ids: set[str],
        existing_urls: set[str],
    ) -> tuple[list[CampaignSeed], int]:
        queue = deque([CAMPAIGNS_URL])
        visited_pages: set[str] = set()
        discovered: dict[str, CampaignSeed] = {}
        discovered_urls: set[str] = set()

        while queue and (max_pages is None or len(visited_pages) < max_pages):
            current_url = queue.popleft()
            if current_url in visited_pages:
                continue

            html = self.client.get(current_url)
            visited_pages.add(current_url)

            parsed = extract_listing_page(html, current_url)
            new_on_page = 0

            for campaign in parsed.campaigns:
                if (
                    campaign.campaign_id in existing_ids
                    or campaign.url in existing_urls
                    or campaign.campaign_id in discovered
                    or campaign.url in discovered_urls
                ):
                    continue
                discovered[campaign.campaign_id] = campaign
                discovered_urls.add(campaign.url)
                new_on_page += 1

            for next_page_url in parsed.next_page_urls:
                if next_page_url not in visited_pages:
                    queue.append(next_page_url)

            if not parsed.next_page_urls and parsed.campaigns and new_on_page > 0:
                next_page_url = build_paginated_url(
                    current_url,
                    extract_page_number(current_url) + 1,
                )
                if next_page_url not in visited_pages:
                    queue.append(next_page_url)

        ordered = sorted(discovered.values(), key=lambda campaign: int(campaign.campaign_id))
        return ordered, len(visited_pages)

    def _collect_range_campaign_seeds(
        self,
        *,
        min_campaign_id: int,
        max_campaign_id: int,
        existing_ids: set[str],
        existing_urls: set[str],
    ) -> tuple[list[CampaignSeed], int]:
        discovered: dict[str, CampaignSeed] = {}
        pages_visited = 0

        for campaign_id in range(min_campaign_id, max_campaign_id + 1):
            campaign_id_str = str(campaign_id)
            url = f"{CAMPAIGNS_URL}/{campaign_id}"

            if campaign_id_str in existing_ids or url in existing_urls:
                continue

            html = self.client.get(url)
            pages_visited += 1

            if is_not_found_campaign_page(html):
                continue

            self._detail_html_cache[url] = html
            discovered[campaign_id_str] = CampaignSeed(
                campaign_id=campaign_id_str,
                url=url,
                title="",
                subtitle="",
                image_url="",
            )

        ordered = sorted(discovered.values(), key=lambda campaign: int(campaign.campaign_id))
        return ordered, pages_visited

    def _collect_campaign_seeds(
        self,
        *,
        discovery_mode: str,
        max_pages: int | None,
        min_campaign_id: int | None,
        max_campaign_id: int | None,
        existing_ids: set[str],
        existing_urls: set[str],
    ) -> tuple[list[CampaignSeed], int]:
        collected: dict[str, CampaignSeed] = {}
        total_pages_visited = 0

        if discovery_mode in {"listing", "combined"}:
            listing_seeds, listing_pages = self._collect_listing_campaign_seeds(
                max_pages=max_pages,
                existing_ids=existing_ids,
                existing_urls=existing_urls,
            )
            total_pages_visited += listing_pages
            for seed in listing_seeds:
                collected.setdefault(seed.campaign_id, seed)

        if discovery_mode in {"id_range", "combined"}:
            if max_campaign_id is None:
                known_ids = [int(seed.campaign_id) for seed in collected.values()]
                max_campaign_id = max(known_ids, default=DEFAULT_MIN_CAMPAIGN_ID)
            min_campaign_id = min_campaign_id or DEFAULT_MIN_CAMPAIGN_ID

            range_seeds, range_pages = self._collect_range_campaign_seeds(
                min_campaign_id=min_campaign_id,
                max_campaign_id=max_campaign_id,
                existing_ids=existing_ids | set(collected.keys()),
                existing_urls=existing_urls | {seed.url for seed in collected.values()},
            )
            total_pages_visited += range_pages
            for seed in range_seeds:
                collected.setdefault(seed.campaign_id, seed)

        ordered = sorted(collected.values(), key=lambda campaign: int(campaign.campaign_id))
        return ordered, total_pages_visited

    def scrape_to_csv(
        self,
        *,
        output_path: Path,
        start_year: int | None,
        end_year: int | None,
        discovery_mode: str = "combined",
        max_pages: int | None = None,
        min_campaign_id: int | None = None,
        max_campaign_id: int | None = None,
        resume: bool = False,
    ) -> ScrapeSummary:
        existing_ids, existing_urls, _ = load_existing_campaign_keys(output_path) if resume else (set(), set(), 0)
        seeds, pages_visited = self._collect_campaign_seeds(
            discovery_mode=discovery_mode,
            max_pages=max_pages,
            min_campaign_id=min_campaign_id,
            max_campaign_id=max_campaign_id,
            existing_ids=existing_ids,
            existing_urls=existing_urls,
        )

        campaigns_written = 0
        uncertain_date_count = 0
        skipped_out_of_range = 0
        failed_details = 0

        with CampaignCsvWriter(output_path, append=resume) as writer:
            for seed in seeds:
                try:
                    html = self._detail_html_cache.pop(seed.url, None) or self.client.get(seed.url)
                    row = parse_campaign_detail(
                        html,
                        seed.url,
                        fallback_seed=seed,
                        start_year=start_year,
                        end_year=end_year,
                    )
                except Exception as exc:
                    failed_details += 1
                    print(f"[WARN] Failed to parse campaign {seed.url}: {exc}")
                    continue

                if not should_keep_campaign(row, start_year, end_year):
                    skipped_out_of_range += 1
                    continue

                row["scraped_at"] = datetime.now(timezone.utc).isoformat()
                writer.write_row(row)
                campaigns_written += 1
                if row.get("date_status") == "uncertain":
                    uncertain_date_count += 1

        return ScrapeSummary(
            pages_visited=pages_visited,
            campaigns_found=len(seeds),
            campaigns_written=campaigns_written,
            uncertain_date_count=uncertain_date_count,
            skipped_out_of_range=skipped_out_of_range,
            failed_details=failed_details,
        )
