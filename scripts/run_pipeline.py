import os
import csv
import time
import requests
from datetime import datetime
from google import genai
from google.genai.errors import ServerError

# Initialize Gemini Client
client = genai.Client()

TARGETS_FILE = "data/targets.csv"
PITCH_DIR = "generated_pitches"
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")

def load_targets():
    """Loads target entities from data/targets.csv safely handling variable column lengths."""
    targets = []
    if not os.path.exists(TARGETS_FILE):
        print(f"File not found: {TARGETS_FILE}")
        return targets
        
    with open(TARGETS_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return targets
            
        header = [h.strip() for h in header]
        
        for row in reader:
            if not row or not any(row):
                continue
            row_padded = row + [''] * (len(header) - len(row))
            target_dict = dict(zip(header, row_padded))
            
            for key in ["Organization_Name", "Category", "Contact_Name", "Role", "Contact_Email", "Website_Domain", "Status", "Outreach_Count", "Last_Contacted_Date"]:
                if key not in target_dict:
                    target_dict[key] = ""
                    
            targets.append(target_dict)
            
    return targets

def save_targets(targets):
    """Saves updated targets back to data/targets.csv with complete 9 headers."""
    fieldnames = [
        "Organization_Name", "Category", "Contact_Name", "Role", 
        "Contact_Email", "Website_Domain", "Status", "Outreach_Count", "Last_Contacted_Date"
    ]
    with open(TARGETS_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(targets)

def enrich_decision_maker_apollo(domain):
    """Queries Apollo.io API with a strict 10-second timeout."""
    if not APOLLO_API_KEY or not domain:
        return None, None, None

    url = "https://api.apollo.io/v1/people/search"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "api_key": APOLLO_API_KEY
    }
    
    payload = {
        "q_organization_domains": domain,
        "person_titles": [
            "Managing Director", "MD", "CEO", "Chief Executive Officer", "Director", 
            "Principal", "Procurement Manager", "Head of Procurement", 
            "General Secretary", "Head"
        ],
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
    except requests.exceptions.Timeout:
        print(f"Apollo API timeout for domain {domain}. Skipping enrichment.")
    except Exception as err:
        print(f"Apollo API lookup warning for {domain}: {err}")
        
    return None, None, None

def call_gemini_with_retry(model, contents, retries=3, delay=5):
    """Calls the Gemini API with automatic retries and safety timeout protection."""
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except ServerError as e:
            if attempt < retries - 1:
                print(f"Server busy (503). Retrying in {delay}s... (Attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                raise e
        except Exception as e:
            if attempt < retries - 1:
                print(f"Gemini call error: {e}. Retrying in {delay}s... (Attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                raise e

def generate_pitch(org_name, category, contact_name="", role=""):
    """Constructs prompt and calls Gemini 3.8 Flash to write tailored B2B pitches."""
    greeting = f"Dear {contact_name}," if contact_name else "Dear Managing Director,"
    target_role = role if role else "Managing Director"
    
    prompt = f"""
    You are a strategic B2B sales representative at Radio Africa Group (RAG) pitching directly to decision-makers at {org_name} (Category: {category}).
    
    Opening Salutation: {greeting}
    Target Executive Title: {target_role}
    
    Structure a high-conversion B2B cold email pitch emphasizing:
    
    1. THE ANCHOR: The Star's official MyGov pullout for statutory notices, procurement disclosures, compliance, title deed/survey announcements, and donor transparency reporting.
    
    2. TAILORED BROADCAST ASSETS (ROUTED BY SECTOR & AUDIENCE):
       - If Category is 'Agro-Machinery & Spares' or 'Regional Heavy Equipment': Highlight Radio Jambo (mass Swahili rural/farmer reach) and Gukena FM for direct regional equipment sales, spares awareness, and service hub announcements in regional centers like Eldoret, Nakuru, and Kitale.
       - If Category is 'Land Sacco & Real Estate' or 'Investment Trust': Highlight The Star/MyGov for legal title deed issuance and statutory AGM notices, combined with Classic 105 and East FM for high-trust executive/diaspora investor reach.
       - If Category is 'TVET & Technical Education': Highlight Kiss 100 for high school leaver recruitment combined with Radio Jambo to reach fee-paying parents in rural and peri-urban regions.
       - If Category is 'Faith-Based Healthcare & Medical Networks': Highlight Radio Jambo for mass public health mobilization and free medical camp announcements, alongside MyGov for institutional donor reporting.
       - If Category is 'Agriculture & Climate' or 'Direct Research Hub': Highlight Radio Jambo for grassroots community advocacy alongside The Star MyGov pullout for official policy disclosures.
       - For all other categories: Select the optimal combination from Kiss 100, Classic 105, Radio Jambo, East FM, Homeboyz Radio, or Gukena FM based on their primary target demographic.
    
    3. AGENCY ROUTING CLAUSE (Option B Formulation): 
       Incorporate this precise positioning naturally into the email body:
       "Should {org_name}'s media scheduling and advertising campaigns be handled by a retained agency, please feel free to forward this to your account directors so we can supply our latest MyGov and commercial rate cards."
    
    4. SIGNATURE:
       End every pitch with this exact layout and your precise details:
       
       Warm regards,
       
       Ruth Njaramba
       Direct Commercial & Institutional Accounts Lead
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
    print("Starting pipeline execution with Bounced status check & timeouts...")
    os.makedirs(PITCH_DIR, exist_ok=True)
    targets = load_targets()
    print(f"Loaded {len(targets)} targets from CSV.")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    processed = 0
    BATCH_LIMIT = 7
    
    for t in targets:
        # Skip targets marked as Excluded, Agency Routed, Missing Contact, already Touched, or Bounced
        if t.get("Status") in ["Excluded", "Agency_Routed", "Excluded_Missing_Contact", "Touched_1", "Bounced"]:
            continue

        if t.get("Status") == "Pending" and processed < BATCH_LIMIT:
            email = t.get("Contact_Email", "").strip()
            domain = t.get("Website_Domain", "").strip()
            
            # Step A: Query Apollo for executive contact info
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

            # Step B: Fallback to domain email if Apollo returns no email string
            if not email and domain:
                email = f"info@{domain}"
                t["Contact_Email"] = email
                print(f"Apollo email not found for {domain}. Applying domain fallback: {email}")

            # Step C: Exclude only if missing both email and domain
            if not email and not domain:
                print(f"Excluding {t['Organization_Name']}: Missing both Contact_Email and Website_Domain.")
                t["Status"] = "Excluded_Missing_Contact"
                continue

            print(f"[{processed+1}/{BATCH_LIMIT}] Generating pitch for: {t['Organization_Name']} ({t['Category']})...")
            
            contact_name = t.get("Contact_Name", "").strip()
            contact_role = t.get("Role", "").strip() or "Managing Director"
            
            try:
                pitch_text = generate_pitch(
                    t["Organization_Name"], 
                    t["Category"], 
                    contact_name=contact_name, 
                    role=contact_role
                )
            except Exception as gen_err:
                print(f"Failed to generate pitch for {t['Organization_Name']}: {gen_err}")
                continue
            
            clean_filename = "".join(c for c in t["Organization_Name"] if c.isalnum() or c in (' ', '_')).rstrip()
            filename = os.path.join(PITCH_DIR, f"{clean_filename.replace(' ', '_')}_Pitch.md")
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# B2B Pitch: {t['Organization_Name']}\n")
                f.write(f"**Contact Name:** {contact_name or 'N/A'}\n")
                f.write(f"**Role:** {contact_role}\n")
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
