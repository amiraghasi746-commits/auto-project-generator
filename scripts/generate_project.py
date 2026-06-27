"""
Auto Project Generator
از Groq API برای تولید ایده پروژه و GitHub API برای ایجاد repo استفاده می‌کنه
"""

import os
import json
import requests
import re
import random
from datetime import datetime
from github import Github, GithubException

# ─── تنظیمات ──────────────────────────────────────────────────────────────────

GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
GITHUB_PAT      = os.environ["GITHUB_PAT"]          # ← Personal Access Token
GITHUB_USERNAME = os.environ["GITHUB_USERNAME"]

TOPICS = ["AI / Machine Learning", "Data Science", "Python Automation"]

GROQ_MODEL = "llama3-70b-8192"


# ─── مرحله ۱: تولید ایده پروژه با Groq ────────────────────────────────────────

def call_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 4000,
    }
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def generate_project_idea() -> dict:
    topic = random.choice(TOPICS)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    prompt = f"""
You are a senior Python developer. Today is {today}.
Generate a unique, practical, beginner-to-intermediate Python project idea in the domain: **{topic}**.

Return ONLY valid JSON (no markdown, no extra text) with this exact structure:
{{
  "repo_name": "kebab-case-name-max-50-chars",
  "title": "Human Readable Title",
  "description": "One sentence description under 120 chars",
  "topics": ["python", "one-or-two-domain-tags"],
  "domain": "{topic}",
  "readme": "Full markdown README with ## sections: Overview, Features, Installation, Usage, Examples, Contributing, License",
  "main_code": "Complete working Python code for main.py (50-150 lines, with docstrings and type hints)",
  "test_code": "Complete pytest test file for test_main.py (at least 5 tests)",
  "gitignore_extras": ["any extra patterns beyond standard Python .gitignore"],
  "ci_python_versions": ["3.10", "3.11", "3.12"]
}}
"""
    raw = call_groq(prompt)

    # استخراج JSON از پاسخ - گاهی Groq توضیح اضافه میده
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in Groq response:\n{raw[:500]}")
    return json.loads(match.group())


# ─── مرحله ۲: ساخت فایل‌های پروژه ────────────────────────────────────────────

GITIGNORE_TEMPLATE = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
dist/
*.egg-info/
.eggs/
*.egg
pip-wheel-metadata/

# Virtual environments
.env
.venv
env/
venv/
ENV/

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# IDEs
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""

# FIX ۱: از f-string به جای .format() استفاده می‌کنیم تا تداخل curly-brace نداشته باشیم
def build_ci_yaml(versions: list[str]) -> str:
    versions_yaml = "\n".join(f'          - "{v}"' for v in versions)
    return f"""\
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version:
{versions_yaml}

    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{{{ matrix.python-version }}}}
        uses: actions/setup-python@v5
        with:
          python-version: ${{{{ matrix.python-version }}}}
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pytest pytest-cov
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Run tests
        run: pytest --cov=. --cov-report=xml -v
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
"""

CONTRIBUTING_MD = """\
# Contributing

Contributions are welcome! Please follow these steps:

1. Fork this repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## Code Style
- Follow PEP 8
- Add type hints
- Write docstrings for all public functions
- Add tests for new features
"""

REQUIREMENTS_TXT = """\
pytest>=7.0
pytest-cov>=4.0
"""


def build_file_tree(project: dict) -> dict[str, str]:
    """دیکشنری از path -> محتوا برمی‌گردونه"""
    versions = project.get("ci_python_versions", ["3.10", "3.11"])
    gitignore = GITIGNORE_TEMPLATE
    for extra in project.get("gitignore_extras", []):
        gitignore += f"\n{extra}"

    return {
        "README.md":                  project["readme"],
        "main.py":                    project["main_code"],
        "test_main.py":               project["test_code"],
        ".gitignore":                 gitignore.strip(),
        "requirements.txt":           REQUIREMENTS_TXT.strip(),
        "CONTRIBUTING.md":            CONTRIBUTING_MD.strip(),
        "docs/overview.md":           f"# {project['title']}\n\n{project['description']}\n\n> Domain: {project['domain']}\n",
        ".github/workflows/ci.yml":   build_ci_yaml(versions),   # FIX ۱
    }


# ─── مرحله ۳: ایجاد repo در GitHub ────────────────────────────────────────────

def create_github_repo(project: dict, files: dict[str, str]) -> str:
    g = Github(GITHUB_PAT)          # FIX ۲: از PAT استفاده می‌کنیم
    user = g.get_user()

    repo_name = project["repo_name"]

    # FIX ۳: فقط خطای 404 (repo وجود نداره) رو ignore می‌کنیم
    try:
        user.get_repo(repo_name)
        # اگه به اینجا رسیدیم یعنی repo وجود داره → suffix اضافه کن
        repo_name = f"{repo_name}-{datetime.utcnow().strftime('%Y%m%d')}"
    except GithubException as e:
        if e.status != 404:
            raise   # خطاهای دیگه رو re-raise کن

    repo = user.create_repo(
        name=repo_name,
        description=project["description"],
        private=False,
        auto_init=False,
    )

    # آپلود همه فایل‌ها
    for path, content in files.items():
        repo.create_file(
            path=path,
            message=f"Add {path}",
            content=content,
        )

    # تنظیم topics - GitHub فقط lowercase قبول می‌کنه
    raw_topics = project.get("topics", [])
    all_topics = list(set(
        ["python", "auto-generated"] +
        [t.lower().replace(" ", "-").replace("/", "-") for t in raw_topics]
    ))
    repo.replace_topics(all_topics)

    return repo.html_url


# ─── اجرای اصلی ────────────────────────────────────────────────────────────────

def main():
    print("🤖 Generating project idea with Groq...")
    project = generate_project_idea()
    print(f"✅ Idea: {project['title']} (domain: {project['domain']})")

    print("📁 Building file tree...")
    files = build_file_tree(project)
    print(f"   Files: {list(files.keys())}")

    print("🚀 Creating GitHub repo...")
    url = create_github_repo(project, files)
    print(f"✅ Published: {url}")


if __name__ == "__main__":
    main()
