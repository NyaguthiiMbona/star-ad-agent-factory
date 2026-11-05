import csv
import os
import time
from google import genai
from google.genai import types

def load_prompt(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def generate_pitches():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    client = genai.Client(api_key=api_key)
    copywriter_persona = load_prompt("prompts/copywriter.md")

    targets_file = "data/targets.csv"
    if not os.path.exists(targets_file):
        print("Targets file not found.")
        return

    output_dir = "generated_pitches"
    os.makedirs(output_dir, exist_ok=True)

    # Official Sender Contact Details
    sender_name = "Ruth Njaramba"
    sender_title = "The Star Publications & Mgazeti"
    sender_company = "Radio Africa Group"
    sender_email = "ruth.njaramba@radioafricagroup.co.ke"
    sender_phone = "0724233767"

    with open(targets_file, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        count = 0

        for row in reader:
            count += 1
            org_name = row['Organization']
            contact_name = row['Contact_Name']
            category = row['Category']
            campaign_focus = row['Campaign_Focus']
            location = row['Location']
            is_international = "Kenya" not in location

            print(f"[{count}/100] Generating email draft for: {org_name} ({location})...")

            location_context = (
                "Highlight direct soft power outreach, national visibility, and grassroots public policy communication "
                "to all 47 counties without requiring a physical local office footprint."
                if is_international else
                "Emphasize reaching off-grid rural communities, local county government officials, and grassroots leaders "
                "beyond urban digital paywalls in Nairobi."
            )

            user_prompt = f"""
            Target Organization: {org_name}
            Location/Base: {location}
            Category: {category}
            Contact Person: {contact_name}
            Campaign Focus: {campaign_focus}

            Strategic Context for this target:
            {location_context}

            Sender Contact Information for Signature:
            Name: {sender_name}
            Role/Title: {sender_title} ({sender_company})
            Email: {sender_email}
            Phone/WhatsApp: {sender_phone}

            Task: Write a concise, professional cold sales pitch email (Subject line + Body) targeting {contact_name}.
            Emphasize that every Tuesday, 100,000 physical copies of The Star Newspaper (featuring the official government MyGov pullout)
            are distributed across all 47 sub-counties of Kenya. Sign off using the exact provided sender contact details.
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

                email_content = response.text

                safe_filename = "".join([c if c.isalnum() else "_" for c in org_name.lower()])
                filename = os.path.join(output_dir, f"{count:03d}_{safe_filename}.md")

                with open(filename, "w", encoding="utf-8") as out_file:
                    out_file.write(f"# Pitch for {org_name}\n\n")
                    out_file.write(f"**Target Email:** {row['Email']}\n")
                    out_file.write(f"**Location:** {location}\n\n")
                    out_file.write("----\n\n")
                    out_file.write(email_content)

                print(f" Done! Saved to {filename}")

                time.sleep(1)

            except Exception as e:
                print(f" Failed to generate pitch for {org_name}: {e}")

if __name__ == "__main__":
    generate_pitches()
