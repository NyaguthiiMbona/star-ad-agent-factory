import csv
from datetime import datetime
import os
import time
from google import genai

# Configuration
CSV_PATH = "data/targets.csv"
OUTPUT_DIR = "generated_pitches"
MODEL_NAME = "gemini-3.8-flash"  # Updated to current model identifier

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


def main():
  if not os.path.exists(CSV_PATH):
    print(f"Error: Could not find target database at {CSV_PATH}")
    return

  os.makedirs(OUTPUT_DIR, exist_ok=True)

  # Initialize Gemini Client using official google-genai library
  client = genai.Client()

  # Read targets CSV
  rows = []
  with open(CSV_PATH, mode="r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
      rows.append(row)

  today = datetime.now().date()
  updated_count = 0

  for row in rows:
    org_name = row.get("Organization_Name", "").strip()
    status = row.get("Status", "Pending").strip()
    category = row.get("Category", "").strip()
    last_contacted_str = row.get("Last_Contacted_Date", "").strip()
    outreach_count = int(row.get("Outreach_Count", 0) or 0)

    # Check 30-day cooldown if already contacted
    if status != "Pending" and last_contacted_str:
      try:
        last_date = datetime.strptime(last_contacted_str, "%Y-%m-%d").date()
        days_since = (today - last_date).days
        if days_since < 30:
          print(f"Skipping {org_name}: on cooldown ({days_since} days elapsed).")
          continue
      except ValueError:
        pass  # Date parsing fallback if format is unexpected

    # Select angle
    angle = get_pitch_angle(category)
    print(f"Generating pitch for {org_name} using [{angle}]...")

    # Build prompt for Gemini
    prompt = f"""
    You are an expert B2B media sales director for The Star newspaper in Kenya (focusing on the high-impact MyGov national pullout).
    Write a tailored, professional, and respectful B2B partnership pitch email to {org_name}, which operates in the '{category}' sector.
    
    The pitch must align with this strategic angle: {angle}.
    Emphasize national reach, institutional visibility, and audience engagement across Kenya through The Star's platform.
    
    Format your response cleanly with:
    Subject: [Compelling Subject Line]
    
    [Email Body - Professional, concise, punchy B2B pitch with a clear call to action]
    """

    try:
      response = client.models.generate_content(
          model=MODEL_NAME,
          contents=prompt,
      )
      pitch_content = response.text

      # Save to markdown file
      safe_filename = "".join(
          c if c.isalnum() else "_" for c in org_name
      ).lower()
      file_path = os.path.join(OUTPUT_DIR, f"pitch_{safe_filename}.md")

      with open(file_path, "w", encoding="utf-8") as out_f:
        out_f.write(f"# Pitch Draft for {org_name}\n\n")
        out_f.write(f"**Target Category:** {category}\n")
        out_f.write(f"**Assigned Angle:** {angle}\n")
        out_f.write(f"**Generated On:** {today}\n\n---\n\n")
        out_f.write(pitch_content)

      # Update tracking status in CSV data
      row["Status"] = "Touched_1" if outreach_count == 0 else "Touched_2"
      row["Outreach_Count"] = str(outreach_count + 1)
      row["Last_Contacted_Date"] = today.strftime("%Y-%m-%d")
      updated_count += 1

      # Rate limiting pause between API requests
      time.sleep(2)

    except Exception as e:
      print(f"Failed for {org_name}: {e}")

  # Write back updated rows to CSV
  if updated_count > 0:
    with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
      writer = csv.DictWriter(f, fieldnames=fieldnames)
      writer.writeheader()
      writer.writerows(rows)
    print(
        f"Successfully generated {updated_count} pitches and updated"
        " targets.csv!"
    )
  else:
    print("No new pitches generated (all targets skipped or on cooldown).")


if __name__ == "__main__":
  main()
