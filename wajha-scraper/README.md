# Wajha — UAE Attractions Live Dashboard
## Setup Guide (30 minutes, no coding required beyond copy-paste)

---

## What you're building

```
Official attraction websites
         ↓  (twice daily, automated)
  Python scraper (GitHub Actions)
         ↓
  Google Sheets (your database)
         ↓  (on every page load)
  Dashboard HTML (your browser)
```

---

## Step 1 — Create the Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com) → create a **New spreadsheet**
2. Name it: `Wajha Attractions Data`
3. Copy the **Sheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/  ← THIS PART →  /edit
   ```
   It looks like: `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`
4. **Publish the sheet** so the dashboard can read it:
   - File → Share → Publish to web
   - Choose: **Sheet1** / **Comma-separated values (.csv)**
   - Click **Publish** → confirm → copy the URL (you don't need it, just confirm it's done)

---

## Step 2 — Create the Google Service Account (for the scraper to write)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Google Sheets API**:
   - APIs & Services → Library → search "Google Sheets API" → Enable
4. Create a Service Account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Name: `wajha-scraper` → Create and Continue → Done
5. Create a JSON key:
   - Click your new service account → Keys tab → Add Key → Create new key → **JSON**
   - A `.json` file downloads — **keep this safe**
6. Share your Google Sheet with the service account:
   - Open your sheet → Share
   - Paste the service account email (looks like `wajha-scraper@your-project.iam.gserviceaccount.com`)
   - Give it **Editor** access → Send

---

## Step 3 — Set up the GitHub repository

1. Create a new **private** GitHub repository (e.g. `wajha-scraper`)
2. Upload these files maintaining the structure:
   ```
   .github/
     workflows/
       scraper.yml
   scraper/
     scraper.py
     requirements.txt
   dashboard/
     index.html
   ```
3. Add GitHub Secrets (Settings → Secrets and variables → Actions → New repository secret):

   | Secret name   | Value |
   |---------------|-------|
   | `GSHEET_ID`   | Your Sheet ID from Step 1 |
   | `GSHEET_CREDS`| The **entire contents** of the JSON key file from Step 2 (paste the whole JSON) |

---

## Step 4 — Configure the dashboard

Open `dashboard/index.html` and find these two lines near the top of the `<script>` block:

```javascript
const SHEET_ID  = "YOUR_GOOGLE_SHEET_ID";   // ← paste your Sheet ID here
const SHEET_GID = "0";                       // ← usually 0 for the first sheet
```

Replace `YOUR_GOOGLE_SHEET_ID` with your actual Sheet ID from Step 1.

---

## Step 5 — Run the scraper for the first time

1. In your GitHub repo, go to **Actions** tab
2. Click **Wajha Attractions Scraper** → **Run workflow** → **Run workflow**
3. Wait ~5 minutes for it to complete
4. Check your Google Sheet — it should now have data in it

---

## Step 6 — Open the dashboard

Open `dashboard/index.html` in any browser. It will:
1. Fetch the live CSV from your Google Sheet
2. Build all the attraction cards from the scraped data
3. Show open/closed status, current prices, and detected offers

**That's it.** The scraper runs automatically at 8am and 8pm UAE time every day.

---

## How it updates

| Trigger | What happens |
|---------|-------------|
| 8:00 AM UAE (4:00 UTC) | Scraper runs, visits every attraction site, updates Sheet |
| 8:00 PM UAE (16:00 UTC) | Same |
| Manual trigger | GitHub Actions → Run workflow |
| Dashboard load | Fetches latest CSV from Sheet on every page open |

---

## What the scraper detects automatically

- ✅ **Open/Closed status** — reads page text for closure banners ("closed as precautionary measure", "temporarily unavailable" etc.) and cross-checks against booking/buy-now signals
- ✅ **Price changes** — extracts AED amounts from known price patterns on each page
- ✅ **New offers** — scans for offer-related keywords and captures surrounding text
- ✅ **Last checked timestamp** — every row shows when it was last verified

## What still needs human review

- Prices that only appear inside JS booking widgets (Yas parks, Qasr Al Watan etc.) — the scraper captures what it can but some widgets require authenticated sessions
- Brand-new attractions not yet in the scraper config — add them to `ATTRACTIONS` list in `scraper.py`
- FAZAA / Es'ad / Entertainer deals — these require authenticated app access

---

## Adding a new attraction

In `scraper/scraper.py`, add a new dict to the `ATTRACTIONS` list:

```python
{
    "id": "unique_id",                    # snake_case, no spaces
    "name": "Attraction Name",
    "emirate": "dubai",                   # dubai / abudhabi / rak / sharjah
    "category": "themepark",             # themepark/waterpark/cultural/adventure/observation/nature/wildlife
    "source_url": "https://official-site.com/tickets",
    "source_label": "official-site.com",
    "scrape_type": "js",                 # js / static / manual
    "closed_patterns": ["closed", "temporarily"],
    "offer_patterns": ["free", "offer", "discount", "resident"],
    "known_price": "AED 100",            # fallback if scrape can't extract price
},
```

Then commit and push — it will be scraped on the next run.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Dashboard shows "Could not load live data" | Check Sheet is published to web as CSV |
| Sheet is empty after scraper runs | Check GitHub Actions logs for errors; verify GSHEET_ID and GSHEET_CREDS secrets |
| Scraper marks everything as closed | Some sites block headless browsers — check the `raw_snippet` column in the sheet |
| Price not updating | Site may use a JS widget; the `known_price` fallback will be used instead |
