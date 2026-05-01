"""
Business Lead Generator — Flask Backend API
============================================
Crash-proof deployment on Railway/Render without Selenium.
Uses multi-source scraping: Google Maps, business directories, social APIs.

Install:
    pip install flask flask-cors requests beautifulsoup4 lxml gunicorn

Run locally:
    python app.py
    → http://localhost:5000
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import re, time, json, logging, requests, csv, io, random
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote_plus, urlparse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EMAIL_RE = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
PHONE_RE = [
    r"\+?1?[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}",  # US/CA
    r"\+?[0-9]{1,3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}",  # International
    r"\([0-9]{3}\)\s*[0-9]{3}[\s\-]?[0-9]{4}",  # (555) 555-5555
]
SOCIAL_RE = {
    "facebook":  r"facebook\.com/[A-Za-z0-9_.%-]+",
    "instagram": r"instagram\.com/[A-Za-z0-9_.%-]+",
    "twitter":   r"(?:twitter|x)\.com/[A-Za-z0-9_]+",
    "linkedin":  r"linkedin\.com/(?:in|company)/[A-Za-z0-9_%-]+",
    "youtube":   r"youtube\.com/(?:c/|channel/|@)[A-Za-z0-9_%-]+",
    "tiktok":    r"tiktok\.com/@[A-Za-z0-9_.%-]+",
}

# ════════════════════════════════════════════════════════════
#  CORE SCRAPING UTILITIES
# ════════════════════════════════════════════════════════════

def fetch_html(url, timeout=12):
    """Fetch HTML without Selenium — pure requests."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        log.warning(f"Fetch error for {url}: {e}")
    return ""

def extract_emails(text):
    """Extract valid emails from text."""
    emails = [e for e in re.findall(EMAIL_RE, text)
              if not e.endswith((".png", ".jpg", ".svg", ".webp", ".gif"))]
    return list(dict.fromkeys(emails))  # Remove duplicates

def extract_phones(text):
    """Extract phone numbers from text."""
    phones = []
    for pat in PHONE_RE:
        found = re.findall(pat, text)
        for f in found:
            clean = re.sub(r"[^\d+]", "", f)
            if len(clean) >= 10:
                phones.append(f.strip())
    return list(dict.fromkeys(phones))

def extract_socials(text):
    """Extract social media links from text."""
    socials = {}
    for platform, pat in SOCIAL_RE.items():
        found = re.findall(pat, text, re.IGNORECASE)
        if found:
            socials[platform] = "https://" + found[0].split("/")[0] + "/" + found[0].split("/", 1)[1] if "/" in found[0] else "https://" + found[0]
    return socials

def extract_website(text, base_domain=""):
    """Extract website URL from text."""
    # Look for explicit website links
    soup = BeautifulSoup(text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and not any(x in href.lower() for x in ["google.com", "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "tiktok.com"]):
            return href

    # Regex fallback for domain patterns
    domain_re = r"https?://(?:www\.)?([a-zA-Z0-9][a-zA-Z0-9\-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,})(?:/[^\s"<>]*)?"
    found = re.findall(domain_re, text)
    if found:
        return "https://www." + found[0]
    return ""

# ════════════════════════════════════════════════════════════
#  GOOGLE MAPS SCRAPER
# ════════════════════════════════════════════════════════════

def scrape_google_maps(query, location, max_results=20):
    """Scrape business listings from Google Maps via search."""
    results = []
    search_query = quote_plus(f"{query} {location}")

    # Try multiple Google endpoints
    urls = [
        f"https://www.google.com/search?q={search_query}&tbm=lcl",
        f"https://www.google.com/search?q={search_query}+business+directory",
        f"https://www.google.com/search?q={search_query}+contact",
    ]

    for url in urls:
        html = fetch_html(url, timeout=15)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Extract business cards from Google local results
        cards = soup.find_all("div", class_=re.compile(r"(VkpGBb|g|rlfl__tls|rl_tile-group)"))
        if not cards:
            cards = soup.find_all("div", attrs={"data-attrid": True})

        for card in cards[:max_results]:
            try:
                # Extract name
                name_elem = card.find("div", class_=re.compile(r"(dbg0pd|OSrXXb|SPZz6b)")) or card.find("h3")
                name = name_elem.get_text(strip=True) if name_elem else ""
                if not name or len(name) < 2:
                    continue

                # Extract address
                addr_elem = card.find("span", class_=re.compile(r"(LrzXr|address|street-address)")) or card.find("div", class_=re.compile(r"address"))
                address = addr_elem.get_text(strip=True) if addr_elem else ""

                # Extract phone
                phone_elem = card.find("span", class_=re.compile(r"(phone|LrzXr|oyrXab)"))
                phone = phone_elem.get_text(strip=True) if phone_elem else ""

                # Extract website
                web_elem = card.find("a", class_=re.compile(r"(ab_button|yYlJEf|a)"), href=True)
                website = ""
                if web_elem:
                    href = web_elem["href"]
                    if href.startswith("http") and "google.com" not in href:
                        website = href

                # Extract rating/reviews
                rating_elem = card.find("span", class_=re.compile(r"(rating|Y0A0hc)"))
                rating = rating_elem.get_text(strip=True) if rating_elem else ""

                business = {
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "website": website,
                    "rating": rating,
                    "source": "Google Maps",
                    "emails": [],
                    "socials": {},
                    "contacts": []
                }

                if business not in results:
                    results.append(business)

            except Exception as e:
                continue

        if len(results) >= max_results:
            break

    return results[:max_results]

# ════════════════════════════════════════════════════════════
#  YELP / DIRECTORY SCRAPER
# ════════════════════════════════════════════════════════════

def scrape_yelp_style(query, location, max_results=15):
    """Scrape Yelp-style business listings."""
    results = []
    search_query = quote_plus(f"{query} {location}")

    # Try Yelp search
    url = f"https://www.yelp.com/search?find_desc={quote_plus(query)}&find_loc={quote_plus(location)}"
    html = fetch_html(url, timeout=15)

    if html:
        soup = BeautifulSoup(html, "html.parser")
        businesses = soup.find_all("div", class_=re.compile(r"(container__09f24__|businessName__|arrange__)"))

        for biz in businesses[:max_results]:
            try:
                name_elem = biz.find("a", class_=re.compile(r"(css-19v1rkv|business-name)"))
                name = name_elem.get_text(strip=True) if name_elem else ""
                if not name:
                    continue

                # Get Yelp page for more details
                yelp_url = "https://yelp.com" + name_elem["href"] if name_elem and name_elem.get("href") else ""

                address = ""
                phone = ""
                website = ""

                if yelp_url:
                    yelp_html = fetch_html(yelp_url, timeout=10)
                    if yelp_html:
                        yelp_soup = BeautifulSoup(yelp_html, "html.parser")
                        addr_elem = yelp_soup.find("address") or yelp_soup.find("p", class_=re.compile(r"address"))
                        address = addr_elem.get_text(strip=True) if addr_elem else ""

                        phone_elem = yelp_soup.find("p", class_=re.compile(r"phone")) or yelp_soup.find("a", href=re.compile(r"tel:"))
                        phone = phone_elem.get_text(strip=True) if phone_elem else ""

                        web_elem = yelp_soup.find("a", class_=re.compile(r"website"), href=True)
                        if web_elem:
                            website = web_elem["href"]

                results.append({
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "website": website,
                    "yelp_url": yelp_url,
                    "source": "Yelp",
                    "emails": [],
                    "socials": {},
                    "contacts": []
                })
            except:
                continue

    return results[:max_results]

# ════════════════════════════════════════════════════════════
#  WEBSITE DEEP SCRAPE
# ════════════════════════════════════════════════════════════

def deep_scrape_website(url):
    """Deep scrape a business website for contact info and team details."""
    if not url or not url.startswith("http"):
        return {"emails": [], "phones": [], "socials": {}, "contacts": [], "addresses": []}

    data = {"emails": [], "phones": [], "socials": {}, "contacts": [], "addresses": []}

    # Scrape main page + contact + about + team pages
    pages_to_scrape = ["", "/contact", "/about", "/team", "/about-us", "/contact-us", "/our-team", "/leadership"]
    combined_html = ""

    for page in pages_to_scrape:
        try:
            full_url = url.rstrip("/") + page
            html = fetch_html(full_url, timeout=8)
            if html:
                combined_html += html + " "
        except:
            pass

    if not combined_html:
        return data

    # Extract emails
    data["emails"] = extract_emails(combined_html)

    # Extract phones
    data["phones"] = extract_phones(combined_html)

    # Extract socials
    data["socials"] = extract_socials(combined_html)

    # Extract team members / leadership
    soup = BeautifulSoup(combined_html, "html.parser")

    # Look for team member patterns
    team_patterns = [
        (r"(CEO|Founder|Owner|President|Director|Manager|Partner)", "leadership"),
        (r"([A-Z][a-z]+\s[A-Z][a-z]+)\s*[-–—]\s*(CEO|Founder|Owner|President|Director|Manager)", "named_role"),
    ]

    for pattern, ptype in team_patterns:
        matches = re.findall(pattern, combined_html)
        for match in matches:
            if isinstance(match, tuple):
                name, role = match
            else:
                name = match
                role = "Team Member"

            # Try to find email for this person
            person_email = ""
            for email in data["emails"]:
                if name.split()[0].lower() in email.lower() or name.split()[-1].lower() in email.lower():
                    person_email = email
                    break

            contact = {
                "name": name.strip(),
                "role": role.strip(),
                "email": person_email,
                "phone": data["phones"][0] if data["phones"] else "",
                "linkedin": ""
            }

            # Avoid duplicates
            if not any(c["name"] == contact["name"] for c in data["contacts"]):
                data["contacts"].append(contact)

    # Extract addresses
    addr_patterns = [
        r"\d+\s+[A-Za-z0-9\s,]+(?:Avenue|Lane|Road|Boulevard|Drive|Street|Ave|Ln|Rd|Blvd|Dr|St)\.?\s*[A-Za-z]*,\s*[A-Za-z]+\s*\d{5}",
        r"\d+\s+[A-Za-z0-9\s]+,\s*[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}",
    ]
    for pat in addr_patterns:
        found = re.findall(pat, combined_html)
        data["addresses"].extend(found)
    data["addresses"] = list(dict.fromkeys(data["addresses"]))[:3]

    return data

# ════════════════════════════════════════════════════════════
#  FACEBOOK PAGE SCRAPER
# ════════════════════════════════════════════════════════════

def scrape_facebook_pages(query, location, max_results=10):
    """Find Facebook business pages."""
    results = []
    search_query = quote_plus(f"{query} {location}")
    url = f"https://www.facebook.com/search/pages/?q={search_query}"

    html = fetch_html(url, timeout=12)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        # Extract page links
        links = soup.find_all("a", href=re.compile(r"facebook\.com/[^/]+"))
        for link in links[:max_results]:
            href = link.get("href", "")
            name = link.get_text(strip=True)
            if name and href and "facebook.com" in href:
                results.append({
                    "name": name,
                    "facebook": href if href.startswith("http") else "https://facebook.com" + href,
                    "source": "Facebook",
                    "address": "",
                    "phone": "",
                    "website": "",
                    "emails": [],
                    "socials": {"facebook": href},
                    "contacts": []
                })
    return results[:max_results]

# ════════════════════════════════════════════════════════════
#  LINKEDIN COMPANY SEARCH
# ════════════════════════════════════════════════════════════

def scrape_linkedin_companies(query, location, max_results=10):
    """Find LinkedIn company pages."""
    results = []
    search_query = quote_plus(f"{query} {location}")
    url = f"https://www.linkedin.com/search/results/companies/?keywords={search_query}"

    html = fetch_html(url, timeout=12)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        companies = soup.find_all("a", href=re.compile(r"linkedin\.com/company/"))
        for comp in companies[:max_results]:
            href = comp.get("href", "")
            name = comp.get_text(strip=True)
            if name and href:
                results.append({
                    "name": name,
                    "linkedin": href if href.startswith("http") else "https://linkedin.com" + href,
                    "source": "LinkedIn",
                    "address": "",
                    "phone": "",
                    "website": "",
                    "emails": [],
                    "socials": {"linkedin": href if href.startswith("http") else "https://linkedin.com" + href},
                    "contacts": []
                })
    return results[:max_results]

# ════════════════════════════════════════════════════════════
#  MAIN AGGREGATOR
# ════════════════════════════════════════════════════════════

def aggregate_leads(niche, location, max_results=20):
    """Aggregate leads from multiple sources."""
    all_results = []
    seen_names = set()

    # Source 1: Google Maps
    log.info(f"Scraping Google Maps for {niche} in {location}")
    maps_results = scrape_google_maps(niche, location, max_results=max_results)
    for r in maps_results:
        if r["name"] not in seen_names:
            seen_names.add(r["name"])
            all_results.append(r)

    # Source 2: Yelp/Directories
    if len(all_results) < max_results:
        log.info("Scraping Yelp-style directories")
        yelp_results = scrape_yelp_style(niche, location, max_results=max_results - len(all_results))
        for r in yelp_results:
            if r["name"] not in seen_names:
                seen_names.add(r["name"])
                all_results.append(r)

    # Source 3: Facebook
    if len(all_results) < max_results:
        log.info("Scraping Facebook pages")
        fb_results = scrape_facebook_pages(niche, location, max_results=max_results - len(all_results))
        for r in fb_results:
            if r["name"] not in seen_names:
                seen_names.add(r["name"])
                all_results.append(r)

    # Deep scrape websites for enriched data
    log.info("Deep scraping websites for contact enrichment")
    for i, business in enumerate(all_results):
        if business.get("website"):
            log.info(f"Deep scraping: {business['website']}")
            web_data = deep_scrape_website(business["website"])

            # Merge enriched data
            if web_data["emails"]:
                business["emails"] = web_data["emails"]
            if web_data["phones"]:
                business["phone"] = business["phone"] or web_data["phones"][0]
            if web_data["socials"]:
                business["socials"].update(web_data["socials"])
            if web_data["contacts"]:
                business["contacts"] = web_data["contacts"][:3]  # Top 3 contacts
            if web_data["addresses"] and not business["address"]:
                business["address"] = web_data["addresses"][0]

        # Small delay to be respectful
        if i % 3 == 0:
            time.sleep(random.uniform(0.5, 1.5))

    return all_results[:max_results]

# ════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "version": "2.0-business-leads",
        "selenium": False,
        "sources": ["google_maps", "yelp", "facebook", "linkedin", "website_deep_scrape"]
    })

@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.get_json() or {}
    niche = body.get("niche", "").strip()
    location = body.get("location", "").strip()
    max_results = int(body.get("max_results", 20))

    if not niche or not location:
        return jsonify({"error": "niche and location are required"}), 400

    if max_results > 100:
        max_results = 100
    if max_results < 1:
        max_results = 10

    try:
        results = aggregate_leads(niche, location, max_results=max_results)

        return jsonify({
            "query": f"{niche} {location}",
            "count": len(results),
            "results": results,
            "scraped_at": datetime.now().strftime("%d %b %Y, %H:%M"),
            "sources_scraped": ["google_maps", "business_directories", "social_media", "website_enrichment"]
        })
    except Exception as e:
        log.error(f"Scrape error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/export-csv", methods=["POST"])
def export_csv():
    body = request.get_json() or {}
    results = body.get("results", [])

    # Flatten contacts for CSV
    flat_results = []
    for r in results:
        base = {
            "name": r.get("name", ""),
            "address": r.get("address", ""),
            "phone": r.get("phone", ""),
            "website": r.get("website", ""),
            "email": ", ".join(r.get("emails", [])),
            "facebook": r.get("socials", {}).get("facebook", ""),
            "instagram": r.get("socials", {}).get("instagram", ""),
            "twitter": r.get("socials", {}).get("twitter", ""),
            "linkedin": r.get("socials", {}).get("linkedin", ""),
            "youtube": r.get("socials", {}).get("youtube", ""),
            "tiktok": r.get("socials", {}).get("tiktok", ""),
            "rating": r.get("rating", ""),
            "source": r.get("source", ""),
        }

        contacts = r.get("contacts", [])
        if contacts:
            for i, contact in enumerate(contacts[:3]):
                row = base.copy()
                row[f"contact_{i+1}_name"] = contact.get("name", "")
                row[f"contact_{i+1}_role"] = contact.get("role", "")
                row[f"contact_{i+1}_email"] = contact.get("email", "")
                row[f"contact_{i+1}_phone"] = contact.get("phone", "")
                row[f"contact_{i+1}_linkedin"] = contact.get("linkedin", "")
                flat_results.append(row)
        else:
            flat_results.append(base)

    if not flat_results:
        return jsonify({"error": "No results to export"}), 400

    # Build fieldnames
    fieldnames = list(flat_results[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(flat_results)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=business_leads.csv"}
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
