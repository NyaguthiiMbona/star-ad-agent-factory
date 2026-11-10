import os
import csv
import time
import requests
from datetime import datetime
from google import genai
from google.genai.errors import ServerError

client = genai.Client()

TARGETS_FILE = "data/targets.csv"
PITCH_DIR = "generated_pitches"
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")

def load_targets():
    targets = []
    if not os.path.exists(TARGETS_FILE):
        print(f"File not found: {TARGETS_FILE}")
        return targets
    with open(TARGETS_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(row)
    return targets

def save_targets(targets):
    fieldnames = [
        "Organization_Name", "Category", "Contact_Name", "Role", 
        "Contact_Email", "Website_Domain", "Status", "Outreach_Count", "Last_Contacted_Date"
    ]
    with open(TARGETS_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(targets)

def enrich_decision_maker_apollo(domain):
    """Queries Apollo.io API to find executive decision-maker email and name for a domain."""
    if not APOLLO_API_KEY or not domain:
        return None, None, None

    url = "https://api.apollo.io/v1/people/search"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "api_key": APOLLO_API_KEY
    }
    
    # Search for decision-maker titles on the domain
    payload = {
        "q_organization_domains": domain,
        "person_titles": ["CEO", "Managing Director", "Director", "Principal", "Procurement Manager", "General Secretary", "Head"],
        "page": 1,
        "per_page": 5
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            people = data.get("people", [])
            for person in people:
                email = person.get("email")
                if email:
                    full_name = person.get("name", "").strip()
                    title = person.get("title", "").strip()
                    return email, full_name, title
    except Exception as err:
        print(f"Apollo API lookup warning for {domain}: {err}")
        
    return None, None, None

def call_gemini_with_retry(model, contents, retries=3, delay=5):
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except ServerError as e:
            if attempt < retries - 1:
                print(f"Server busy (503). Retrying in {delay}s... (Attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                raise e

def generate_pitch(org_name, category, contact_name="", role=""):
    greeting = f"Dear {contact_name}," if contact_name else "Dear Decision Maker,"
    
    prompt = f"""
    You are a strategic B2B sales representative at Radio Africa Group (RAG) pitching directly to decision-makers at {org_name} (Category: {category}).
    
    Opening Salutation: {greeting}
    
    Structure a high-conversion B2B cold email pitch emphasizing:
    
    1. THE ANCHOR: The Star's official MyGov pullout for statutory notices, procurement disclosures, compliance, title deed/survey announcements, and donor transparency reporting.
    
    2. TAILORED BROADCAST ASSETS (ROUTED BY SECTOR & AUDIENCE):
       - If Category is 'Agro-Machinery & Spares' or 'Regional Heavy Equipment': Highlight Radio Jambo (mass Swahili rural/farmer reach) and Gukena FM for direct regional equipment sales, spares awareness, and service hub announcements in regional centers like Eldoret, Nakuru, and Kitale.
       - If Category is 'Land Sacco & Real Estate' or 'Investment Trust': Highlight The Star/MyGov for legal title deed issuance and statutory AGM notices, combined with Classic 105 and East FM for high-trust executive/diaspora investor reach.
       - If Category is 'TVET & Technical Education': Highlight Kiss 100 for high school leaver recruitment combined with Radio Jambo to reach fee-paying parents in rural and peri-urban regions.
       - If Category is 'Faith-Based Healthcare & Medical Networks': Highlight Radio Jambo for mass public health mobilization and free medical camp announcements, alongside MyGov for institutional donor reporting.
       - If Category is 'Agriculture & Climate' or 'Direct Research Hub': Highlight Radio Jambo for grassroots community advocacy alongside The Star MyGov pullout for official policy disclosures.
       - For all other categories: Select the optimal combination from Kiss 100, Classic 105, Radio Jambo, East FM, Homeboyz Radio, or Gukena FM based on their primary target demographic.
    
    3. AGENCY ROUTING CLAUSE: Politely note that if their public notices, media buys, or marketing campaigns in Kenya are managed via a retained media buying/PR agency, we welcome connecting directly with their account direction team to supply official institutional rate cards.
    
    4. SIGNATURE:
       End every pitch with this exact layout and your precise details (adapt only the Functional Role line to match the sector relevance):
       
       Warm regards,
       
       Ruth Njaramba
       [Functional Role Line tailored to sector, e.g., Direct Commercial & Regional Accounts / Institutional Media Lead]
       Radio Africa Group | The Star / MyGov
       Nairobi & Regional Hubs, Kenya
       Cell / WhatsApp: 0724233767
       Email: ruth.njaramba@radioafricagroup.co.ke
    
    Keep the tone professional, direct, commercial, and focused on clear utility and return on investment.
    Provide a Subject Line and Email Body.
    """
    response = call_gemini_with_retry(model='gemini-3.8-flash', contents=prompt)
    return response.text

def main():
    print("Starting pipeline execution with Apollo.io enrichment & missing contact validation...")
    os.makedirs(PITCH_DIR, exist_ok=True)
    targets = load_targets()
    print(f"Loaded {len(targets)} targets from CSV.")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    processed = 0
    BATCH_LIMIT = 2
    
    for t in targets:
        if t.get("Status") in ["Excluded", "Agency_Routed", "Excluded_Missing_Contact"]:
            continue

        if t.get("Status") == "Pending" and processed < BATCH_LIMIT:
            email = t.get("Contact_Email", "").strip()
            domain = t.get("Website_Domain", "").strip()
            
            # Step A: Attempt Enrichment via Apollo if email is missing or generic and domain exists
            if (not email or email.startswith("info@") or email.startswith("sales@")) and domain:
                print(f"Enriching executive contact info for {domain} via Apollo.io...")
                found_email, found_name, found_role = enrich_decision_maker_apollo(domain)
                if found_email:
                    t["Contact_Email"] = found_email
                    if found_name:
                        t["Contact_Name"] = found_name
                    if found_role:
                        t["Role"] = found_role
                    email = found_email
                    print(f"Enriched: {found_email} ({found_name or 'N/A'}, {found_role or 'N/A'})")

            # Step B: Exclude records that still lack both email and domain
            if not email and not domain:
                print(f"Excluding {t['Organization_Name']}: Missing both Contact_Email and Website_Domain.")
                t["Status"] = "Excluded_Missing_Contact"
                continue

            print(f"[{processed+1}/{BATCH_LIMIT}] Generating pitch for: {t['Organization_Name']} ({t['Category']})...")
            
            pitch_text = generate_pitch(
                t["Organization_Name"], 
                t["Category"], 
                contact_name=t.get("Contact_Name", ""), 
                role=t.get("Role", "")
            )
            
            clean_filename = "".join(c for c in t["Organization_Name"] if c.isalnum() or c in (' ', '_')).rstrip()
            filename = os.path.join(PITCH_DIR, f"{clean_filename.replace(' ', '_')}_Pitch.md")
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# B2B Pitch: {t['Organization_Name']}\n")
                f.write(f"**Contact Name:** {t.get('Contact_Name', 'N/A')}\n")
                f.write(f"**Role:** {t.get('Role', 'N/A')}\n")
                f.write(f"**Contact Email:** {t.get('Contact_Email', 'N/A')}\n")
                f.write(f"**Category:** {t['Category']}\n")
                f.write(f"**Generated:** {today_str}\n\n---\n\n")
                f.write(pitch_text)
                
            t["Status"] = "Touched_1"
            t["Outreach_Count"] = "1"
            t["Last_Contacted_Date"] = today_str
            processed += 1
            print(f"Saved: {filename}")
            
    save_targets(targets)
    print(f"Pipeline finished! Successfully processed {processed} pitch(es).")

if __name__ == "__main__":
    main()
