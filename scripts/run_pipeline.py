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
    http_options=types.HttpOptions(timeout=30000),
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
    if not APOLLO_API_KEY:
        return row

    domain = (row.get("Website_Domain") or "").strip()
    if not domain:
        return row

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
            print(f"  [Apollo] HTTP {resp.status_code} for {domain} - keeping existing contact details.")
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

        print(f"  [Apollo] No unlocked executive email for {domain} - keeping fallback ({existing_email or 'none'}).")
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

    lines = [
        "You are a senior B2B commercial account executive at Radio Africa Group in Nairobi, Kenya.",
        "Write a crisp, high-converting initial B2B outreach email pitching Radio Africa Group's integrated print (The Star / MyGov) and broadcast (Classic 105, Kiss 100, Radio Jambo, East FM) advertising solutions.",
        "",
        "Target Details:",
        f"- Organization Name: {org_name}",
        f"- Sector / Category: {category}",
        f"- Contact Name: {contact_name or 'Not specified'}",
        f"- Role: {role or 'Executive Leadership'}",
        f"- Recipient Email: {email}",
        f"- Website Domain: {domain}",
        f"- Recommended Radio Africa Group Media Angles: {routing_angles}",
        "",
        "Strict Requirements:",
        "1. Format the top clearly with:",
        f"   To: {email}",
        f"   Subject: [Compelling, specific subject line tailored to {org_name}]",
        f'2. Open with "{salutation}"',
        f"3. Keep the body concise (160-220 words), practical, and tailored specifically to {org_name}'s sector in Kenya.",
        "4. Highlight 2 concrete value pillars matching the recommended Radio Africa Group media angles above.",
        "5. Include one polite sentence noting that if their media buying/advertising is handled by a retained agency, they can forward the note to their account director for rate cards.",
        "6. End with a low-friction call to action for a brief 10-minute call this week.",
        "7. Use this exact signature block verbatim:",
        "Warm regards,",
        "",
        "Ruth Njaramba",
        "Direct Commercial & Institutional Accounts Lead",
        "Radio Africa Group | The Star / MyGov",
        "Nairobi & Regional Hubs, Kenya",
        "Cell / WhatsApp: 0724233767",
        "Email: ruth.njaramba@radioafricagroup.co.ke",
    ]
    return "\n".join(lines)


def build_followup_prompt(row: dict) -> str:
    org_name = row.get("Organization_Name", "").strip()
    category = row.get("Category", "").strip()
    contact_name = row.get("Contact_Name", "").strip()
    role = row.get("Role", "").strip()
    email = row.get("Contact_Email", "").strip()
    last_contacted = row.get("Last_Contacted_Date", "").strip()
    routing_angles = get_radio_africa_routing(category)
    salutation = f"Dear {contact_name}," if contact_name else f"Dear {role or 'Managing Director / Principal'},"

    lines = [
        "You are a senior B2B commercial account executive at Radio Africa Group in Nairobi, Kenya.",
        f"Write a polite, concise 30-day follow-up email (Touch #2) to a Kenyan organization that has not yet replied to our initial outreach sent on {last_contacted}.",
        "",
        "Target Details:",
        f"- Organization Name: {org_name}",
        f"- Sector / Category: {category}",
        f"- Contact Name: {contact_name or 'Not specified'}",
        f"- Role: {role or 'Executive Leadership'}",
        f"- Recipient Email: {email}",
        f"- Recommended Radio Africa Group Media Angles: {routing_angles}",
        "",
        "Strict Requirements:",
        "1. Format the top clearly with:",
        f"   To: {email}",
        f"   Subject: Following up: Radio Africa Group & The Star / MyGov partnership for {org_name}",
        f'2. Open with "{salutation}"',
        "3. Keep it brief and respectful of their time (110-150 words). Briefly reference our note from last month without sounding pushy.",
        "4. Reiterate one high-value reason to connect now (e.g., upcoming MyGov statutory/tender notice deadlines or seasonal broadcast campaign windows on Classic 105 / Kiss 100 / Radio Jambo).",
        "5. Offer to share our latest MyGov & commercial rate card via email or WhatsApp, or jump on a quick 10-minute call.",
        "6. Use this exact signature block verbatim:",
        "Warm regards,",
        "",
        "Ruth Njaramba",
        "Direct Commercial & Institutional Accounts Lead",
        "Radio Africa Group | The Star / MyGov",
        "Nairobi & Regional Hubs, Kenya",
        "Cell / WhatsApp: 0724233767",
        "Email: ruth.njaramba@radioafricagroup.co.ke",
    ]
    return "\n".join(lines)


def generate_with_failover(prompt: str) -> tuple[str | None, bool]:
    quota_exhausted_count = 0

    for model_name in MODEL_CHAIN:
        for attempt in range(1, 3):
            try:
                print(f"  [Gemini] Requesting {model_name} (attempt {attempt}/2)...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = (response.text or "").strip()
                if text:
                    print(f"  [Gemini] Success with {model_name}.")
                    return text, False
            except APIError as err:
                status_code = getattr(err, "code", None)
                err_msg = str(err)
                print(f"  [Gemini] {model_name} APIError (code={status_code}): {err_msg[:160]}")

                if status_code == 429 or "RESOURCE_EXHAUSTED" in err_msg:
                    quota_exhausted_count += 1
                    break

                if status_code in (500, 502, 503, 504) or "UNAVAILABLE" in err_msg:
                    if attempt == 1:
                        time.sleep(5)
                        continue
                    print(f"  [Gemini] {model_name} congested (503). Failing over to next model...")
                    break

                break
            except Exception as exc:
                print(f"  [Gemini] Unexpected error on {model_name}: {exc}")
                if attempt == 1:
                    time.sleep(5)
                    continue
                break

    if quota_exhausted_count >= len(MODEL_CHAIN):
        print("  [Gemini] All models reported 429 quota exhaustion. Halting batch cleanly.")
        return None, True

    print("  [Gemini] All models temporarily unavailable for this lead. Skipping for now.")
    return None, False


def save_csv(fieldnames: list[str], rows: list[dict]) -> None:
    with open(CSV_PATH, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Could not find {CSV_PATH}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(CSV_PATH, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or [
            "Organization_Name",
            "Category",
            "Contact_Name",
            "Role",
            "Contact_Email",
            "Website_Domain",
            "Status",
            "Outreach_Count",
            "Last_Contacted_Date",
        ]
        rows = list(reader)

    followup_indices = []
    pending_indices = []

    for idx, row in enumerate(rows):
        status = (row.get("Status") or "").strip()
        if status == "Touched_1":
            elapsed = days_since(row.get("Last_Contacted_Date", ""))
            if elapsed >= FOLLOW_UP_DAYS:
                followup_indices.append(idx)
        elif status == "Pending":
            pending_indices.append(idx)

    print(
        f"Queue summary: {len(followup_indices)} eligible for 30-day follow-up (Touched_2), "
        f"{len(pending_indices)} Pending for initial outreach (Touched_1)."
    )

    selected_tasks = []
    for idx in followup_indices:
        if len(selected_tasks) >= MAX_LEADS_PER_RUN:
            break
        selected_tasks.append((idx, "FOLLOWUP"))

    for idx in pending_indices:
        if len(selected_tasks) >= MAX_LEADS_PER_RUN:
            break
        selected_tasks.append((idx, "INITIAL"))

    if not selected_tasks:
        print("No eligible leads to process today. Exiting cleanly.")
        return

    today_str = get_today_str()
    processed_count = 0

    for task_num, (idx, touch_type) in enumerate(selected_tasks, start=1):
        row = rows[idx]
        org_name = (row.get("Organization_Name") or "Unknown").strip()
        print(f"\n[{task_num}/{len(selected_tasks)}] Processing {org_name} ({touch_type})...")

        if touch_type == "INITIAL":
            row = enrich_contact_via_apollo(row)
            rows[idx] = row

        contact_email = (row.get("Contact_Email") or "").strip()
        if not contact_email:
            print(f"  [Skip] No valid Contact_Email available for {org_name}. Leaving row unchanged.")
            continue

        prompt = build_followup_prompt(row) if touch_type == "FOLLOWUP" else build_first_touch_prompt(row)
        pitch_text, should_abort = generate_with_failover(prompt)

        if should_abort:
            print("Stopping run early due to quota exhaustion. Progress so far has been saved.")
            break

        if not pitch_text:
            print(f"  [Defer] Could not generate pitch for {org_name} right now; leaving status unchanged for next run.")
            continue

        touch_label = "touch2_followup" if touch_type == "FOLLOWUP" else "touch1_initial"
        filename = f"{today_str}_{touch_label}_{sanitize_filename(org_name)}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, mode="w", encoding="utf-8") as out_f:
            out_f.write(pitch_text + "\n")

        current_count = int((row.get("Outreach_Count") or "0").strip() or "0")
        if touch_type == "FOLLOWUP":
            row["Status"] = "Touched_2"
            row["Outreach_Count"] = str(max(current_count + 1, 2))
        else:
            row["Status"] = "Touched_1"
            row["Outreach_Count"] = str(max(current_count + 1, 1))

        row["Last_Contacted_Date"] = today_str
        rows[idx] = row

        save_csv(fieldnames, rows)
        processed_count += 1
        print(f"  [Saved] {org_name} -> {row['Status']} ({filepath})")

        if task_num < len(selected_tasks):
            time.sleep(PACING_DELAY_SECONDS)

    print(f"\nRun complete. Successfully generated {processed_count} pitch(es).")


if __name__ == "__main__":
    main()
