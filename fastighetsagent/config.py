from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "fastigheter.db"
DB_GZ_PATH = DATA_DIR / "fastigheter.db.gz"
LOG_PATH = DATA_DIR / "fastigheter.log"

CLAUDE_MODEL = "claude-opus-4-8"

SOURCES = {
    "fastighetsnytt": {
        "name": "Fastighetsnytt",
        "base_url": "https://www.fastighetsnytt.se",
        "paths": ["/affarer/", "/nyheter/transaktioner/"],
        "enabled": True,
    },
    "fastighetsvarlden": {
        "name": "Fastighetsvärlden",
        "base_url": "https://www.fastighetsvarlden.se",
        "paths": ["/affarer/", "/nyheter/"],
        "enabled": True,
    },
    "brandt_media": {
        "name": "Brandt Media",
        "base_url": "https://www.brandtmedia.se",
        "paths": ["/nyheter/", "/transaktioner/"],
        "enabled": True,
    },
    "di_fastighet": {
        "name": "DI Fastighet",
        "base_url": "https://www.di.se",
        "paths": ["/fastigheter/"],
        "enabled": True,
    },
}

PROPERTY_TYPES = [
    "Kontor", "Handel", "Logistik", "Bostäder", "Hotell",
    "Industri", "Samhällsfastighet", "Blandat", "Mark", "Övrigt",
]

DEAL_KEYWORDS = [
    "förvärvar", "förvärv", "säljer",
    "köper", "köp", "affär", "transaktion",
    "fastighetsaffär", "portfölj", "avyttrar",
    "överlåter", "tillträder", "tillträde",
]

SCHEDULE_TIME = "07:30"
TIMEZONE = "Europe/Stockholm"
REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

DATA_DIR.mkdir(exist_ok=True)
