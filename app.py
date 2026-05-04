"""
YouTube SEO Intelligence Tool — Flask Backend
Bulletproof, multi-layer scraping with deep channel + website analysis.
Deploy to Railway. Set YT_API_KEY env var or paste directly below.
"""

import os, re, time, random, json, urllib.parse
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from bs4 import BeautifulSoup

app = Flask(__name__)

# ── CORS (required for Google Sites / any external embed) ────────────────────
CORS(app, origins="*", methods=["GET","POST","OPTIONS"],
     allow_headers=["Content-Type","Authorization"])

@app.after_request
def cors_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

# ── API Keys — set as Railway env vars OR paste here ────────────────────────
YT_API_KEY     = os.environ.get("YT_API_KEY", "")        # YouTube Data API v3
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")    # hunter.io  (optional)

YT_API_BASE    = "https://www.googleapis.com/youtube/v3"

# ── HTTP helpers ─────────────────────────────────────────────────────────────
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def hdrs():
    return {"User-Agent": random.choice(UA_LIST),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

def safe_get(url, timeout=12, params=None):
    try:
        time.sleep(random.uniform(0.5, 1.2))
        r = requests.get(url, headers=hdrs(), timeout=timeout,
                         params=params, allow_redirects=True)
        if r.status_code == 200:
            return r
        print(f"  HTTP {r.status_code} → {url[:80]}")
    except Exception as e:
        print(f"  GET error: {e} → {url[:80]}")
    return None

def yt_api(endpoint, params):
    """Call YouTube Data API v3."""
    if not YT_API_KEY:
        return None
    params["key"] = YT_API_KEY
    r = safe_get(f"{YT_API_BASE}/{endpoint}", params=params)
    if r:
        return r.json()
    return None

# ═════════════════════════════════════════════════════════════════════════════
# LAYER 1 — YouTube API: Search
# ═════════════════════════════════════════════════════════════════════════════

def yt_search(keyword, location, max_results=25, order="relevance"):
    """
    Search YouTube for channels matching keyword + location.
    Returns list of channel IDs.
    """
    channel_ids = []
    query = f"{keyword} {location}".strip()

    # --- Search for channels directly ---
    data = yt_api("search", {
        "part": "snippet",
        "q": query,
        "type": "channel",
        "maxResults": min(max_results, 50),
        "order": order,
    })
    if data:
        for item in data.get("items", []):
            cid = item.get("snippet", {}).get("channelId") or \
                  item.get("id", {}).get("channelId")
            if cid and cid not in channel_ids:
                channel_ids.append(cid)

    # --- Also search videos → extract channel IDs ---
    if len(channel_ids) < max_results:
        data2 = yt_api("search", {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max_results, 50),
            "order": order,
        })
        if data2:
            for item in data2.get("items", []):
                cid = item.get("snippet", {}).get("channelId")
                if cid and cid not in channel_ids:
                    channel_ids.append(cid)

    print(f"  YT API search → {len(channel_ids)} channel IDs")
    return channel_ids[:max_results]


def yt_scrape_search(keyword, location, max_results=25):
    """
    Fallback: scrape YouTube search page for channel IDs (no API key needed).
    """
    channel_ids = []
    query = urllib.parse.quote(f"{keyword} {location}")
    url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%3D%3D"  # filter=channel
    r = safe_get(url)
    if not r:
        # also try video search
        url2 = f"https://www.youtube.com/results?search_query={query}"
        r = safe_get(url2)
    if r:
        # Extract channel IDs from page source
        ids = re.findall(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', r.text)
        for cid in ids:
            if cid not in channel_ids:
                channel_ids.append(cid)
        # Also grab /channel/ paths
        ids2 = re.findall(r'/channel/(UC[a-zA-Z0-9_-]{22})', r.text)
        for cid in ids2:
            if cid not in channel_ids:
                channel_ids.append(cid)
    print(f"  Scrape search → {len(channel_ids)} channel IDs")
    return list(dict.fromkeys(channel_ids))[:max_results]


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 2 — YouTube API: Full Channel Details
# ═════════════════════════════════════════════════════════════════════════════

def yt_channel_details(channel_ids):
    """
    Fetch full channel details for up to 50 IDs in one API call.
    Returns list of enriched channel dicts.
    """
    if not channel_ids:
        return []

    results = []
    # API allows max 50 per request
    for batch_start in range(0, len(channel_ids), 50):
        batch = channel_ids[batch_start:batch_start+50]
        data = yt_api("channels", {
            "part": "snippet,statistics,brandingSettings,contentDetails,topicDetails,localizations",
            "id": ",".join(batch),
            "maxResults": 50,
        })
        if not data:
            continue
        for item in data.get("items", []):
            snippet  = item.get("snippet", {})
            stats    = item.get("statistics", {})
            branding = item.get("brandingSettings", {}).get("channel", {})
            topics   = item.get("topicDetails", {}).get("topicCategories", [])

            channel = {
                "channel_id":      item.get("id", ""),
                "channel_name":    snippet.get("title", ""),
                "channel_url":     f"https://www.youtube.com/channel/{item.get('id','')}",
                "custom_url":      snippet.get("customUrl", ""),
                "country":         snippet.get("country", ""),
                "language":        snippet.get("defaultLanguage", ""),
                "description":     snippet.get("description", "")[:600],
                "published_at":    snippet.get("publishedAt", "")[:10],
                "thumbnail":       snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                # Stats
                "subscribers":     stats.get("subscriberCount", "0"),
                "total_views":     stats.get("viewCount", "0"),
                "video_count":     stats.get("videoCount", "0"),
                "hidden_subs":     stats.get("hiddenSubscriberCount", False),
                # Branding
                "keywords":        branding.get("keywords", ""),
                "trailer_url":     branding.get("unsubscribedTrailer", ""),
                # Topics
                "topics":          [t.split("/wiki/")[-1].replace("_"," ") for t in topics],
                # Contact — filled by deep scrape
                "website":         branding.get("unsubscribedTrailer","") and "" or "",
                "email":           "",
                "phone":           "",
                "facebook":        "",
                "instagram":       "",
                "twitter":         "",
                "tiktok":          "",
                "linkedin":        "",
                "other_links":     [],
                "key_people":      [],
                "business_email":  "",
            }

            # Custom URL → proper handle URL
            if channel["custom_url"]:
                handle = channel["custom_url"]
                if not handle.startswith("@"):
                    handle = "@" + handle.lstrip("@")
                channel["handle_url"] = f"https://www.youtube.com/{handle}"
            else:
                channel["handle_url"] = channel["channel_url"]

            results.append(channel)

    return results


def yt_channel_scrape(channel_id):
    """
    Scrape /about page for website + email + social links.
    Works without API key.
    """
    data = {"website": "", "email": "", "links": []}
    url = f"https://www.youtube.com/channel/{channel_id}/about"
    r = safe_get(url)
    if not r:
        return data

    text = r.text

    # Website
    websites = re.findall(r'"url"\s*:\s*"(https?://(?!(?:www\.)?youtube\.com)[^"]+)"', text)
    for w in websites:
        if not any(x in w for x in ["google.", "gstatic.", "ytimg.", "ggpht."]):
            data["website"] = w
            data["links"].append(w)
            break

    # All external links from about page
    all_links = re.findall(r'q=(https?://[^&"]+)', text)
    for lnk in all_links:
        decoded = urllib.parse.unquote(lnk)
        if not any(x in decoded for x in ["youtube.", "google.", "gstatic."]):
            if decoded not in data["links"]:
                data["links"].append(decoded)

    # Email from description (sometimes present in raw JSON)
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    for e in emails:
        if not any(x in e.lower() for x in ["youtube", "google", "example", "test"]):
            data["email"] = e
            break

    return data


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Deep Website Scraper
# ═════════════════════════════════════════════════════════════════════════════

EMAIL_RE    = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE    = re.compile(r"(\+?[\d][\d\s\-().]{6,}[\d])")

SOCIAL_RE = {
    "facebook":  re.compile(r"https?://(?:www\.)?facebook\.com/(?!sharer)[^\s\"'<>/][^\s\"'<>]*"),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>?#]+"),
    "twitter":   re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?!intent|share)[^\s\"'<>?#]+"),
    "tiktok":    re.compile(r"https?://(?:www\.)?tiktok\.com/@[^\s\"'<>?#]+"),
    "linkedin":  re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[^\s\"'<>?#]+"),
}

CONTACT_SUBPAGES = [
    "", "/contact", "/contact-us", "/about", "/about-us",
    "/team", "/people", "/staff", "/leadership", "/get-in-touch",
    "/work-with-us", "/collaborate", "/business",
]

TEAM_SELECTORS = [
    "[class*='team']", "[class*='person']", "[class*='staff']",
    "[class*='member']", "[class*='founder']", "[class*='executive']",
    "[class*='leadership']", "[class*='bio']",
]

def clean_email(e):
    e = e.strip(".,;:\"'()")
    parts = e.split("@")
    if len(parts) != 2:
        return None
    if not re.search(r"\.[a-zA-Z]{2,}$", parts[1]):
        return None
    bad = ["example","domain","email@","test@","noreply","no-reply",
           "yourname","youremail","info@example","user@","name@"]
    if any(b in e.lower() for b in bad):
        return None
    return e

def clean_phone(p):
    digits = re.sub(r"\D", "", p)
    if not (7 <= len(digits) <= 15):
        return None
    return p.strip()

def extract_socials_from_html(html):
    found = {}
    for platform, pattern in SOCIAL_RE.items():
        m = pattern.search(html)
        if m:
            url = m.group(0).rstrip("\"'/>\\")
            # Skip generic/share pages
            if any(x in url for x in ["/sharer", "/share?", "intent/tweet",
                                        "facebook.com/home", "twitter.com/home"]):
                continue
            found[platform] = url
    return found

def extract_people_from_soup(soup):
    people = []
    for sel in TEAM_SELECTORS:
        for card in soup.select(sel)[:12]:
            name_el  = card.select_one("h1,h2,h3,h4,strong,[class*='name']")
            role_el  = card.select_one("p,span,[class*='title'],[class*='role'],[class*='position'],[class*='job']")
            email_el = card.select_one("a[href^='mailto:']")
            li_el    = card.select_one("a[href*='linkedin.com']")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not (3 < len(name) < 60):
                continue
            p = {
                "name":     name,
                "role":     role_el.get_text(strip=True)[:80] if role_el else "",
                "email":    email_el["href"].replace("mailto:","").split("?")[0] if email_el else "",
                "linkedin": li_el["href"] if li_el else "",
            }
            if p not in people:
                people.append(p)
    return people[:6]

def scrape_website_deep(url):
    """
    Visit homepage + contact/about/team subpages.
    Returns emails, phones, socials, people, description.
    """
    if not url or not url.startswith("http"):
        return {}

    base = url.rstrip("/")
    result = {
        "emails": [], "phones": [], "people": [],
        "facebook":"", "instagram":"", "twitter":"",
        "tiktok":"", "linkedin":"", "description":"",
    }
    visited = set()

    pages = [base] + [base + p for p in CONTACT_SUBPAGES[1:]]

    scraped = 0
    for page in pages:
        if page in visited or scraped >= 4:
            continue
        visited.add(page)
        r = safe_get(page)
        if not r:
            continue
        scraped += 1

        html = r.text
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script","style","noscript","svg"]):
            tag.decompose()
        text = soup.get_text(separator=" ")

        # Emails via mailto:
        for a in soup.select("a[href^='mailto:']"):
            e = a["href"].replace("mailto:","").split("?")[0].strip()
            ce = clean_email(e)
            if ce and ce not in result["emails"]:
                result["emails"].append(ce)

        # Emails via regex
        for e in EMAIL_RE.findall(text):
            ce = clean_email(e)
            if ce and ce not in result["emails"]:
                result["emails"].append(ce)

        # Phones via tel:
        for a in soup.select("a[href^='tel:']"):
            p = a["href"].replace("tel:","").strip()
            cp = clean_phone(p)
            if cp and cp not in result["phones"]:
                result["phones"].append(cp)

        # Phones via regex
        for m in PHONE_RE.findall(text):
            cp = clean_phone(m)
            if cp and cp not in result["phones"]:
                result["phones"].append(cp)

        # Socials
        s = extract_socials_from_html(html)
        for plat, link in s.items():
            if not result[plat]:
                result[plat] = link

        # People
        if not result["people"]:
            result["people"] = extract_people_from_soup(soup)

        # Meta description
        if not result["description"]:
            for sel in ["meta[name='description']","meta[property='og:description']"]:
                m = soup.select_one(sel)
                if m and m.get("content"):
                    result["description"] = m["content"][:400]
                    break

    # Hunter.io fallback
    if not result["emails"] and HUNTER_API_KEY:
        try:
            domain = re.sub(r"https?://(www\.)?","", base).split("/")[0]
            hr = requests.get(
                f"https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 5},
                timeout=8
            )
            for em in hr.json().get("data",{}).get("emails",[]):
                val = em.get("value","")
                if val and val not in result["emails"]:
                    result["emails"].append(val)
                    fn = em.get("first_name",""); ln = em.get("last_name","")
                    if fn or ln:
                        result["people"].append({
                            "name": f"{fn} {ln}".strip(),
                            "role": em.get("position",""),
                            "email": val, "linkedin": "",
                        })
        except Exception:
            pass

    return result


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Enrich: merge API + scrape + website data
# ═════════════════════════════════════════════════════════════════════════════

def enrich_channel(channel):
    """Merge YouTube /about scrape + website deep scrape into channel dict."""
    cid = channel["channel_id"]

    # Scrape YouTube /about page for website + links
    about = yt_channel_scrape(cid)

    if about["website"]:
        channel["website"] = about["website"]
    if about["email"] and not channel["email"]:
        channel["email"] = about["email"]

    # Classify links from about page into socials
    for lnk in about.get("links", []):
        for plat, pat in SOCIAL_RE.items():
            if pat.search(lnk) and not channel.get(plat):
                channel[plat] = lnk

    # Deep scrape the creator's website
    if channel["website"]:
        ws = scrape_website_deep(channel["website"])
        if not channel["email"] and ws["emails"]:
            channel["email"] = ws["emails"][0]
        if not channel["phone"] and ws["phones"]:
            channel["phone"] = ws["phones"][0]
        for plat in ["facebook","instagram","twitter","tiktok","linkedin"]:
            if not channel[plat] and ws.get(plat):
                channel[plat] = ws[plat]
        if not channel["key_people"] and ws["people"]:
            channel["key_people"] = ws["people"]
        if not channel["description"] and ws.get("description"):
            channel["description"] = ws["description"]

    # Format numbers
    try:
        channel["subscribers_fmt"] = fmt_number(int(channel["subscribers"]))
    except Exception:
        channel["subscribers_fmt"] = channel["subscribers"]
    try:
        channel["views_fmt"] = fmt_number(int(channel["total_views"]))
    except Exception:
        channel["views_fmt"] = channel["total_views"]

    return channel

def fmt_number(n):
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


# ═════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "service": "YouTube SEO Intelligence",
        "api_key_loaded": bool(YT_API_KEY),
        "endpoints": ["/health", "/search", "/export-csv"],
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "yt_api": "connected" if YT_API_KEY else "missing — scrape mode only",
    })

@app.route("/search", methods=["POST","OPTIONS"])
def search():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    body        = request.get_json(force=True, silent=True) or {}
    keyword     = body.get("keyword","").strip()
    location    = body.get("location","").strip()
    max_results = min(int(body.get("max_results", 20)), 50)
    order       = body.get("order", "relevance")   # relevance | viewCount | rating | videoCount
    min_subs    = int(body.get("min_subscribers", 0))
    max_subs    = int(body.get("max_subscribers", 999_999_999))
    country_filter = body.get("country_filter","").strip().upper()

    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    print(f"\n[SEARCH] keyword='{keyword}' location='{location}' max={max_results} order={order}")

    # Step 1: Get channel IDs
    if YT_API_KEY:
        channel_ids = yt_search(keyword, location, max_results * 2, order)
    else:
        channel_ids = yt_scrape_search(keyword, location, max_results * 2)

    if not channel_ids:
        return jsonify({"error": "No channels found. Try a different keyword or check your API key.", "results": []}), 200

    # Step 2: Get full channel details
    if YT_API_KEY:
        channels = yt_channel_details(channel_ids)
    else:
        # Build minimal channel dicts from IDs for scrape-only mode
        channels = [{"channel_id": cid,
                     "channel_name": "",
                     "channel_url": f"https://www.youtube.com/channel/{cid}",
                     "custom_url":"","country":"","language":"",
                     "description":"","published_at":"","thumbnail":"",
                     "subscribers":"0","total_views":"0","video_count":"0",
                     "hidden_subs":False,"keywords":"","trailer_url":"",
                     "topics":[],"website":"","email":"","phone":"",
                     "facebook":"","instagram":"","twitter":"","tiktok":"",
                     "linkedin":"","other_links":[],"key_people":"",
                     "business_email":"","handle_url":"","subscribers_fmt":"N/A","views_fmt":"N/A",
                     } for cid in channel_ids]

    # Step 3: Filter by subscribers / country
    filtered = []
    for ch in channels:
        try:
            subs = int(ch.get("subscribers","0"))
        except Exception:
            subs = 0
        if not (min_subs <= subs <= max_subs):
            continue
        if country_filter and ch.get("country","").upper() != country_filter:
            continue
        filtered.append(ch)

    # Step 4: Enrich each channel (deep scrape)
    enriched = []
    for ch in filtered[:max_results]:
        try:
            ch = enrich_channel(ch)
        except Exception as e:
            print(f"  Enrich error for {ch.get('channel_id')}: {e}")
        enriched.append(ch)

    # Remove duplicates
    seen = set()
    final = []
    for ch in enriched:
        cid = ch.get("channel_id","")
        if cid and cid not in seen:
            seen.add(cid)
            final.append(ch)

    print(f"[SEARCH] Done — {len(final)} channels returned\n")

    return jsonify({
        "keyword":  keyword,
        "location": location,
        "count":    len(final),
        "api_mode": "YouTube API v3" if YT_API_KEY else "Scrape (no API key)",
        "results":  final,
    })


@app.route("/export-csv", methods=["POST","OPTIONS"])
def export_csv():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    body    = request.get_json(force=True, silent=True) or {}
    results = body.get("results", [])

    if not results:
        return jsonify({"error": "No results"}), 400

    cols = [
        "channel_name","channel_url","handle_url","custom_url",
        "subscribers","subscribers_fmt","total_views","views_fmt","video_count",
        "country","language","published_at",
        "email","phone","website",
        "facebook","instagram","twitter","tiktok","linkedin",
        "description","keywords","topics",
    ]

    lines = [",".join(cols)]
    for r in results:
        row = []
        for col in cols:
            val = r.get(col, "")
            if isinstance(val, list):
                val = " | ".join(str(v) for v in val)
            val = str(val).replace('"','""').replace("\n"," ")
            row.append(f'"{val}"')
        lines.append(",".join(row))

    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=youtube_seo.csv",
                 "Access-Control-Allow-Origin": "*"}
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting on port {port} | YT API: {'YES' if YT_API_KEY else 'NO (scrape mode)'}")
    app.run(host="0.0.0.0", port=port, debug=False)
