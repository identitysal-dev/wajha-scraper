"""
Wajha UAE Attractions Scraper
Scrapes official attraction websites for current prices, status, and offers.
Writes results to Google Sheets via the Sheets API.
Schedule: runs twice daily via GitHub Actions (8am + 8pm UAE time).
"""

import asyncio
import json
import os
import re
import traceback
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# ── GOOGLE SHEETS CONFIG ─────────────────────────────────────────────────────

SHEET_ID = os.environ["GSHEET_ID"]          # set in GitHub Actions secrets
CREDS_JSON = os.environ["GSHEET_CREDS"]     # service account JSON string

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet():
    creds_dict = json.loads(CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1


# ── ATTRACTION DEFINITIONS ───────────────────────────────────────────────────
# Each entry defines what to scrape and how to interpret results.
# scrape_type options:
#   "static"   → page renders prices in plain HTML (no JS needed)
#   "js"       → requires Playwright to fully render
#   "search"   → fall back to web search snippet
#   "manual"   → price is known/stable, just check for closed banners

ATTRACTIONS = [

    # ── DUBAI ────────────────────────────────────────────────────────────────

    {
        "id": "burj_khalifa_silver",
        "name": "Burj Khalifa At the Top (L124–125)",
        "emirate": "dubai",
        "category": "observation",
        "source_url": "https://ticket.atthetop.ae/tickets/",
        "source_label": "ticket.atthetop.ae",
        "scrape_type": "static",
        "price_selector": None,           # prices are in static HTML text
        "price_pattern": r"AED\s*([\d,]+)(?=\s*\nBook Now)",
        "closed_patterns": ["closed", "temporarily unavailable", "precautionary"],
        "offer_patterns": ["resident", "off", "free", "offer", "discount"],
    },
    {
        "id": "burj_khalifa_sky",
        "name": "Burj Khalifa At the Top SKY (L148)",
        "emirate": "dubai",
        "category": "observation",
        "source_url": "https://ticket.atthetop.ae/tickets/",
        "source_label": "ticket.atthetop.ae",
        "scrape_type": "static",
        "price_pattern": r"AED\s*([\d,]+)(?=.*?Gold|SKY)",
        "closed_patterns": ["closed", "temporarily unavailable", "precautionary"],
        "offer_patterns": ["resident", "sky", "offer"],
        "known_price": "AED 479",         # fallback if scrape fails
    },
    {
        "id": "aquaventure",
        "name": "Aquaventure World — Atlantis The Palm",
        "emirate": "dubai",
        "category": "waterpark",
        "source_url": "https://www.aquaventureworld.com",
        "source_label": "aquaventureworld.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["free", "resident", "offer", "discount", "off"],
    },
    {
        "id": "lost_chambers",
        "name": "Lost Chambers Aquarium — Atlantis",
        "emirate": "dubai",
        "category": "wildlife",
        "source_url": "https://www.atlantis.com/dubai/lost-chambers-aquarium",
        "source_label": "atlantis.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["free", "offer", "discount", "resident"],
    },
    {
        "id": "miracle_garden",
        "name": "Dubai Miracle Garden",
        "emirate": "dubai",
        "category": "nature",
        "source_url": "https://www.dubaimiraclgarden.com",
        "source_label": "dubaimiraclgarden.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "season ended", "see you next"],
        "offer_patterns": ["free", "resident", "offer", "discount"],
        "known_price": "AED 100",
    },
    {
        "id": "museum_future",
        "name": "Museum of the Future",
        "emirate": "dubai",
        "category": "cultural",
        "source_url": "https://museumofthefuture.ae/en/offer/general-offers",
        "source_label": "museumofthefuture.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily unavailable"],
        "offer_patterns": ["resident", "offer", "discount", "pioneer", "free"],
        "known_price": "AED 169",
    },
    {
        "id": "sky_views",
        "name": "Sky Views Observatory",
        "emirate": "dubai",
        "category": "observation",
        "source_url": "https://www.skyviewsdubai.com/observatory/",
        "source_label": "skyviewsdubai.com",
        "scrape_type": "static",
        "price_pattern": r"General Admission Adult[^A]*AED\s*([\d,]+)",
        "closed_patterns": ["closed", "temporarily", "precautionary"],
        "offer_patterns": ["resident", "off", "offer", "discount"],
        "known_price": "AED 89",
    },
    {
        "id": "dubai_frame",
        "name": "Dubai Frame",
        "emirate": "dubai",
        "category": "cultural",
        "source_url": "https://www.thedubaiframe.com/en/buy-tickets",
        "source_label": "thedubaiframe.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily", "precautionary"],
        "offer_patterns": ["resident", "off", "offer", "discount"],
        "known_price": "AED 50",
    },
    {
        "id": "ain_dubai",
        "name": "Ain Dubai — Bluewaters Island",
        "emirate": "dubai",
        "category": "observation",
        "source_url": "https://www.aindubai.com",
        "source_label": "aindubai.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["resident", "offer", "open"],
        "known_status": "closed",
    },
    {
        "id": "motiongate",
        "name": "Motiongate Dubai",
        "emirate": "dubai",
        "category": "themepark",
        "source_url": "https://www.motiongatedubai.com",
        "source_label": "motiongatedubai.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["open", "reopen", "offer"],
        "known_status": "closed",
    },
    {
        "id": "legoland",
        "name": "Legoland Dubai",
        "emirate": "dubai",
        "category": "themepark",
        "source_url": "https://www.legoland.com/dubai/",
        "source_label": "legoland.com/dubai",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["open", "reopen", "offer"],
        "known_status": "closed",
    },
    {
        "id": "real_madrid_world",
        "name": "Real Madrid World (fmr. Bollywood Parks)",
        "emirate": "dubai",
        "category": "themepark",
        "source_url": "https://www.dubaiparks.com",
        "source_label": "dubaiparks.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["open", "reopen"],
        "known_status": "closed",
    },
    {
        "id": "wild_wadi",
        "name": "Wild Wadi Waterpark",
        "emirate": "dubai",
        "category": "waterpark",
        "source_url": "https://www.wildwadi.com/en",
        "source_label": "wildwadi.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["resident", "offer", "discount", "off", "free"],
    },
    {
        "id": "global_village",
        "name": "Global Village",
        "emirate": "dubai",
        "category": "cultural",
        "source_url": "https://www.globalvillage.ae",
        "source_label": "globalvillage.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety", "see you"],
        "offer_patterns": ["open", "reopen", "tickets now"],
        "known_status": "closed",
    },
    {
        "id": "skydive_dubai",
        "name": "Skydive Dubai — Palm Drop Zone",
        "emirate": "dubai",
        "category": "adventure",
        "source_url": "https://www.skydivedubai.ae",
        "source_label": "skydivedubai.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["open", "reopen", "book now"],
        "known_status": "closed",
    },
    {
        "id": "dubai_aquarium",
        "name": "Dubai Aquarium & Underwater Zoo",
        "emirate": "dubai",
        "category": "wildlife",
        "source_url": "https://www.thedubaiaquarium.com/ticket/4-for-3-pass/",
        "source_label": "thedubaiaquarium.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["4 for 3", "buy 3", "resident", "off", "discount"],
        "known_price": "AED 199",
    },
    {
        "id": "dubai_safari",
        "name": "Dubai Safari Park",
        "emirate": "dubai",
        "category": "nature",
        "source_url": "https://dubaisafari.ae/tickets/",
        "source_label": "dubaisafari.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily", "safety"],
        "offer_patterns": ["open", "resident", "offer", "discount"],
        "known_status": "closed",
    },
    {
        "id": "img_worlds",
        "name": "IMG Worlds of Adventure",
        "emirate": "dubai",
        "category": "themepark",
        "source_url": "https://imgworldsadventures.com/ticket-list",
        "source_label": "imgworldsadventures.com",
        "scrape_type": "static",
        "price_pattern": r"AED\s*\*?([\d,]+\.?\d*)\*?\s*Includes VAT",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["buy 3", "get 1", "free", "ramadan", "eid", "offer"],
        "known_price": "AED 365",
    },
    {
        "id": "ski_dubai",
        "name": "Ski Dubai — Mall of the Emirates",
        "emirate": "dubai",
        "category": "adventure",
        "source_url": "https://www.skidxb.com/book-tickets",
        "source_label": "skidxb.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["resident", "twilight", "offer", "discount", "off"],
        "known_price": "AED 250",
    },
    {
        "id": "green_planet",
        "name": "Green Planet Dubai — City Walk",
        "emirate": "dubai",
        "category": "wildlife",
        "source_url": "https://www.thegreenplanetdubai.com/en/buyticket",
        "source_label": "thegreenplanetdubai.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["online", "offer", "discount", "off", "resident"],
        "known_price": "AED 140 gate / AED 110 online",
    },
    {
        "id": "al_fahidi",
        "name": "Al Fahidi Historic District",
        "emirate": "dubai",
        "category": "cultural",
        "source_url": "https://www.visitdubai.com/en/places-to-visit/al-fahidi-historical-neighbourhood",
        "source_label": "visitdubai.com",
        "scrape_type": "manual",
        "known_price": "FREE",
        "known_status": "open",
    },

    # ── ABU DHABI ─────────────────────────────────────────────────────────────

    {
        "id": "ferrari_world",
        "name": "Ferrari World Abu Dhabi",
        "emirate": "abudhabi",
        "category": "themepark",
        "source_url": "https://www.ferrariworldabudhabi.com/en/booking",
        "source_label": "ferrariworldabudhabi.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["buy 3", "get 1", "free", "resident", "off", "4 for 3"],
    },
    {
        "id": "yas_waterworld",
        "name": "Yas Waterworld",
        "emirate": "abudhabi",
        "category": "waterpark",
        "source_url": "https://www.yaswaterworld.com/en/tickets",
        "source_label": "yaswaterworld.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["buy 3", "get 1", "free", "resident", "off", "4 for 3"],
    },
    {
        "id": "warner_bros",
        "name": "Warner Bros. World Abu Dhabi",
        "emirate": "abudhabi",
        "category": "themepark",
        "source_url": "https://www.wbworldabudhabi.com/en/tickets",
        "source_label": "wbworldabudhabi.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["buy 3", "get 1", "free", "resident", "off", "4 for 3"],
    },
    {
        "id": "seaworld",
        "name": "SeaWorld Yas Island",
        "emirate": "abudhabi",
        "category": "wildlife",
        "source_url": "https://www.seaworldabudhabi.com/en/tickets",
        "source_label": "seaworldabudhabi.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "precautionary", "temporarily"],
        "offer_patterns": ["buy 3", "get 1", "free", "resident", "off", "4 for 3"],
    },
    {
        "id": "yas_multipark",
        "name": "Yas Island Multi-Park Pass",
        "emirate": "abudhabi",
        "category": "themepark",
        "source_url": "https://www.yasisland.com/en/packages-and-offers/multi-park-experience",
        "source_label": "yasisland.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "unavailable"],
        "offer_patterns": ["multi", "park", "pass", "save", "off"],
    },
    {
        "id": "louvre",
        "name": "Louvre Abu Dhabi",
        "emirate": "abudhabi",
        "category": "cultural",
        "source_url": "https://www.louvreabudhabi.ae/en/buy-ticket",
        "source_label": "louvreabudhabi.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "senior", "free", "discount", "off"],
        "known_price": "AED 70",
    },
    {
        "id": "szgm",
        "name": "Sheikh Zayed Grand Mosque",
        "emirate": "abudhabi",
        "category": "cultural",
        "source_url": "https://www.szgmc.gov.ae/en/visiting-the-mosque",
        "source_label": "szgmc.gov.ae",
        "scrape_type": "manual",
        "known_price": "FREE",
        "known_status": "open",
    },
    {
        "id": "clymb",
        "name": "Clymb Abu Dhabi",
        "emirate": "abudhabi",
        "category": "adventure",
        "source_url": "https://www.clymbabudhabi.com/tickets",
        "source_label": "clymbabudhabi.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "off", "discount", "offer"],
        "known_price": "AED 160",
    },
    {
        "id": "qasr_al_hosn",
        "name": "Qasr Al Hosn",
        "emirate": "abudhabi",
        "category": "cultural",
        "source_url": "https://www.qasralhosn.ae/en/visit",
        "source_label": "qasralhosn.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "off", "discount"],
        "known_price": "AED 30",
    },
    {
        "id": "qasr_al_watan",
        "name": "Qasr Al Watan",
        "emirate": "abudhabi",
        "category": "cultural",
        "source_url": "https://www.qasralwatan.ae/en/tickets",
        "source_label": "qasralwatan.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["senior", "fazaa", "homat", "resident", "off", "peak", "off-peak"],
    },

    # ── RAS AL KHAIMAH ────────────────────────────────────────────────────────

    {
        "id": "jebel_jais_zipline",
        "name": "Jebel Jais Flight — World's Longest Zipline",
        "emirate": "rak",
        "category": "adventure",
        "source_url": "https://www.jebeljaisflight.com/book-tickets",
        "source_label": "jebeljaisflight.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "weather", "temporarily"],
        "offer_patterns": ["free", "child", "resident", "offer", "discount", "off"],
    },
    {
        "id": "jebel_jais_ferrata",
        "name": "Jebel Jais Via Ferrata",
        "emirate": "rak",
        "category": "adventure",
        "source_url": "https://www.jebeljaisflight.com/via-ferrata",
        "source_label": "jebeljaisflight.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "weather", "temporarily"],
        "offer_patterns": ["free", "child", "resident", "offer", "discount"],
    },
    {
        "id": "iceland_waterpark",
        "name": "Iceland Water Park RAK",
        "emirate": "rak",
        "category": "waterpark",
        "source_url": "https://www.icelandwaterpark.com/buy-tickets",
        "source_label": "icelandwaterpark.com",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "off", "discount", "offer"],
        "known_price": "AED 200",
    },

    # ── SHARJAH ───────────────────────────────────────────────────────────────

    {
        "id": "sharjah_islamic_museum",
        "name": "Sharjah Museum of Islamic Civilization",
        "emirate": "sharjah",
        "category": "cultural",
        "source_url": "https://www.islamicmuseum.ae/en/visit-us",
        "source_label": "islamicmuseum.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "free", "discount"],
        "known_price": "AED 15",
    },
    {
        "id": "sharjah_art_foundation",
        "name": "Sharjah Art Foundation",
        "emirate": "sharjah",
        "category": "cultural",
        "source_url": "https://www.sharjahart.org/sharjah-art-foundation/visit",
        "source_label": "sharjahart.org",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["free", "discount", "offer"],
        "known_price": "FREE",
    },
    {
        "id": "sharjah_aquarium",
        "name": "Sharjah Aquarium",
        "emirate": "sharjah",
        "category": "wildlife",
        "source_url": "https://www.sharjahaquarium.ae/plan-your-visit/tickets",
        "source_label": "sharjahaquarium.ae",
        "scrape_type": "js",
        "closed_patterns": ["closed", "temporarily"],
        "offer_patterns": ["resident", "off", "discount"],
        "known_price": "AED 25",
    },
]


# ── SCRAPER CORE ─────────────────────────────────────────────────────────────

async def scrape_attraction(page, attraction: dict) -> dict:
    """Scrape a single attraction page and return structured result."""
    result = {
        "id": attraction["id"],
        "name": attraction["name"],
        "emirate": attraction["emirate"],
        "category": attraction["category"],
        "source_url": attraction["source_url"],
        "source_label": attraction["source_label"],
        "status": attraction.get("known_status", "open"),
        "price": attraction.get("known_price", ""),
        "offer": "",
        "closed_reason": "",
        "last_checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scrape_ok": False,
        "raw_snippet": "",
    }

    if attraction["scrape_type"] == "manual":
        result["scrape_ok"] = True
        return result

    try:
        await page.goto(attraction["source_url"], wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(3)  # allow JS to settle

        text = (await page.inner_text("body")).lower()
        result["raw_snippet"] = text[:500]
        result["scrape_ok"] = True

        # ── STATUS CHECK ──────────────────────────────────────────────────────
        closed_hits = [p for p in attraction.get("closed_patterns", []) if p in text]
        # If page has strong closure language and NO open/book-now language, mark closed
        open_signals = ["book now", "buy tickets", "add to cart", "select date",
                        "book tickets", "buy now", "purchase"]
        has_open_signal = any(s in text for s in open_signals)

        if closed_hits and not has_open_signal:
            result["status"] = "closed"
            # Extract a brief reason
            for pattern in closed_hits:
                idx = text.find(pattern)
                if idx != -1:
                    snippet = text[max(0, idx - 30):idx + 80].strip()
                    result["closed_reason"] = snippet
                    break
        elif has_open_signal:
            result["status"] = "open"

        # ── PRICE EXTRACTION ─────────────────────────────────────────────────
        if attraction.get("price_pattern"):
            raw_text = await page.inner_text("body")
            match = re.search(attraction["price_pattern"], raw_text, re.IGNORECASE | re.DOTALL)
            if match:
                price_str = match.group(1).replace(",", "")
                result["price"] = f"AED {price_str}"

        # ── OFFER EXTRACTION ─────────────────────────────────────────────────
        offer_hits = []
        for pattern in attraction.get("offer_patterns", []):
            idx = text.find(pattern)
            if idx != -1:
                snippet = text[max(0, idx - 20):idx + 100].strip()
                # clean up whitespace
                snippet = " ".join(snippet.split())
                offer_hits.append(snippet)

        if offer_hits:
            # Deduplicate and take the most informative snippet
            seen = set()
            unique = []
            for h in offer_hits:
                key = h[:40]
                if key not in seen:
                    seen.add(key)
                    unique.append(h)
            result["offer"] = " | ".join(unique[:2])  # max 2 snippets

    except PlaywrightTimeout:
        result["scrape_ok"] = False
        result["raw_snippet"] = "TIMEOUT"
    except Exception as e:
        result["scrape_ok"] = False
        result["raw_snippet"] = str(e)[:200]

    return result


async def run_all_scrapers() -> list[dict]:
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()

        for attraction in ATTRACTIONS:
            print(f"  Scraping: {attraction['name']} ...", end=" ")
            try:
                result = await scrape_attraction(page, attraction)
                status_icon = "✓" if result["scrape_ok"] else "✗"
                print(f"{status_icon} [{result['status']}] {result['price'] or '—'}")
            except Exception as e:
                result = {**attraction, "scrape_ok": False, "status": "unknown",
                          "price": "", "offer": "", "closed_reason": "",
                          "last_checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                          "raw_snippet": traceback.format_exc()[:300]}
                print(f"✗ ERROR: {e}")
            results.append(result)

        await browser.close()
    return results


# ── GOOGLE SHEETS WRITER ─────────────────────────────────────────────────────

HEADERS = [
    "id", "name", "emirate", "category",
    "status", "price", "offer", "closed_reason",
    "source_url", "source_label",
    "last_checked", "scrape_ok", "raw_snippet",
]


def write_to_sheets(results: list[dict]):
    sheet = get_sheet()

    # Write headers on first run
    existing = sheet.row_values(1)
    if existing != HEADERS:
        sheet.clear()
        sheet.append_row(HEADERS)

    # Build a map of existing rows by id so we can update in place
    all_rows = sheet.get_all_records()
    id_to_row = {row["id"]: idx + 2 for idx, row in enumerate(all_rows)}  # +2 for header

    for result in results:
        row_data = [str(result.get(h, "")) for h in HEADERS]
        if result["id"] in id_to_row:
            row_num = id_to_row[result["id"]]
            sheet.update(f"A{row_num}:{chr(64 + len(HEADERS))}{row_num}", [row_data])
        else:
            sheet.append_row(row_data)

    print(f"\n✅ Written {len(results)} rows to Google Sheets")
    print(f"   Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}")


# ── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'='*60}")
    print(f"Wajha Scraper  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    results = await run_all_scrapers()

    open_count = sum(1 for r in results if r.get("status") == "open")
    closed_count = sum(1 for r in results if r.get("status") == "closed")
    ok_count = sum(1 for r in results if r.get("scrape_ok"))

    print(f"\n{'─'*40}")
    print(f"  Scraped:  {len(results)} attractions")
    print(f"  OK:       {ok_count}")
    print(f"  Open:     {open_count}  |  Closed: {closed_count}")
    print(f"{'─'*40}\n")

    write_to_sheets(results)


if __name__ == "__main__":
    asyncio.run(main())
