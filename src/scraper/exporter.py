from __future__ import annotations

import csv
from pathlib import Path

CSV_HEADERS = [
    "campaign_id",
    "url",
    "title",
    "subtitle",
    "overview_text",
    "details_text",
    "required_amount_raw",
    "paid_amount_raw",
    "left_amount_raw",
    "required_amount",
    "paid_amount",
    "left_amount",
    "donations_count",
    "comments_count",
    "updates_count",
    "shares_count",
    "image_url",
    "year_detected",
    "year_source",
    "date_status",
    "scraped_at",
]


def ensure_output_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_existing_campaign_keys(path: Path) -> tuple[set[str], set[str], int]:
    campaign_ids: set[str] = set()
    urls: set[str] = set()
    row_count = 0

    if not path.exists():
        return campaign_ids, urls, row_count

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            campaign_id = (row.get("campaign_id") or "").strip()
            url = (row.get("url") or "").strip()
            if campaign_id:
                campaign_ids.add(campaign_id)
            if url:
                urls.add(url)

    return campaign_ids, urls, row_count


class CampaignCsvWriter:
    def __init__(self, output_path: Path, *, append: bool = False) -> None:
        self.output_path = output_path
        ensure_output_parent(output_path)
        file_exists = output_path.exists() and output_path.stat().st_size > 0
        mode = "a" if append else "w"
        self._handle = output_path.open(mode, encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=CSV_HEADERS)
        if not append or not file_exists:
            self._writer.writeheader()

    def write_row(self, row: dict[str, object]) -> None:
        normalized = {header: row.get(header, "") for header in CSV_HEADERS}
        self._writer.writerow(normalized)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "CampaignCsvWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

