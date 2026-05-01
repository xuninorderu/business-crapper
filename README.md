# YouTuber Finder — Full Setup Guide
## From Zero to Live in 15 Minutes

---

## FILES IN THIS FOLDER

| File | Purpose |
|---|---|
| `app.py` | Flask backend (the scraper engine) |
| `requirements.txt` | Python packages list |
| `Procfile` | Tells Railway/Render how to start the app |
| `nixpacks.toml` | Tells Railway to install Chrome (for Selenium) |
| `google_sites_frontend.html` | The webpage you embed in Google Sites |

---

## STEP 1 — Upload to GitHub (free, required for deployment)

1. Go to https://github.com and create a free account
2. Click **New Repository** → name it `youtuber-scraper` → Public → Create
3. Upload all 5 files (drag and drop onto the GitHub page)
4. Click **Commit changes**

---

## STEP 2 — Deploy Backend to Railway (free, recommended)

1. Go to https://railway.app → Sign up with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `youtuber-scraper` repo
4. Railway detects Flask automatically — click **Deploy**
5. Wait ~3 minutes for build to finish
6. Go to **Settings → Networking → Generate Domain**
7. Copy your URL — looks like: `https://youtuber-scraper-production.up.railway.app`

**That URL is your backend. Copy it.**

---

## STEP 3 — Connect Frontend to Backend

1. Open `google_sites_frontend.html` in Notepad
2. Find this line near the top of the `<script>` section:
   ```
   const BACKEND_URL = "https://YOUR-APP.up.railway.app";
   ```
3. Replace it with your actual Railway URL:
   ```
   const BACKEND_URL = "https://youtuber-scraper-production.up.railway.app";
   ```
4. Save the file

---

## STEP 4 — Embed in Google Sites

1. Open your Google Site → click **Edit (pencil icon)**
2. Click **Insert** (left sidebar) → scroll down → **Embed**
3. Click the **"Embed code"** tab
4. Open `google_sites_frontend.html` in Notepad → Select All (Ctrl+A) → Copy
5. Paste into the embed box → Click **Next → Insert**
6. Resize the embed box to be tall enough (drag the bottom handle down)
7. Click **Publish** on your Google Site

---

## STEP 5 — Test It

1. Type a niche: `food vlogger`
2. Type a location: `Chittagong Bangladesh`
3. Select how many results: `10`
4. Click **Search**
5. Results appear as cards with emails, phones, social links, website buttons
6. Click **CSV** to download all data as a spreadsheet

---

## OPTIONAL — Add YouTube API Key (better results)

1. Go to https://console.cloud.google.com
2. Create project → Enable **YouTube Data API v3**
3. Create Credentials → API Key → Copy it
4. Open `app.py` → find line:
   ```python
   YT_API_KEY = ""
   ```
5. Paste your key:
   ```python
   YT_API_KEY = "AIzaSy_your_key_here"
   ```
6. Re-upload `app.py` to GitHub → Railway auto-redeploys

---

## TROUBLESHOOTING

| Problem | Fix |
|---|---|
| "Backend not configured" | Set BACKEND_URL in the HTML file |
| "CORS error" in browser | Flask-CORS is already included — redeploy |
| "No results found" | Try broader niche, or add YouTube API key |
| Railway build fails | Check logs in Railway dashboard |
| Embed too small in Google Sites | Drag the embed box taller |
| Slow results | Normal — scraping 20 channels takes ~2-3 minutes |

---

## ALTERNATIVE: Run Backend on Your PC (for testing)

```bash
# In the folder with app.py:
pip install flask flask-cors requests beautifulsoup4 selenium webdriver-manager pandas
python app.py
```

Then in the HTML file set:
```javascript
const BACKEND_URL = "http://localhost:5000";
```

Note: This only works when your PC is on. Use Railway for permanent access.
