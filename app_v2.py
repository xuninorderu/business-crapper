"""
Business Intelligence Scraper — Flask Backend
===============================================
Scrapes businesses by niche + location from multiple sources:
- Google Search / Maps (via requests)
- Yellow Pages
- Yelp
- LinkedIn (public)
- Company websites (email, phone, socials, key people)

Install:
    pip install flask flask-cors requests beautifulsoup4 gunicorn lxml

Run locally:
    python app.py  →  http://localhost:5000
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import re, time, json, logging, csv, io, random
import requests as req
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse, quote_plus

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ════════════════════════════════════════════════════════════
#  HEADERS — rotate user agents to avoid blocks
# ════════════════════════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def safe_get(url, timeout=12):
    try:
        time.sleep(random.uniform(0.8, 1.8))
        r = req.get(url, headers=get_headers(), timeout=timeout)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        log.warning(f"GET failed {url}: {e}")
        return ""

# ════════════════════════════════════════════════════════════
#  REGEX PATTERNS
# ════════════════════════════════════════════════════════════
EMAIL_RE   = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
PHONE_RE   = r"(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
PHONE_BD   = r"(?:\+880|0)1[3-9]\d{8}"
SOCIAL_RE  = {
    "facebook":  r"(?:https?://)?(?:www\.)?facebook\.com/(?!sharer)[A-Za-z0-9_.%-]+",
    "instagram": r"(?:https?://)?(?:www\.)?instagram\.com/[A-Za-z0-9_.%-]+",
    "twitter":   r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+",
    "linkedin":  r"(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_%-]+",
    "youtube":   r"(?:https?://)?(?:www\.)?youtube\.com/(?:@|channel/|c/)[A-Za-z0-9_.%-]+",
    "tiktok":    r"(?:https?://)?(?:www\.)?tiktok\.com/@[A-Za-z0-9_.%-]+",
}

def extract_emails(text):
    found = re.findall(EMAIL_RE, text)
    return list({e for e in found if not e.endswith((".png",".jpg",".gif",".svg",".webp",".css",".js"))})

def extract_phones(text):
    found = re.findall(PHONE_RE, text) + re.findall(PHONE_BD, text)
    cleaned = []
    for p in found:
        p = p.strip()
        if len(re.sub(r"\D","",p)) >= 7:
            cleaned.append(p)
    return list(set(cleaned))[:3]

def extract_socials(text):
    result = {}
    for platform, pattern in SOCIAL_RE.items():
        found = re.findall(pattern, text, re.IGNORECASE)
        if found:
            url = found[0]
            if not url.startswith("http"):
                url = "https://" + url
            result[platform] = url
    return result

def extract_website(soup, base_url=""):
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "google" not in href and "facebook" not in href \
           and "yelp" not in href and "yellowpages" not in href and "bing" not in href:
            parsed = urlparse(href)
            if parsed.netloc:
                return href
    return ""

# ════════════════════════════════════════════════════════════
#  SOURCE 1 — Google Search
# ════════════════════════════════════════════════════════════

def search_google(query, num=20):
    """Scrape Google search results for businesses."""
    businesses = []
    seen = set()

    for page in range(0, min(num, 60), 10):
        url = f"https://www.google.com/search?q={quote_plus(query)}&start={page}&num=10"
        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")

        # Extract organic results
        for result in soup.select("div.g, div[data-hveid]"):
            title_el = result.select_one("h3")
            link_el  = result.select_one("a[href]")
            desc_el  = result.select_one("div.VwiC3b, span.st, div[data-sncf]")

            if not title_el or not link_el:
                continue

            name = title_el.get_text(strip=True)
            href = link_el.get("href","")
            if not href.startswith("http") or "google.com" in href:
                continue
            if href in seen:
                continue
            seen.add(href)

            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            domain = urlparse(href).netloc.replace("www.","")

            businesses.append({
                "name":    name,
                "website": href,
                "domain":  domain,
                "description": desc,
                "source":  "Google Search",
            })

        if len(businesses) >= num:
            break

    return businesses[:num]

# ════════════════════════════════════════════════════════════
#  SOURCE 2 — Yelp
# ════════════════════════════════════════════════════════════

def search_yelp(niche, location, num=20):
    businesses = []
    offset = 0

    while len(businesses) < num:
        url = f"https://www.yelp.com/search?find_desc={quote_plus(niche)}&find_loc={quote_plus(location)}&start={offset}"
        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")

        for card in soup.select("div[data-testid='serp-ia-card'], li.regular-search-result, div.businessName__09f24__EYSZE"):
            name_el = card.select_one("a.css-19v1rkv, span.css-1egxyvc, a[name]")
            if not name_el:
                name_el = card.select_one("h3 a, h4 a")
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            link = name_el.get("href","")
            if link and not link.startswith("http"):
                link = "https://www.yelp.com" + link

            phone_el = card.select_one("p[class*='phone'], span[class*='phone']")
            phone = phone_el.get_text(strip=True) if phone_el else ""

            addr_el = card.select_one("address, span[class*='address'], p[class*='address']")
            address = addr_el.get_text(strip=True) if addr_el else ""

            rating_el = card.select_one("div[aria-label*='star'], span[class*='ratingValue']")
            rating = ""
            if rating_el:
                rating = rating_el.get("aria-label","").replace(" star rating","")

            businesses.append({
                "name":    name,
                "address": address,
                "phone":   phone,
                "rating":  rating,
                "yelp_url": link,
                "source":  "Yelp",
            })

        offset += 10
        if offset >= 40 or len(businesses) >= num:
            break

    return businesses[:num]

# ════════════════════════════════════════════════════════════
#  SOURCE 3 — Yellow Pages
# ════════════════════════════════════════════════════════════

def search_yellowpages(niche, location, num=20):
    businesses = []
    page = 1

    while len(businesses) < num and page <= 3:
        url = f"https://www.yellowpages.com/search?search_terms={quote_plus(niche)}&geo_location_terms={quote_plus(location)}&page={page}"
        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")

        for card in soup.select("div.result, div.organic"):
            name_el  = card.select_one("a.business-name, h2.n span")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)

            phone_el = card.select_one("div.phones, a.phone")
            phone    = phone_el.get_text(strip=True) if phone_el else ""

            addr_el  = card.select_one("p.adr, div.street-address")
            address  = addr_el.get_text(strip=True) if addr_el else ""

            web_el   = card.select_one("a.track-visit-website, a[class*='website']")
            website  = web_el.get("href","") if web_el else ""

            cats_el  = card.select("div.categories a")
            cats     = ", ".join(c.get_text(strip=True) for c in cats_el)

            businesses.append({
                "name":     name,
                "phone":    phone,
                "address":  address,
                "website":  website,
                "category": cats,
                "source":   "Yellow Pages",
            })

        page += 1

    return businesses[:num]

# ════════════════════════════════════════════════════════════
#  SOURCE 4 — Scrape company website
# ════════════════════════════════════════════════════════════

def scrape_company_website(url):
    """Deep scrape a company website for all contact/people data."""
    data = {
        "emails":  [],
        "phones":  [],
        "socials": {},
        "people":  [],
        "address": "",
    }
    if not url:
        return data

    combined_html = ""
    pages = [url]
    for slug in ["/contact", "/about", "/about-us", "/contact-us", "/team", "/our-team", "/leadership", "/people"]:
        pages.append(url.rstrip("/") + slug)

    visited = set()
    for page_url in pages[:5]:
        if page_url in visited:
            continue
        visited.add(page_url)
        html = safe_get(page_url)
        if html:
            combined_html += html

    if not combined_html:
        return data

    # Emails & phones
    data["emails"] = extract_emails(combined_html)[:5]
    data["phones"] = extract_phones(combined_html)[:3]
    data["socials"] = extract_socials(combined_html)

    # Address
    soup = BeautifulSoup(combined_html, "lxml")
    addr_el = soup.select_one("address, [class*='address'], [itemprop='address']")
    if addr_el:
        data["address"] = addr_el.get_text(separator=" ", strip=True)[:200]

    # Key people — look for team/about sections
    people = []
    person_blocks = soup.select(
        "div[class*='team'] div[class*='member'], "
        "div[class*='people'] div[class*='person'], "
        "div[class*='staff'] div, "
        "article[class*='team'], "
        "div[class*='leadership'] div[class*='card'], "
        "li[class*='team-member']"
    )

    for block in person_blocks[:6]:
        name_el = block.select_one("h2,h3,h4,h5,strong,[class*='name']")
        role_el = block.select_one("p,[class*='title'],[class*='role'],[class*='position'],[class*='job']")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        role = role_el.get_text(strip=True) if role_el else ""
        if len(name) < 3 or len(name) > 60:
            continue

        # Email for this person
        block_html = str(block)
        p_emails = extract_emails(block_html)
        p_phones = extract_phones(block_html)
        p_li = ""
        li_match = re.search(r"linkedin\.com/in/[A-Za-z0-9_%-]+", block_html, re.IGNORECASE)
        if li_match:
            p_li = "https://" + li_match.group(0)

        people.append({
            "name":     name,
            "role":     role,
            "email":    p_emails[0] if p_emails else "",
            "phone":    p_phones[0] if p_phones else "",
            "linkedin": p_li,
        })

    data["people"] = people[:3]
    return data

# ════════════════════════════════════════════════════════════
#  SOURCE 5 — LinkedIn company search (public)
# ════════════════════════════════════════════════════════════

def search_linkedin(niche, location, num=10):
    businesses = []
    url = f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(niche + ' ' + location)}"
    html = safe_get(url)
    if not html:
        return businesses

    soup = BeautifulSoup(html, "lxml")
    for card in soup.select("li.search-result, div[data-chameleon-result-urn]")[:num]:
        name_el = card.select_one("span.name, a.app-aware-link span")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        sub_el = card.select_one("p.subline-level-1, span.subline-level-1-v2")
        subtitle = sub_el.get_text(strip=True) if sub_el else ""
        link_el = card.select_one("a[href*='/company/']")
        li_url  = link_el.get("href","") if link_el else ""
        if li_url and not li_url.startswith("http"):
            li_url = "https://www.linkedin.com" + li_url
        businesses.append({
            "name":     name,
            "subtitle": subtitle,
            "linkedin": li_url,
            "source":   "LinkedIn",
        })

    return businesses

# ════════════════════════════════════════════════════════════
#  MERGE — combine all sources into unified records
# ════════════════════════════════════════════════════════════

def merge_businesses(all_results, max_results):
    """Merge and deduplicate businesses from all sources."""
    seen_names = set()
    merged = []

    for biz in all_results:
        name = biz.get("name","").strip()
        if not name or len(name) < 2:
            continue
        key = re.sub(r"[^a-z0-9]","", name.lower())[:20]
        if key in seen_names:
            continue
        seen_names.add(key)
        merged.append(biz)
        if len(merged) >= max_results:
            break

    return merged

def enrich_business(biz):
    """Scrape the company website to enrich with full contact data."""
    website = biz.get("website","")
    if not website:
        return biz

    log.info(f"  Enriching: {biz.get('name','?')} → {website}")
    site_data = scrape_company_website(website)

    # Merge in data
    if site_data["emails"] and not biz.get("email"):
        biz["email"] = site_data["emails"][0]
    if site_data["emails"]:
        biz["all_emails"] = site_data["emails"]
    if site_data["phones"] and not biz.get("phone"):
        biz["phone"] = site_data["phones"][0]
    if not biz.get("address") and site_data["address"]:
        biz["address"] = site_data["address"]

    # Merge socials
    existing = biz.get("socials", {})
    existing.update(site_data["socials"])
    biz["socials"] = existing
    # Flatten socials to top level
    for k, v in existing.items():
        if not biz.get(k):
            biz[k] = v

    biz["people"] = site_data["people"]
    return biz

# ════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/scrape", methods=["POST"])
def scrape():
    body     = request.get_json() or {}
    niche    = body.get("niche","").strip()
    location = body.get("location","").strip()
    max_res  = min(int(body.get("max_results", 10)), 50)
    sources  = body.get("sources", ["google","yelp","yellowpages"])

    if not niche or not location:
        return jsonify({"error": "niche and location are required"}), 400

    query = f"{niche} {location}"
    log.info(f"Scraping: '{query}' | max={max_res} | sources={sources}")

    all_raw = []

    # ── Collect from all sources ──────────────────────────
    per_source = max(max_res // len(sources), 5)

    if "google" in sources:
        log.info("Searching Google...")
        all_raw += search_google(f"{niche} business {location}", per_source)

    if "yelp" in sources:
        log.info("Searching Yelp...")
        all_raw += search_yelp(niche, location, per_source)

    if "yellowpages" in sources:
        log.info("Searching Yellow Pages...")
        all_raw += search_yellowpages(niche, location, per_source)

    if "linkedin" in sources:
        log.info("Searching LinkedIn...")
        all_raw += search_linkedin(niche, location, per_source)

    # ── Merge & deduplicate ───────────────────────────────
    businesses = merge_businesses(all_raw, max_res)
    log.info(f"Found {len(businesses)} unique businesses, enriching...")

    # ── Enrich each with website scraping ────────────────
    enriched = []
    for biz in businesses:
        try:
            enriched.append(enrich_business(biz))
        except Exception as e:
            log.error(f"Enrich error for {biz.get('name')}: {e}")
            enriched.append(biz)

    # ── Normalize output ──────────────────────────────────
    results = []
    for b in enriched:
        socials = b.get("socials", {})
        results.append({
            "name":        b.get("name",""),
            "address":     b.get("address",""),
            "phone":       b.get("phone",""),
            "website":     b.get("website",""),
            "email":       b.get("email",""),
            "all_emails":  b.get("all_emails",[]),
            "description": b.get("description","")[:300],
            "rating":      b.get("rating",""),
            "category":    b.get("category",""),
            "source":      b.get("source",""),
            "facebook":    b.get("facebook","") or socials.get("facebook",""),
            "instagram":   b.get("instagram","") or socials.get("instagram",""),
            "linkedin":    b.get("linkedin","") or socials.get("linkedin",""),
            "twitter":     b.get("twitter","") or socials.get("twitter",""),
            "youtube":     b.get("youtube","") or socials.get("youtube",""),
            "tiktok":      b.get("tiktok","") or socials.get("tiktok",""),
            "people":      b.get("people",[]),
            "yelp_url":    b.get("yelp_url",""),
        })

    return jsonify({
        "query":      query,
        "count":      len(results),
        "results":    results,
        "scraped_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    })


@app.route("/export-csv", methods=["POST"])
def export_csv():
    body    = request.get_json() or {}
    results = body.get("results", [])

    buf = io.StringIO()
    fields = ["name","address","phone","email","website",
              "facebook","instagram","linkedin","twitter","youtube","tiktok",
              "rating","category","source","description"]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()

    for r in results:
        w.writerow(r)
        # Write people as sub-rows
        for p in r.get("people", []):
            w.writerow({
                "name":    f"  → {p.get('name','')} ({p.get('role','')})",
                "phone":   p.get("phone",""),
                "email":   p.get("email",""),
                "linkedin":p.get("linkedin",""),
            })

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=business_intel.csv"}
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
