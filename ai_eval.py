"""
Prompt Team — AI-kvalitetsutvärdering
Kör hela flödet N gånger per läge mot kod med MEDVETET planterade fel (facit),
och sparar alla agentsvar för bedömning.

  python ai_eval.py [port] [iterationer=3]

Output: ai_eval_results.json — {mode: [run1, run2, run3]} med fulla agentsvar.
"""
import base64
import concurrent.futures
import json
import sys
import time
import urllib.request
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "8001"
ITERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
BASE = f"http://127.0.0.1:{PORT}"

# ── Planterade fel — FACIT per agent-domän ──────────────────────────────
# Varje rad markerad TRAP:<agent> är ett fel den agenten SKA hitta.
SEEDED_CODE = '''
import sqlite3, hashlib, logging
from flask import Flask, request

app = Flask(__name__)

API_KEY = "sk_live_51HxT2mQ9vN3pR8wZAbCdEf"
ADMIN_PWD = "admin123"

cache = {}

def get_db():
    return sqlite3.connect("app.db")

@app.route("/users")
def list_users():
    q = request.args.get("name", "")
    db = get_db()
    rows = db.execute("SELECT * FROM users WHERE name = '" + q + "'").fetchall()
    out = []
    for r in rows:
        orders = db.execute("SELECT * FROM orders WHERE user_id=" + str(r[0])).fetchall()
        out.append({"user": list(r), "orders": [list(o) for o in orders]})
        logging.info("Visar anvandare %s email %s personnummer %s", r[1], r[2], r[3])
    return {"data": out}

@app.route("/users/delete")
def delete_user():
    uid = request.args["id"]
    db = get_db()
    db.execute("DELETE FROM users WHERE id=" + uid)
    db.commit()
    return "ok"

def hash_password(pwd):
    return hashlib.md5(pwd.encode()).hexdigest()

def proc(d):
    try:
        x = d["items"][0]
        return x * 1.25
    except:
        pass
'''

SEEDED_HTML = '''
<!-- index.html (utdrag) -->
<div onclick="deleteAccount()" style="width:1200px;background:#333;color:#3a3a3a;">Radera konto</div>
<img src="chart.png">
<input placeholder="Sok anvandare">
<script>
  function showResult(userInput) {
    document.getElementById("out").innerHTML = userInput;
  }
  setInterval(function() { fetch("/users").then(r => r.json()); }, 1000);
</script>
'''

GRANSKA_INPUT = SEEDED_CODE + "\n" + SEEDED_HTML

BUGG_INPUT = (
    "FELBESKRIVNING:\n"
    "Appen kraschar tyst nar varukorgen ar tom - anvandaren ser bara en blank yta, "
    "inget felmeddelande. Dessutom visar anvandarlistan ibland andra anvandares ordrar.\n\n"
    "KOD:\n" + SEEDED_CODE
)

NY_INPUT = (
    "Jag vill att kunder ska kunna logga in med BankID och se sina fakturor och betala "
    "dem direkt i appen. Spara deras kortuppgifter sa det gar snabbt nasta gang. "
    "Det ska kannas enkelt och tryggt."
)

PASS, FAIL = [], []

def req(path, payload, timeout=700):  # serverns lagliga värsta fall är ~650s efter kapacitetshöjningen
    data = json.dumps(payload).encode()
    r = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def run_mode(mode, payload, i):
    t0 = time.time()
    res = req("/api/review", payload)
    dt = time.time() - t0
    fel = [x["name"] for x in res["results"] if x["status"] == "FEL"]
    print(f"  {mode} #{i+1}: {dt:.0f}s · {res['stats']['total']} agenter · "
          f"{res['stats']['errors']} FEL{' (' + ', '.join(fel) + ')' if fel else ''} · "
          f"${res.get('cost_summary', {}).get('total_usd', 0):.3f}")
    # Slimma ner: behåll det som behövs för bedömning
    return {
        "iteration": i + 1,
        "elapsed_s": round(dt, 1),
        "stats": res["stats"],
        "cost": res.get("cost_summary", {}),
        "krav_result": res.get("krav_result", {}),
        "results": [
            {k: r.get(k) for k in ("id", "name", "status", "severity", "findings", "suggestions", "model", "error")}
            for r in res["results"]
        ],
        "smith_type": res.get("smith", {}).get("type"),
        "final_prompt": (res.get("final_prompt") or "")[:6000],
        "completeness": res.get("completeness_result", {}),
        "bestallare": res.get("bestallare_result", {}),
        "backlog_items_n": len(res.get("backlog_items", [])),
        "backlog_titles": [b.get("title") for b in res.get("backlog_result", {}).get("items", [])],
    }


def main():
    png = Path(__file__).parent / "test_screenshot.png"
    img_b64 = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()

    runs = {"granska_kod": [], "buggrapport": [], "ny_funktion": []}
    payloads = {
        "granska_kod": {"mode": "granska_kod", "input_text": GRANSKA_INPUT,
                        "context": "Flask-app med inbyggd HTML-frontend", "images": [img_b64],
                        "project_id": "aieval"},
        "buggrapport": {"mode": "buggrapport", "input_text": BUGG_INPUT,
                        "context": "Flask-app", "images": [img_b64], "project_id": "aieval"},
        "ny_funktion": {"mode": "ny_funktion", "input_text": NY_INPUT,
                        "context": "", "project_id": "aieval"},
    }

    t_start = time.time()
    for i in range(ITERS):
        print(f"\n── Iteration {i+1}/{ITERS} ──")
        # Kör de tre lägena parallellt (3 samtidiga reviews per iteration)
        with concurrent.futures.ThreadPoolExecutor(3) as ex:
            futs = {mode: ex.submit(run_mode, mode, payloads[mode], i) for mode in payloads}
            for mode, fut in futs.items():
                try:
                    runs[mode].append(fut.result(timeout=750))
                except Exception as e:
                    # Ett kraschat läge får inte slänga alla lägens resultat
                    print(f"  [FEL] {mode} #{i+1} kraschade: {str(e)[:200]}")
                    runs[mode].append({"iteration": i + 1, "error": str(e)[:300], "stats": {"errors": 0}})

    out = Path(__file__).parent / "ai_eval_results.json"
    out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")

    total_cost = sum(r.get("cost", {}).get("total_usd", 0) for rs in runs.values() for r in rs)
    total_fel = sum(r["stats"]["errors"] for rs in runs.values() for r in rs)
    print(f"\n{'='*56}")
    print(f"KLART: {ITERS} iterationer x 3 lagen pa {time.time()-t_start:.0f}s · "
