from pathlib import Path

BASE_URL = "https://molhamteam.com"
EN_BASE_URL = f"{BASE_URL}/en"
CAMPAIGNS_PATH = "/en/campaigns"
CAMPAIGNS_URL = f"{BASE_URL}{CAMPAIGNS_PATH}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 MolhamCampaignScraper/1.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEFAULT_TIMEOUT = 20
DEFAULT_REQUEST_DELAY = 2.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.5
DEFAULT_START_YEAR = None
DEFAULT_END_YEAR = None
DEFAULT_OUTPUT_PATH = Path("data") / "campaigns_all.csv"
DEFAULT_DISCOVERY_MODE = "combined"
DEFAULT_MIN_CAMPAIGN_ID = 1
