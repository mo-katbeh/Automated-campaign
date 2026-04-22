from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from src.config import BASE_URL

CAMPAIGN_URL_RE = re.compile(r"/en/campaigns/(?P<campaign_id>\d+)(?:/)?$")
YEAR_RE = re.compile(r"\b(20[0-9]{2})\b")
GENERIC_ANCHOR_LABELS = {"donate", "share", "details", "read more"}
NOISE_PREFIXES = (
    "required",
    "paid",
    "left",
    "donate",
    "share",
    "last updates",
    "comments",
    "donations",
    "loading",
    "molham volunteering team",
    "tap to unmute",
    "english",
    "cart",
    "sign in",
    "menu",
    "home",
    "donation & payment methods",
    "how to donate",
)
NOISE_EXACT = {
    "overview",
    "details",
    "about",
    "help",
    "faqs",
    "privacy policy",
    "terms of use",
    "contact us",
    "powered by",
}


@dataclass(frozen=True)
class CampaignSeed:
    campaign_id: str
    url: str
    title: str
    subtitle: str
    image_url: str


@dataclass(frozen=True)
class ListingParseResult:
    campaigns: list[CampaignSeed]
    next_page_urls: list[str]


def build_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def normalize_space(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def campaign_id_from_url(url: str) -> str:
    match = CAMPAIGN_URL_RE.search(urlparse(url).path.rstrip("/"))
    return match.group("campaign_id") if match else ""


def normalize_campaign_url(raw_url: str, base_url: str = BASE_URL) -> str:
    absolute = urljoin(base_url, raw_url)
    parsed = urlparse(absolute)
    clean = parsed._replace(query="", fragment="")
    return urlunparse(clean).rstrip("/")


def build_paginated_url(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page_number)]
    encoded = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=encoded))


def extract_page_number(url: str) -> int:
    page_value = parse_qs(urlparse(url).query).get("page", ["1"])[0]
    try:
        return max(1, int(page_value))
    except ValueError:
        return 1


def extract_listing_page(html: str, current_url: str) -> ListingParseResult:
    soup = build_soup(html)
    campaigns: dict[str, CampaignSeed] = {}

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        normalized_url = normalize_campaign_url(href)
        campaign_id = campaign_id_from_url(normalized_url)
        if not campaign_id:
            continue

        card = anchor
        for parent in anchor.parents:
            classes = " ".join(parent.get("class", []))
            if parent.name in {"article", "li"} or any(
                marker in classes.lower() for marker in ["campaign", "card", "item"]
            ):
                card = parent
                break

        heading = card.find(re.compile(r"^h[1-6]$"))
        title = normalize_space(heading.get_text(" ", strip=True) if heading else "")
        anchor_text = normalize_space(anchor.get_text(" ", strip=True))
        if not title and anchor_text.lower() not in GENERIC_ANCHOR_LABELS:
            title = anchor_text

        subtitle = ""
        for selector in ["h2", "h3", "h4", "h5", "h6", "p", "span"]:
            for candidate in card.select(selector):
                text = normalize_space(candidate.get_text(" ", strip=True))
                if text and text != title and not is_noise_text(text):
                    subtitle = text
                    break
            if subtitle:
                break

        image = card.find("img")
        image_url = ""
        if image:
            image_url = urljoin(BASE_URL, image.get("src") or image.get("data-src") or "")

        seed = CampaignSeed(
            campaign_id=campaign_id,
            url=normalized_url,
            title=title,
            subtitle=subtitle,
            image_url=image_url,
        )
        existing = campaigns.get(campaign_id)
        if existing is None or _seed_score(seed) > _seed_score(existing):
            campaigns[campaign_id] = seed

    next_page_urls: set[str] = set()
    current_page = extract_page_number(current_url)

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        label = normalize_space(anchor.get_text(" ", strip=True)).lower()
        absolute = urljoin(current_url, href)
        page_number = extract_page_number(absolute)
        if page_number <= current_page:
            continue

        if "page=" in href or label in {"next", "older", ">"} or label.isdigit():
            next_page_urls.add(build_paginated_url(current_url, page_number))

    return ListingParseResult(
        campaigns=sorted(campaigns.values(), key=lambda campaign: int(campaign.campaign_id)),
        next_page_urls=sorted(next_page_urls, key=extract_page_number),
    )


def extract_meta_content(soup: BeautifulSoup, *candidates: tuple[str, str]) -> str:
    for attr_name, attr_value in candidates:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return normalize_space(tag["content"])
    return ""


def extract_next_data(soup: BeautifulSoup) -> dict[str, object] | None:
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return None

    raw_json = script.string or script.get_text()
    if not raw_json:
        return None

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def is_not_found_campaign_page(html: str) -> bool:
    soup = build_soup(html)
    title = normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "")
    h1 = normalize_space(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
    canonical_tag = soup.find("link", rel="canonical")
    canonical_url = normalize_space(canonical_tag.get("href", "") if canonical_tag else "")

    if h1.lower() == "error 404":
        return True
    if title == "Molham Volunteering Team" and h1.lower() == "error 404":
        return True
    if "nxtPdonate=campaigns" in canonical_url and h1.lower() == "error 404":
        return True
    return False


def extract_label_value(raw_text: str, label: str) -> str:
    pattern = rf"{re.escape(label)}\s*[$£€]?\s*([0-9][0-9,\.]*|NaN)"
    match = re.search(pattern, raw_text, re.IGNORECASE)
    return match.group(1) if match else ""


def parse_number(raw_value: str) -> float | int | None:
    cleaned = normalize_space(raw_value).replace(",", "")
    if not cleaned or cleaned.lower() == "nan":
        return None
    if "." in cleaned:
        try:
            return float(cleaned)
        except ValueError:
            return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def extract_stat_count(raw_text: str, label: str) -> int | None:
    match = re.search(rf"{re.escape(label)}\s+(\d+)", raw_text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def extract_primary_text_blocks(soup: BeautifulSoup) -> tuple[str, str]:
    overview_text = _extract_named_section_text(soup, "overview")
    details_text = _extract_named_section_text(soup, "details")

    if overview_text or details_text:
        return overview_text, details_text

    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    meaningful_lines: list[str] = []
    seen: set[str] = set()

    for text in content_root.stripped_strings:
        normalized = normalize_space(text)
        if is_noise_text(normalized):
            continue
        if len(normalized.split()) < 5 and len(normalized) < 35:
            continue
        if normalized not in seen:
            seen.add(normalized)
            meaningful_lines.append(normalized)

    return "\n".join(meaningful_lines), ""


def _extract_named_section_text(soup: BeautifulSoup, keyword: str) -> str:
    candidates = soup.select(
        f"#{keyword}, [id*='{keyword}'], [class*='{keyword}'], [data-tab='{keyword}']"
    )
    texts: list[str] = []
    for candidate in candidates:
        for paragraph in candidate.select("p, li"):
            text = normalize_space(paragraph.get_text(" ", strip=True))
            if text and not text.startswith("Loading..."):
                texts.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if text not in seen:
            seen.add(text)
            deduped.append(text)

    return "\n".join(deduped)


def _seed_score(seed: CampaignSeed) -> int:
    score = 0
    if seed.title and seed.title.lower() not in GENERIC_ANCHOR_LABELS:
        score += 3
    if seed.subtitle:
        score += 2
    if seed.image_url:
        score += 1
    return score


def amount_to_usd_value(payload: object) -> int | float | None:
    if not isinstance(payload, dict):
        return None

    direct_usd = payload.get("usd")
    if isinstance(direct_usd, (int, float)):
        return direct_usd

    nested_amount = payload.get("amount")
    if isinstance(nested_amount, dict):
        nested_usd = nested_amount.get("usd")
        if isinstance(nested_usd, (int, float)):
            return nested_usd

    return None


def format_numeric_raw(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def extract_structured_amounts(single_case: dict[str, object]) -> tuple[str, str, str]:
    required_raw = format_numeric_raw(amount_to_usd_value(single_case.get("required_amount")))
    paid_raw = ""
    left_raw = ""

    funding_progress_bar = single_case.get("funding_progress_bar")
    if isinstance(funding_progress_bar, dict):
        blocks = funding_progress_bar.get("blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                label = normalize_space(str(block.get("label", ""))).lower()
                amount_raw = format_numeric_raw(amount_to_usd_value(block.get("amount")))
                if label == "paid":
                    paid_raw = amount_raw
                elif label == "left":
                    left_raw = amount_raw

    return required_raw, paid_raw, left_raw


def extract_structured_counters(single_case: dict[str, object]) -> tuple[int | None, int | None, int | None, int | None]:
    counters = single_case.get("counters")
    if not isinstance(counters, dict):
        return None, None, None, None

    def to_int(value: object) -> int | None:
        return value if isinstance(value, int) else None

    return (
        to_int(counters.get("donations")),
        to_int(counters.get("comments")),
        to_int(counters.get("updates")),
        to_int(counters.get("shares")),
    )


def extract_publishing_date(single_case: dict[str, object]) -> str:
    metadata = single_case.get("metadata")
    if not isinstance(metadata, list):
        return ""

    for item in metadata:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "publishing_date":
            return normalize_space(str(item.get("value", "")))

    return ""


def is_noise_text(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return True

    lower = normalized.lower()
    if lower in NOISE_EXACT or lower in GENERIC_ANCHOR_LABELS:
        return True
    if normalized.startswith("©"):
        return True
    if re.fullmatch(r"campaign\s+\d+", lower):
        return True
    if lower.startswith(("$", "£", "€", "â", "nan")):
        return True
    if not any(character.isalpha() for character in normalized) and re.search(r"[\d$£€]|nan", lower):
        return True
    return any(lower.startswith(prefix) for prefix in NOISE_PREFIXES)


def detect_year(
    *,
    start_year: int | None,
    end_year: int | None,
    title: str,
    subtitle: str,
    overview_text: str,
    details_text: str,
    meta_description: str,
    publishing_date: str,
) -> tuple[str, str, str]:
    candidates: list[tuple[str, str]] = [
        ("title", title),
        ("subtitle", subtitle),
        ("publishing_date", publishing_date),
        ("meta_description", meta_description),
        ("overview_text", overview_text),
        ("details_text", details_text),
    ]

    year_matches: list[tuple[str, int]] = []
    for source, text in candidates:
        for match in YEAR_RE.findall(text):
            year_matches.append((source, int(match)))

    unique_years = sorted({year for _, year in year_matches})
    if len(unique_years) == 1:
        year = str(unique_years[0])
        source = next(source for source, matched_year in year_matches if matched_year == unique_years[0])
        return year, source, "certain"

    if len(unique_years) > 1:
        in_range = [
            year for year in unique_years if _year_in_range(year, start_year=start_year, end_year=end_year)
        ]
        if len(in_range) == 1:
            return str(in_range[0]), "multiple_matches", "uncertain"
        return "", "multiple_matches", "uncertain"

    return "", "", "uncertain"


def parse_campaign_detail(
    html: str,
    url: str,
    *,
    fallback_seed: CampaignSeed | None = None,
    start_year: int | None,
    end_year: int | None,
) -> dict[str, object]:
    soup = build_soup(html)
    raw_text = normalize_space(soup.get_text(" ", strip=True))
    next_data = extract_next_data(soup)
    page_props = next_data.get("props", {}).get("pageProps", {}) if isinstance(next_data, dict) else {}
    single_case = page_props.get("singleCase", {}) if isinstance(page_props, dict) else {}
    if not isinstance(single_case, dict):
        single_case = {}
    contents = single_case.get("contents")
    if not isinstance(contents, dict):
        contents = {}

    title = normalize_space(
        soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    ) or normalize_space(str(contents.get("title", ""))) or (fallback_seed.title if fallback_seed else "")
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    image_url = extract_meta_content(soup, ("property", "og:image")) or (
        fallback_seed.image_url if fallback_seed else ""
    )
    overview_text, details_text = extract_primary_text_blocks(soup)
    structured_body = normalize_space(str(contents.get("body", "")))
    structured_details = normalize_space(str(contents.get("details", "")))
    if not overview_text and structured_body:
        overview_text = structured_body
    if not details_text and structured_details and structured_details != overview_text:
        details_text = structured_details

    campaign_id = campaign_id_from_url(url)
    if not campaign_id:
        campaign_id_match = re.search(r"Campaign\s+(\d+)", raw_text, re.IGNORECASE)
        campaign_id = campaign_id_match.group(1) if campaign_id_match else ""

    required_amount_raw, paid_amount_raw, left_amount_raw = extract_structured_amounts(single_case)
    if not required_amount_raw:
        required_amount_raw = extract_label_value(raw_text, "Required")
    if not paid_amount_raw:
        paid_amount_raw = extract_label_value(raw_text, "Paid")
    if not left_amount_raw:
        left_amount_raw = extract_label_value(raw_text, "Left")

    donations_count, comments_count, updates_count, shares_count = extract_structured_counters(single_case)
    if donations_count is None:
        donations_count = extract_stat_count(raw_text, "Donations")
    if comments_count is None:
        comments_count = extract_stat_count(raw_text, "Comments")
    if updates_count is None:
        updates_count = extract_stat_count(raw_text, "Last Updates")
    if shares_count is None:
        shares_count = extract_stat_count(raw_text, "Share")

    subtitle = fallback_seed.subtitle if fallback_seed else ""
    publishing_date = extract_publishing_date(single_case)
    year_detected, year_source, date_status = detect_year(
        start_year=start_year,
        end_year=end_year,
        title=title,
        subtitle=subtitle,
        overview_text=overview_text,
        details_text=details_text,
        meta_description=meta_description,
        publishing_date=publishing_date,
    )

    return {
        "campaign_id": campaign_id,
        "url": normalize_campaign_url(url),
        "title": title,
        "subtitle": subtitle,
        "overview_text": overview_text,
        "details_text": details_text,
        "required_amount_raw": required_amount_raw,
        "paid_amount_raw": paid_amount_raw,
        "left_amount_raw": left_amount_raw,
        "required_amount": parse_number(required_amount_raw),
        "paid_amount": parse_number(paid_amount_raw),
        "left_amount": parse_number(left_amount_raw),
        "donations_count": donations_count,
        "comments_count": comments_count,
        "updates_count": updates_count,
        "shares_count": shares_count,
        "image_url": image_url,
        "year_detected": year_detected,
        "year_source": year_source,
        "date_status": date_status,
    }


def should_keep_campaign(row: dict[str, object], start_year: int, end_year: int) -> bool:
    if start_year is None and end_year is None:
        return True

    year_detected = str(row.get("year_detected") or "").strip()
    date_status = str(row.get("date_status") or "").strip()
    if not year_detected:
        return date_status == "uncertain"

    year = int(year_detected)
    return _year_in_range(year, start_year=start_year, end_year=end_year)


def _year_in_range(year: int, *, start_year: int | None, end_year: int | None) -> bool:
    if start_year is not None and year < start_year:
        return False
    if end_year is not None and year > end_year:
        return False
    return True
