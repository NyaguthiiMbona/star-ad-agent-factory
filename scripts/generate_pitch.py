import csv
import os
import time
from datetime import datetime, timedelta
from google import genai
from google.genai import types

def load_prompt(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def select_angle(category):
    """Maps DeepSeek's 14 normalized categories to optimal pitch angles."""
    cat = category.strip()
    
    # Angle A: Agriculture, Climate & Rural Development
    if cat in ["Agriculture", "Research"]:
        return "Angle A: Agriculture, Climate & Rural Development"
    
    # Angle B: Health, Education & Social Impact
    elif cat in ["Health", "Humanitarian", "Education/Culture", "Housing", "Sanitation"]:
        return "Angle B: Health, Education & Social Impact"
    
    # Angle C: Governance, Diplomacy, Energy & Economic Development
    else:
        return "Angle C: Public Diplomacy, Soft Power & Civic Governance"

def generate_pitches():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    client = genai.Client(api_key=api_key)
    copywriter_persona = load_prompt("prompts/copywriter.md")

    targets_file = "data/targets.csv"
    if not os.path.exists(targets_file):
        print("Error: targets.csv file not found.")
        return

    output_dir = "generated_pitches"
    os.makedirs(output_dir, exist_ok=True)

    sender_name = "Ruth Njaramba"
    sender_title = "The Star Publications & Mgazeti"
    sender_company = "Radio Africa Group"
    sender_email = "ruth.njaramba@radioafricagroup.co.ke"
    sender_phone = "0724233767"

    updated_rows = []
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    with open(targets_file, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames

        for row in reader:
            status = row.get("Status", "Pending")
            outreach_count = int(row.get("Outreach_Count", 0)) if row.get("Outreach_Count") else 0
            last_date_str = row.get("Last_Contacted_Date", "")

            # Evaluate 30-Day Cooldown Status
            in_cooldown = False
            if last_date_str:
                try:
                    last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
                    if (today - last_date) < timedelta(days=30):
                        in_cooldown = True
                except ValueError:
                    pass

            if status in ["Replied", "Won"]:
                print(f"Skipping {row['Organization']} (Status: {status})")
                updated_rows.append(row)
                continue

            if status == "Archived" and in_cooldown:
                days_left = 30 - (today - last_date).days
                print(f"Skipping {row['Organization']} - Active cooldown ({days_left} days remaining).")
                updated_rows.append(row)
                continue

            if status == "Archived" and not in_cooldown:
                print(f"Re-engaging {row['Organization']} - 30 days passed! Resetting for new pitch cycle.")
                status = "Pending"
                outreach_count = 0

            outreach_count += 1
            pitch_angle = select_angle(row.get("Category", ""))
            location_str = f"{row.get('City', '')}, {row.get('Country', '')}"

            if outreach_count == 1:
                pitch_type = f"INITIAL PITCH ({pitch_angle})"
                urgency_note = (
                    "Focus on reaching 100,000 physical copies distributed across all 47 sub-counties "
                    "via the Tuesday MyGov pullout, bridging rural and grassroots communication gaps."
                )
            else:
                pitch_type = f"FOLLOW-UP REMINDER ({pitch_angle})"
                urgency_note = (
                    "Create gentle urgency: Tuesday print bookings, artwork submission, and orders "
                    "must be finalized by Friday at 10:00 AM EAT."
                )

            print(f"[{outreach_count}/2] Generating pitch for {row['Organization']} using [{pitch_angle}]...")

            user_prompt = f"""
            Pitch Type: {pitch_type}
            Target Organization: {row['Organization']}
            Location: {location_str}
            Category: {row['Category']}
            Contact Person: {row['Contact_Name']}
            Campaign Focus: {row['Campaign_Focus']}

            Selected Sector Angle: {pitch_angle}
            Campaign Urgency / Context: {urgency_note}

            Sender Signature Details:
            {sender_name} | {sender_title} ({sender_company})
            Email: {sender_email} | Phone: {sender_phone}

            Task: Write a highly tailored, professional B2B cold sales pitch email (Subject line + Body) targeting {row['Contact_Name']}. 
            Apply the specified Sector Angle and end with the exact provided sender signature.
            """

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=copywriter_persona,
                        temperature=0.7,
                    )
                )

                safe_filename = "".join([c if c.isalnum() else "_" for c in row['Organization'].lower()])
                filename = os.path.join(output_dir, f"touch{outreach_count}_{safe_filename}.md")

                with open(filename, "w", encoding="utf-8") as out_file:
                    out_file.write(f"# Touch #{outreach_count} Pitch for {row['Organization']}\n\n")
                    out_file.write(f"**Target Email:** {row['Email']}\n")
                    out_file.write(f"**Sector Angle:** {pitch_angle}\n")
                    out_file.write(f"**Generated On:** {today_str}\n\n")
                    out_file.write("----\n\n")
                    out_file.write(response.text)

                row["Outreach_Count"] = str(outreach_count)
                row["Last_Contacted_Date"] = today_str
                row["Status"] = "Touched_1" if outreach_count == 1 else "Archived"

                print(f" Done! Pitch saved to {filename}")
                time.sleep(1)

            except Exception as e:
                print(f" Failed for {row['Organization']}: {e}")

            updated_rows.append(row)

    with open(targets_file, mode="w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

if __name__ == "__main__":
    generate_pitches()
