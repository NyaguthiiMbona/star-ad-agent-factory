import csv
import os

def load_prompt(filepath):
    with open(filepath, 'r') as f:
        return f.read()

def generate_pitches():
    copywriter_persona = load_prompt("prompts/copywriter.md")
    
    if not os.path.exists("data/targets.csv"):
        print("Targets file not found.")
        return

    with open("data/targets.csv", mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        count = 0
        for row in reader:
            count += 1
            is_international = "Kenya" not in row['Location']
            
            print(f"==================================================")
            print(f"[{count}/100] Pitching: {row['Organization']} ({row['Location']})")
            print(f"==================================================")
            
            # Context switch for international vs local targets
            if is_international:
                angle = "Direct soft power & public campaign reach to 47 Kenyan counties without needing local branch setup."
            else:
                angle = "Nationwide physical print reach beyond Nairobi to off-grid rural communities."
            
            print(f"Dear {row['Contact_Name']},\n")
            print(f"I noticed {row['Organization']} focuses on {row['Campaign_Focus']}.")
            print(f"Angle applied: {angle}")
            print(f"Distribution Fact: Every Tuesday, 100,000 physical copies of The Star (with MyGov) hit all 47 Kenyan sub-counties.\n")

if __name__ == "__main__":
    generate_pitches()
