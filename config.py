"""Central configuration for bank URLs, binding periods and settings."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "borantor.db"
EXCEL_PATH = DATA_DIR / "borantor_rapport.xlsx"
LOG_PATH = DATA_DIR / "borantor.log"

# Binding periods tracked (in months: 3m=3, 1y=12, 2y=24, 3y=36, 5y=60)
BINDING_PERIODS = {
    "3_man": "3 månader",
    "1_ar": "1 år",
    "2_ar": "2 år",
    "3_ar": "3 år",
    "5_ar": "5 år",
}

BANKS = {
    "SBAB": {
        "name": "SBAB",
        "list_rates_url": "https://www.sbab.se/1/privat/bolan/rantor.html",
        "avg_rates_url": None,
    },
    "Swedbank": {
        "name": "Swedbank",
        "list_rates_url": "https://www.swedbank.se/privat/bolan-och-bostadslan/rantor-och-villkor/aktuella-bolanerantor.html",
        "avg_rates_url": None,
    },
    "Handelsbanken": {
        "name": "Handelsbanken",
        "list_rates_url": "https://www.handelsbanken.se/sv/bolan/bolanerantor",
        "avg_rates_url": None,
    },
    "SEB": {
        "name": "SEB",
        "list_rates_url": "https://seb.se/bolan/bolanerantor",
        "avg_rates_url": None,
    },
    "Nordea": {
        "name": "Nordea",
        "list_rates_url": "https://www.nordea.se/privat/bolan/bolanerantor.html",
        "avg_rates_url": None,
    },
    "Danske Bank": {
        "name": "Danske Bank",
        "list_rates_url": "https://danskebank.se/privat/bolan/bolanerantor",
        "avg_rates_url": None,
    },
    "Länsförsäkringar": {
        "name": "Länsförsäkringar",
        "list_rates_url": "https://www.lansforsakringar.se/privat/bank/bolan/bolanerantor/",
        "avg_rates_url": None,
    },
    "Skandia": {
        "name": "Skandia",
        "list_rates_url": "https://www.skandia.se/bolan/bolanerantor/",
        "avg_rates_url": None,
    },
}

# Riksbanken API base URL (SWEA = Swedish Economic Archive)
RIKSBANK_API = "https://api.riksbank.se/swea/v1"

# Series IDs from Riksbanken's API
RIKSBANK_SERIES = {
    "policy_rate": "SECBREPOEFF",       # Riksbankens styrränta (effectiv)
    "stibor_3m": "SESTIBOR3M",          # STIBOR 3 månader
    "stibor_1w": "SESTIBOR1W",          # STIBOR 1 vecka
    "gov_bond_2y": "SEGVB2YC",          # Statsobligation 2 år
    "gov_bond_5y": "SEGVB5YC",          # Statsobligation 5 år
    "mortgage_rate_avg": "SEMORTNAVG",  # Genomsnittlig bolåneränta (om tillgänglig)
}

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Scheduler: run every day at 07:00 Swedish time
SCHEDULE_TIME = "07:00"
TIMEZONE = "Europe/Stockholm"
