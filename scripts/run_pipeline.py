import csv
import os
import re
import time
from datetime import datetime, timezone
import requests
from google import genai
from google.genai import types
from google.genai.errors import APIError

# --- CONFIGURATION ---
CSV_PATH = "data/targets.csv"
OUTPUT_DIR = "generated_pitches"
MAX_LEADS_PER_RUN = 7
FOLLOW_UP_DAYS = 30
PACING_DELAY_SECONDS = 4
APOLLO_TIMEOUT_SECONDS = 30

# Multi-model failover chain to bypass free-tier 503 capacity spikes
MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=30000),  # 30s hard timeout per request
)


def get_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def days_since(date_str: str) -> int:
    if not date_str or not date_str.strip():
        return -1
    try:
        past_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        today_date = datetime.now(timezone.utc).date()
        return (today_date - past_date).days
    except ValueError:
        return -1


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return cleaned.strip("_").lower()


def get_radio_africa_routing(category: str) -> str:
    cat = (category or "").lower()
    if "tvet" in cat or "technical" in cat or "education" in cat:
        return (
            "Youth & Student Intake Reach (Kiss 100 & Radio Jambo) for prospective trainees/parents, "
            "paired with Official Tender, Graduation & Accreditation Notices in The Star / MyGov."
        )
    if "sacco" in cat or "real estate" in cat or "investment" in cat:
        return (
            "Statutory & Legal Notice Credibility (The Star / MyGov) for AGM notices, title deed issuance "
            "schedules, and land balloting updates, paired with High-Trust Executive & Diaspora Reach "
            "(Classic 105 & East FM)."
        )
    if "agro" in cat or "machinery" in cat or "agriculture" in cat or "climate" in cat:
        return (
            "Grassroots Farmer & Agribusiness Reach (Radio Jambo & Regional Vernacular Stations) for "
            "seasonal equipment/input campaigns, paired with Policy, Tender & Research Dissemination "
            "in The Star / MyGov."
        )
    if "health" in cat or "medical" in cat or "hospital" in cat:
        return (
            "Community & Family Health Awareness (Radio Jambo & Classic 105) for specialist clinics and "
            "outreach camps, paired with Institutional Procurement & Public Notices in The Star / MyGov."
        )
    return (
        "National Print & Official Notice Credibility (The Star / MyGov) combined with Targeted "
        "Commercial Broadcast Reach (Classic 105, Kiss 100, and Radio Jambo)."
    )


def enrich_contact_via_apollo(row: dict) -> dict:
    """Attempts executive contact enrichment via Apollo.io while preserving fallback info@ emails."""
    if not APOLLO_API_KEY:
        return row

    domain = (row.get("Website_Domain") or "").strip()
    if not domain:
        return row

    # Skip Apollo lookup if we already have both a Contact_Name and a non-generic email
    existing_email = (row.get("Contact_Email") or "").strip()
    existing_name = (row.get("Contact_Name") or "").strip()
    if existing_name and existing_email and not existing_email.lower().startswith("info@"):
        return row

    url = "https://api.apollo.io/api/v1/mixed_people/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY,
    }
    payload = {
        "q_organization_domains": domain,
        "person_titles": [
            "Managing Director",
            "Chief Executive Officer",
            "CEO",
            "Principal",
            "General Manager",
            "Marketing Manager",
            "Corporate Communications Manager",
            "Head of Marketing",
            "Procurement Manager",
        ],
        "page": 1,
        "per_page": 3,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=APOLLO_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            print(f"  [Apollo] HTTP {resp.status_code} for {domain} — keeping existing contact details.")
            return row

        data = resp.json()
        people = data.get("people") or []
        for person in people:
            email = (person.get("email") or "").strip()
            if email and "email_not_unlocked" not in email.lower():
                full_name = (person.get("name") or "").strip()
                title = (person.get("title") or "").strip()
                if full_name:
                    row["Contact_Name"] = full_name
                if title:
                    row["Role"] = title
                row["Contact_Email"] = email
                print(f"  [Apollo] Enriched {domain} -> {full_name} ({title}) <{email}>")
                return row

        print(f"  [Apollo] No unlocked executive email for {domain} — keeping fallback ({existing_email or 'none'}).")
    except Exception as exc:
        print(f"  [Apollo] Lookup skipped for {domain} due to error: {exc}")

    return row


def build_first_touch_prompt(row: dict) -> str:
    org_name = row.get("Organization_Name", "").strip()
    category = row.get("Category", "").strip()
    contact_name = row.get("Contact_Name", "").strip()
    role = row.get("Role", "").strip()
    email = row.get("Contact_Email", "").strip()
    domain = row.get("Website_Domain", "").strip()
    routing_angles = get_radio_africa_routing(category)

    salutation = f"Dear {contact_name}," if contact_name else f"Dear {role or 'Managing Director / Principal'},"

    return f"""You are a senior B2B commercial account executive at Radio Africa Group in Nairobi, Kenya.
Write a crisp, high-converting initial B2B outreach email pitching Radio Africa Group's integrated print (The Star / MyGov) and broadcast (Classic 105, Kiss 100, Radio Jambo, East FM) advertising solutions.

Target Details:
- Organization Name: {org_name}
- Sector / Category: {category}
- Contact Name: {contact_name or "Not specified"}
- Role: {role or "Executive Leadership"}
- Recipient Email: {email}
- Website Domain: {domain}
- Recommended Radio Africa Group Media Angles: {routing_angles}

Strict Requirements:
1. Format the top clearly with:
   To: {email}
   Subject: [Compelling, specific subject line tailored to {org_name}]
2. Open with "{salutation}"
3. Keep the body concise (160–220 words), practical, and tailored specifically to {org_name}'s sector in Kenya.
4. Highlight 2 concrete value pillars matching the recommended Radio Africa Group media angles above.
5. Include one polite sentence noting that if their media buying/advertising is handled by a retained agency, they can forward the note to their account director for rate cards.
6. End with a low-friction call to action for a brief 10-minute call this week.
7. Use this exact signature block verbatim:
Warm regards,

Ruth Njaramba
Direct Commercial & Institutional Accounts Lead
Radio Africa Group | The Star / MyGov
Nairobi & Regional Hubs, Kenya
Cell / WhatsApp: 07242337
