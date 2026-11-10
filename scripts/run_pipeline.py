import os
import csv
import time
from datetime import datetime
from google import genai
from google.genai.errors import ServerError

client = genai.Client()

TARGETS_FILE = "data/targets.csv"
PITCH_DIR = "generated_pitches"

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
    fieldnames = ["Organization_Name", "Category", "Contact_Email", "Status", "Outreach_Count", "Last_Contacted_Date"]
    with open(TARGETS_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(targets)

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

def generate_pitch(org_name, category):
    prompt = f"""
    You are a strategic B2B account manager at Radio Africa Group (RAG) pitching to {org_name} (Category: {category}).
    
    Structure a high-conversion cold email pitch emphasizing:
    1. THE ANCHOR: The Star's official MyGov pullout for high-level policy compliance, institutional transparency, and official donor reporting.
    2. TAILORED BROADCAST ASSETS BASED ON SECTOR:
       - If Category is 'Agriculture & Climate': Highlight Radio Jambo (mass Swahili rural reach) and Gukena FM for grassroots farming and rural community engagement.
       - If Category is 'Health & Social Impact': Highlight Kiss 100 for broad urban youth/young adult mobilization alongside Radio Jambo for wide-reaching community public health messaging.
       - If Category is 'Civic Governance & Trade': Highlight The Star MyGov pullout anchor combined with Classic 105 and East FM for high-net-worth policy stakeholders and decision-makers.
    3. AGENCY ROUTING CLAUSE: Politely note that if their public notices, media buys, or advocacy campaigns in Kenya are managed via a retained media buying/PR agency (e.g., WPP Scangroup, Dentsu, Ogilvy, Redhouse), we welcome connecting directly with their account direction team to supply official institutional rate cards.
    
    Keep the tone professional, institutional, and focused on donor impact.
    Provide a Subject Line and Email Body.
    """
    response = call_gemini_with_retry(model='gemini-3.8-flash', contents=prompt)
    return response.text

def main():
    print("Starting pipeline execution...")
    os.makedirs(PITCH_DIR, exist_ok=True)
    targets = load_targets()
    print(f"Loaded {len(targets)} targets from CSV.")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    processed = 0
    BATCH_LIMIT = 2  # Keeps execution well within limits
    
    for t in targets:
        if t["Status"] == "Pending" and processed < BATCH_LIMIT:
            print(f"[{processed+1}/{BATCH_LIMIT}] Generating sector-tailored pitch for: {t['Organization_Name']}...")
            
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
            print(f"Saved: {filename}")
            
    save_targets(targets)
    print(f"Pipeline finished! Successfully generated {processed} pitch(es).")

if __name__ == "__main__":
    main()
