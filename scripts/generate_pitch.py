import csv
import os

def load_prompt(filepath):
    with open(filepath, 'r') as f:
        return f.read()

def generate_pitches():
    copywriter_persona = load_prompt("prompts/copywriter.md")
    
    # Check if targets file exists
    if not os.path.exists("data/targets.csv"):
        print("Targets file not found.")
        return

    with open("data/targets.csv", mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            print(f"========================================")
            print(f"Generating Pitch for: {row['Organization']}")
            print(f"========================================")
            
            prompt = f"""
            {copywriter_persona}
            
            Target Organization: {row['Organization']}
            Category: {row['Category']}
            Contact: {row['Contact_Name']}
            Campaign Focus: {row['Campaign_Focus']}
            
            Write a cold email pitch highlighting The Star's Tuesday 47-county print distribution.
            """
            
            # Print mock generated output for now
            print(f"Dear {row['Contact_Name']},\n")
            print(f"I noticed {row['Organization']} is driving impact with your {row['Campaign_Focus']} campaign...")
            print(f"[Would integrate Gemini API here using GEMINI_API_KEY environment variable]\n")

if __name__ == "__main__":
    generate_pitches()
