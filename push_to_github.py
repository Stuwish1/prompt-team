"""
push_to_github.py — Pushar Prompt Team till GitHub
Kör: python push_to_github.py
"""
import json, subprocess, sys, os
from pathlib import Path

BASE = Path(__file__).parent
SETTINGS = BASE / "settings.json"
REPO_NAME = "prompt-team"

# ── Läs token ──
try:
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    TOKEN = s.get("github_token", "").strip()
except Exception as e:
    print(f"[FEL] Kan inte läsa settings.json: {e}")
    sys.exit(1)

if not TOKEN:
    print("[FEL] GitHub-token saknas. Öppna appen → Inställningar → spara token.")
    sys.exit(1)

# ── Hämta inloggat konto via httpx ──
try:
    import httpx
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

print("Kollar GitHub-konto...")
try:
    me = httpx.get("https://api.github.com/user", headers=HEADERS, timeout=10).json()
    OWNER = me.get("login", "")
    if not OWNER:
        print(f"[FEL] Kunde inte hämta användare. Svar: {me}")
        sys.exit(1)
    print(f"[OK] Inloggad som: {OWNER}")
except Exception as e:
    print(f"[FEL] GitHub API: {e}")
    sys.exit(1)

# ── Skapa repo ──
print(f"Skapar repo {OWNER}/{REPO_NAME}...")
resp = httpx.post(
    "https://api.github.com/user/repos",
    headers=HEADERS,
    json={
        "name": REPO_NAME,
        "description": "Prompt Team — AI-agenter som granskar och förbättrar dina prompts",
        "private": False,
        "auto_init": False,
    },
    timeout=15,
)
if resp.status_code in (201, 422):  # 422 = already exists
    exists = resp.status_code == 422
    print(f"[OK] Repo {'finns redan' if exists else 'skapat'}: https://github.com/{OWNER}/{REPO_NAME}")
else:
    print(f"[FEL] API {resp.status_code}: {resp.text[:200]}")
    sys.exit(1)

# ── .gitignore ──
gi = BASE / ".gitignore"
if not gi.exists():
    gi.write_text("__pycache__/\n*.pyc\nsettings.json\nsessions.json\n.env\n", encoding="utf-8")
    print("[OK] .gitignore skapad")

# ── Git kommandon ──
def git(cmd, check=False):
    r = subprocess.run(
        f"git {cmd}", shell=True, cwd=str(BASE),
        capture_output=True, text=True
    )
    if r.stdout.strip():
        print(f"    {r.stdout.strip()[:120]}")
    if r.stderr.strip() and "warning" not in r.stderr.lower():
        print(f"    {r.stderr.strip()[:120]}")
    return r.returncode == 0

print("\nInitierar git...")
git("init")
git_email = s.get("git_email", "stiven@2snickare.se")
git_name  = s.get("git_name",  "Stiven Ishoo")
git(f'config user.email "{git_email}"')
git(f'config user.name "{git_name}"')
git("remote remove origin")
REMOTE = f"https://{TOKEN}@github.com/{OWNER}/{REPO_NAME}.git"
git(f'remote add origin {REMOTE}')
git("add -A")

# Check if there's anything to commit
status = subprocess.run("git status --porcelain", shell=True, cwd=str(BASE), capture_output=True, text=True)
if status.stdout.strip():
    git('commit -m "feat: Prompt Team initial commit"')
else:
    print("    Inga nya ändringar att committa")

git("branch -M main")
print("\nPushar till GitHub...")
ok = git("push -u origin main --force")

if ok:
    print(f"\n{'='*50}")
    print(f"  [OK] Klart!")
    print(f"  https://github.com/{OWNER}/{REPO_NAME}")
    print(f"{'='*50}\n")

    # ── Spara repo-info i settings ──
    s["self_repo"] = f"{OWNER}/{REPO_NAME}"
    s["self_branch"] = "main"
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Repot sparat i settings: {OWNER}/{REPO_NAME}")
else:
    print("\n[FEL] Push misslyckades.")
    print("Kontrollera att token har 'repo'-r