import os
import csv
import time
from datetime import datetime
from google import genai
from google.genai import types
from google.genai.errors import ServerError

# Initialize Gemini Client
client = genai.Client()

TARGETS_FILE = "data/targets.csv"
PITCH_DIR = "generated_pitches"

def load_targets():
    targets = []
    if not os.path.exists(TARGETS_FILE):
        return targets
    with open(TARGETS_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(row)
    return targets

def save_targets(targets):
    fieldnames = ["Organization_Name", "Category", "Contact_Email", "Status", "Outreach_Count", "Last_Contacted_Date"]
    with open(TARGETS_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(targets)

def call_gemini_with_retry(model, contents, retries=3, delay=5):
    """Wrapper function to handle temporary 503 high-demand errors seamlessly."""
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except ServerError as e:
            if attempt < retries - 1:
                print(f"Server busy (503). Retrying in {delay} seconds... (Attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                raise e

def discover_new_prospects(existing_names, count=5):
    prompt = f"""
    Act as a senior B2B media partnership scout for Radio Africa Group in Nairobi, Kenya.
    Identify {count} unique international NGOs, UN specialized agencies, regional development bodies, or donor-funded project implementers active in East Africa/Kenya.
    EXCLUDE traditional commercial parastatals (e.g., Kenya Power, Kenya Pipeline).
    EXCLUDE these already tracked entities: {', '.join(existing_names)}.
    
    Return EXACTLY {count} CSV rows formatted as:
    Organization_Name,Category,Contact_Email,Status,Outreach_Count,Last_Contacted_Date
    Ensure strings with commas are double-quoted. Status must be "Pending", Outreach_Count 0, Last_Contacted_Date empty.
    """
    response = call_gemini_with_retry(
        model='gemini-3.8-flash',
        contents=prompt
    )
    new_rows = []
    for line in response.text.strip().split('\n'):
        if line.startswith('Organization_Name') or not line.strip():
            continue
        try:
            reader = csv.DictReader([line], fieldnames=["Organization_Name", "Category", "Contact_Email", "Status", "Outreach_Count", "Last_Contacted_Date"])
            for row in reader:
                new_rows.append(row)
        except Exception:
            continue
    return new_rows

def generate_pitch(org_name, category):
    prompt = f"""
    You are a strategic B2B account manager at Radio Africa Group (RAG) pitching to {org_name} (Category: {category}).
    
    Structure a high-conversion cold email pitch emphasizing:
    1. THE ANCHOR: The Star's official MyGov pullout for high-level policy, compliance, institutional transparency, and donor reporting.
    2. THE OMNICHANNEL BUNDLE: Offer access to Radio Africa Group's broadcast network (Radio Jambo for mass Swahili rural reach, Classic 105 / Kiss 100 for urban reach, East FM, Homeboyz, or Gukena FM) for complete 360-degree grassroots community advocacy.
    3. AGENCY ROUTING CLAUSE: Politely note that if their public notices, media buys, or advocacy campaigns in Kenya are managed via a retained media buying/PR agency (e.g., WPP Scangroup, Dentsu, Ogilvy, Redhouse), we welcome connecting directly with their account direction team to supply official institutional rate cards.
    
    Keep the tone professional, institutional, and focused on donor impact.
    Provide a Subject Line and Email Body.
    """
    response = call_gemini_with_retry(
        model='gemini-3.8-flash',
        contents=prompt
    )
    return response.text

def main():
    os.makedirs(PITCH_DIR, exist_ok=True)
    targets = load_targets()
    
    pending_targets = [t for t in targets if t["Status"] == "Pending"]
    
    # Auto-scout if pending list is running low
    if len(pending_targets) < 5:
        existing_names = [t["Organization_Name"] for t in targets]
        new_leads = discover_new_prospects(existing_names, count=5)
        targets.extend(new_leads)
        save_targets(targets)
        pending_targets = [t for t in targets if t["Status"] == "Pending"]
    
    # Process up to 10 pitches per run
    processed = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for t in targets:
        if t["Status"] == "Pending" and processed < 10:
            pitch_text = generate_pitch(t["Organization_Name"], t["Category"])
            
            clean_filename = "".join(c for c in t["Organization_Name"] if c.isalnum() or c in (' ', '_')).rstrip()
            filename = os.path.join(PITCH_DIR, f"{clean_filename.replace(' ', '_')}_Pitch.md")
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# B2B Pitch: {t['Organization_Name']}\n")
                f.write(f"**Contact:** {t['Contact_Email']}\n")
                f.write(f"**Category:** {t['Category']}\n")
                f.write(f"**Generated:** {today_str}\n\n---\n\n")
                f.write(pitch_text)
                
            t["Status"] = "Touched_1"
            t["Outreach_Count"] = "1"
            t["Last_Contacted_Date"] = today_str
            processed += 1
            
    save_targets(targets)
    print(f"Pipeline executed successfully. Processed {processed} pitch(es).")

if __name__ == "__main__":
    main()
