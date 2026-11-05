name: Ad Agent Pipeline

on:
  workflow_dispatch: # Allows manual run from GitHub website

permissions:
  contents: write # Grants GitHub Actions permission to commit generated pitch files back to your repo

jobs:
  run-agents:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install google-genai

      - name: Run Pitch Generator
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: python scripts/generate_pitch.py

      - name: Commit Generated Pitches
        run: |
          git config --global user.name 'github-actions[bot]'
          git config --global user.email 'github-actions[bot]@users.noreply.github.com'
          git add generated_pitches/
          git commit -m "Automated AI pitch generation complete [skip ci]" || echo "No changes to commit"
          git push
