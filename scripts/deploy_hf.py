"""Deploy FINN to a Hugging Face Docker Space.
Reads HF_TOKEN, HF_USER, GEMINI_API_KEY from .env. Usage: python scripts/deploy_hf.py [space-name]"""
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
token, user = os.environ["HF_TOKEN"].strip(), os.environ["HF_USER"].strip()
name = sys.argv[1] if len(sys.argv) > 1 else "finn"
repo = f"{user}/{name}"
api = HfApi(token=token)
api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
api.add_space_secret(repo, "GEMINI_API_KEY", os.environ["GEMINI_API_KEY"].strip())
api.upload_folder(
    folder_path=str(ROOT), repo_id=repo, repo_type="space",
    allow_patterns=["Dockerfile", ".dockerignore", "requirements.txt", "backend/**", "frontend/**", "data/**"],
    ignore_patterns=["**/node_modules/**", "frontend/dist/**", "**/__pycache__/**", "data/cache/pdf/**", ".env"],
    commit_message="Deploy FINN",
)
card = """---
title: FINN
emoji: 📈
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Mobile-first investor agent - push digest + grounded research
---
FINN: the few things that matter across your portfolio, and research grounded in what management actually said.
Source: see the GitHub repository linked in the submission.
"""
with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
    f.write(card)
api.upload_file(path_or_fileobj=f.name, path_in_repo="README.md", repo_id=repo, repo_type="space")
print(f"Space: https://huggingface.co/spaces/{repo}")
print(f"App:   https://{user.lower()}-{name}.hf.space")
