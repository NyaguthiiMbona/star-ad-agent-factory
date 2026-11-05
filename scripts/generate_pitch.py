import csv
from datetime import datetime
import os
import time
from google import genai

# Configuration
CSV_PATH = "data/targets.csv"
OUTPUT_DIR = "generated_pitches"
MODEL_NAME = "gemini-3.8-flash"
MAX_BATCH_SIZE = 10  # Capped at maximum 10 emails per run

# Sector Mapping & Pitch Angles
SECTOR_ANGLES = {
    "Agriculture, Climate & Rural Development": (
        "Angle A: Agriculture, Climate & Rural Development"
    ),
    "Health, Education & Social Impact": (
        "Angle B: Health, Education & Social Impact"
    ),
    "Public Diplomacy, Soft Power & Civic Governance": (
        "Angle C: Public Diplomacy, Soft Power & Civic Governance"
    ),
}


def get_pitch_angle(category):
  cat_lower = category.lower()
  if any(
      k in cat_lower
      for k in ["agri", "climate", "food", "environment", "rural", "water"]
  ):
    return SECTOR_ANGLES["Agriculture, Climate & Rural Development"]
  elif any(
      k in cat_lower for k in ["health", "edu", "humanitarian", "social", "child"]
  ):
    return SECTOR_ANGLES["Health, Education & Social Impact"]
  else:
    return SECTOR_ANGLES["Public Diplomacy, Soft Power & Civic Governance"]


def discover_new_prospects(client, existing_orgs):
  """Scouts fresh international NGOs, regional bodies, and donor-funded agencies operating in Kenya."""
  print(
      "Scouting for fresh international NGOs, regional bodies, and donor-funded"
      " agencies operating in Kenya..."
  )
  prompt = """
    Identify 5 active international organizations, regional development bodies, UN specialized agencies, donor-funded agricultural/health/climate projects, or major INGOs operating regional offices in Kenya (e.g., USAID/FCDO/GIZ implementing partners, CGIAR centers, FAO, AGRA, TradeMark Africa, or similar entities) that require public stakeholder engagement, policy dissemination, or grassroots awareness campaigns across Kenya.
    
    Return ONLY a valid CSV format (without markdown code blocks) with these exact headers:
    Organization_Name,Category,Contact_Email,Status,Outreach_Count,Last_Contacted_Date
    
    Ensure realistic institutional domain emails (e.g., communications@, info@, partnerships@ domain), and make sure they are distinct from these already known organizations:
    """ + ", ".join(
      list(existing_orgs)[:20]
  )

  try:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    text = response.text.strip()
    if text.startswith("```"):
      text = text.split("```")[1]
      if text.startswith("csv"):
        text = text[3:].strip()

    reader = csv.DictReader(text.splitlines())
    new_rows = []
    for row in reader:
      org_name = row.get("Organization_Name", "").strip()
      if org_name and org_name not in existing_orgs:
        new_rows.append({
            "Organization_Name": org_name,
            "Category": row.get(
                "Category", "Public Diplomacy, Soft Power & Civic Governance"
            ).strip(),
            "Contact_Email": row.get(
                "Contact_Email", "partnerships@organization.org"
            ).strip(),
            "Status": "Pending",
            "Outreach_Count": "0",
            "Last_Contacted_Date": "",
        })
    return new_rows
  except Exception as e:
    print(f"Discovery scraping error: {e}")
    return []


def main():
  os.makedirs(OUTPUT_DIR, exist_ok=True)
  client = genai.Client()

  rows = []
  fieldnames = [
      "Organization_Name",
      "Category",
      "Contact_Email",
      "Status",
      "Outreach_Count",
      "Last_Contacted_Date",
  ]

  if os.path.exists(CSV_PATH):
    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
      reader = csv.DictReader(f)
      if reader.fieldnames:
        fieldnames = reader.fieldnames
      for row in reader:
        rows.append(row)

  existing_orgs = {r.get("Organization_Name") for r in rows}

  # If pending list is low, trigger discovery agent
  pending_rows = [r for r in rows if r.get("Status", "Pending") == "Pending"]
  if len(pending_rows) < 5:
    scouted = discover_new_prospects(client, existing_orgs)
    if scouted:
      rows.extend(scouted)
      print(f"Discovered and added {len(scouted)} new prospects to database.")

  today = datetime.now().date()
  processed_count = 0

  # Categorize targets into execution queues
  # Queue 1: Follow-ups due (Touched_1 and >= 30 days since last contact)
  # Queue 2: Fresh new leads (Pending)
  follow_up_queue = []
  fresh_queue = []

  for row in rows:
    status = row.get("Status", "Pending").strip()
    last_contacted_str = row.get("Last_Contacted_Date", "").strip()

    if status == "Touched_1" and last_contacted_str:
      try:
        last_date = datetime.strptime(last_contacted_str, "%Y-%m-%d").date()
        days_since = (today - last_date).days
        if days_since >= 30:
          follow_up_queue.append(row)
      except ValueError:
        pass
    elif status == "Pending":
      fresh_queue.append(row)

  # Combine execution list prioritizing follow-ups first, then filling remaining slots with fresh leads
  execution_list = follow_up_queue + fresh_queue

  for row in execution_list:
    if processed_count >= MAX_BATCH_SIZE:
      print(f"Reached maximum batch limit of {MAX_BATCH_SIZE} pitches for this run.")
      break

    org_name = row.get("Organization_Name", "").strip()
    category = row.get("Category", "General B2B").strip()
    status = row.get("Status", "Pending").strip()
    outreach_count = int(row.get("Outreach_Count", 0) or 0)
    angle = get_pitch_angle(category)

    is_follow_up = status == "Touched_1"

    if is_follow_up:
      print(
          f"[{processed_count + 1}/{MAX_BATCH_SIZE}] Generating Touch 2 Follow-Up"
          f" for {org_name}..."
      )
      prompt = f"""
      You are an expert B2B media sales director for The Star newspaper in Kenya (focusing on the high-impact MyGov national pullout).
      Write a polite, concise, and respectful second-touch follow-up email to the Communications or Partnerships Officer at {org_name} ({category} sector).
      
      The first pitch was sent ~4 weeks ago. This follow-up should politely bump the conversation, acknowledge their busy schedule, and reiterate how partnering with The Star satisfies donor requirements for grassroots policy dissemination and public awareness across Kenya under strategic angle: {angle}.
      
      CRITICAL FORMAT REQUIREMENT:
      Provide a professional, peer-to-peer subject line (e.g., focusing on grassroots reach, stakeholder engagement, or public awareness for {org_name}) followed by a short, courteous email body.
      
      Format your response cleanly with:
      Subject: [Compelling Institutional Subject Line]
      
      [Email Body - Short, professional follow-up with a clear call to action]
      """
    else:
      print(
          f"[{processed_count + 1}/{MAX_BATCH_SIZE}] Generating Initial Pitch"
          f" (Touch 1) for {org_name} using [{angle}]..."
      )
      prompt = f"""
      You are an expert B2B media sales director for The Star newspaper in Kenya (focusing on the high-impact MyGov national pullout).
      Write a tailored, professional, and respectful B2B partnership pitch email to the Communications or Partnerships Officer at {org_name}, which operates in the '{category}' sector.
      
      The pitch must align with this strategic angle: {angle}.
      Emphasize institutional visibility, donor compliance, public participation, and nationwide grassroots reach across Kenya through The Star's platform rather than generic commercial advertising.
      
      CRITICAL FORMAT REQUIREMENT:
      Provide a clean, non-spammy subject line that highlights public outreach, regional impact, or community engagement for {org_name}.
      
      Format your response cleanly with:
      Subject: [Compelling Institutional Subject Line]
      
      [Email Body - Professional, concise, peer-to-peer B2B pitch focusing on institutional reach and compliance, with a clear call to action]
      """

    # Retry logic for 503 high demand errors
    success = False
    max_retries = 3
    pitch_content = ""

    for attempt in range(max_retries):
      try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        pitch_content = response.text
        success = True
        break
      except Exception as e:
        print(f"Attempt {attempt + 1} failed for {org_name}: {e}")
        if attempt < max_retries - 1:
          time.sleep(5 * (attempt + 1))
        else:
          print(f"Skipping {org_name} after {max_retries} failed attempts.")

    if success:
      safe_filename = "".join(
          c if c.isalnum() else "_" for c in org_name
      ).lower()
      if not safe_filename:
        safe_filename = f"target_{processed_count + 1}"

      touch_label = "followup_touch2" if is_follow_up else "pitch_touch1"
      file_path = os.path.join(OUTPUT_DIR, f"{touch_label}_{safe_filename}.md")

      with open(file_path, "w", encoding="utf-8") as out_f:
        out_f.write(
            f"# {'Follow-Up' if is_follow_up else 'Pitch'} Draft for"
            f" {org_name}\n\n"
        )
        out_f.write(f"**Stage:** {'Touch 2 (Follow-Up)' if is_follow_up else 'Touch 1 (Initial Pitch)'}\n")
        out_f.write(f"**Target Contact:** {row.get('Contact_Email', 'N/A')}\n")
        out_f.write(f"**Target Category:** {category}\n")
        out_f.write(f"**Assigned Angle:** {angle}\n")
        out_f.write(f"**Generated On:** {today}\n\n---\n\n")
        out_f.write(pitch_content)

      # Update tracking status
      if is_follow_up:
        row["Status"] = "Touched_2"
      else:
        row["Status
