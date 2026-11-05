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
  """Uses Gemini to scout fresh local and international B2B prospects operating in Kenya."""
  print(
      "Scouting for fresh local and international prospects (NGOs, Agencies,"
      " Enterprises)..."
  )
  prompt = """
    Identify 5 active international organizations, NGOs, or major commercial enterprises operating in Kenya (including local enterprises or international bodies like UN agencies, USAID partners, or agricultural/health firms) that would benefit from advertising in a major national media outlet like The Star's MyGov pullout.
    Return ONLY a valid CSV format (without markdown code blocks) with these exact headers:
    Organization_Name,Category,Contact_Email,Status,Outreach_Count,Last_Contacted_Date
    Ensure realistic placeholder emails or public contact domains, and make sure they are distinct from these already known organizations:
    """ + ", ".join(
      list(existing_orgs)[:20]
  )

  try:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    text = response.text.strip()
    # Clean potential markdown block wrappers
    if text.startswith("```"):
      text = text.split("```")[1]
      if text.startswith("csv"):
        text = text[3:].strip()

    reader = csv.DictReader(text.splitlines())
    new_rows = []
    for row in reader:
      if row.get("Organization_Name") and row.get(
          "Organization_Name"
      ) not in existing_orgs:
        new_rows.append({
            "Organization_Name": row["Organization_Name"].strip(),
            "Category": row.get("Category", "General B2B").strip(),
            "Contact_Email": row.get(
                "Contact_Email", "info@organization.org"
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

  # 1. Read existing targets
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

  # 2. If pending list is low, trigger discovery agent to scrape/scout fresh leads
  pending_rows = [r for r in rows if r.get("Status", "Pending") == "Pending"]
  if len(pending_rows) < 5:
    scouted = discover_new_prospects(client, existing_orgs)
    if scouted:
      rows.extend(scouted)
      print(f"Discovered and added {len(scouted)} new prospects to database.")

  today = datetime.now().date()
  processed_count = 0

  # 3. Process batch up to MAX_BATCH_SIZE (10 targets max)
  for row in rows:
    if processed_count >= MAX_BATCH_SIZE:
      print(f"Reached maximum batch limit of {MAX_BATCH_SIZE} pitches for this run.")
      break

    status = row.get("Status", "Pending").strip()
    if status != "Pending":
      continue  # Skip already contacted or on cooldown

    org_name = row.get("Organization_Name", "").strip()
    category = row.get("Category", "General B2B").strip()
    outreach_count = int(row.get("Outreach_Count", 0) or 0)

    angle = get_pitch_angle(category)
    print(
        f"[{processed_count + 1}/{MAX_BATCH_SIZE}] Generating pitch for"
        f" {org_name} using [{angle}]..."
    )

    prompt = f"""
    You are an expert B2B media sales director for The Star newspaper in Kenya (focusing on the high-impact MyGov national pullout).
    Write a tailored, professional, and respectful B2B partnership pitch email to {org_name}, which operates in the '{category}' sector.
    
    The pitch must align with this strategic angle: {angle}.
    Emphasize national reach, institutional visibility, and audience engagement across Kenya through The Star's platform.
    
    Format your response cleanly with:
    Subject: [Compelling Subject Line]
    
    [Email Body - Professional, concise, punchy B2B pitch with a clear call to action]
    """

    # 3-tier exponential backoff retry logic for 503 high demand errors
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

      file_path = os.path.join(OUTPUT_DIR, f"pitch_{safe_filename}.md")

      with open(file_path, "w", encoding="utf-8") as out_f:
        out_f.write(f"# Pitch Draft for {org_name}\n\n")
        out_f.write(f"**Target Contact:** {row.get('Contact_Email', 'N/A')}\n")
        out_f.write(f"**Target Category:** {category}\n")
        out_f.write(f"**Assigned Angle:** {angle}\n")
        out_f.write(f"**Generated On:** {today}\n\n---\n\n")
        out_f.write(pitch_content)

      row["Status"] = "Touched_1" if outreach_count == 0 else "Touched_2"
      row["Outreach_Count"] = str(outreach_count + 1)
      row["Last_Contacted_Date"] = today.strftime("%Y-%m-%d")
      processed_count += 1

    time.sleep(3)  # Rate limiting pause

  # 4. Save updated targets back to CSV
  with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

  print(
      f"Pipeline run completed. Generated {processed_count} pitch drafts and"
      " updated targets.csv."
  )


if __name__ == "__main__":
  main()
