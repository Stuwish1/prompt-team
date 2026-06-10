"""
Lägger till wildcard CORS i app.py så att dashboard-artefakten
kan nå localhost:8001 oavsett vilken origin Cowork använder.
Kör: python fix_cors.py
"""
import pathlib, shutil

APP = pathlib.Path(r"C:\innob-agent\prompt-team\app.py")
if not APP.exists():
    print("app.py hittades inte"); exit(1)

old = '    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],'
new = '    allow_origins=["*"],  # lokal dev — wildcard OK, server är ej publik'

content = APP.read_text(encoding="utf-8")
if new.strip() in content:
    print("CORS redan patchad"); exit(0)
if old not in content:
    print("Mönster hittades inte — kontrollera app.py rad 88"); exit(1)

shutil.copy2(APP, APP.with_suffix(".py.bak"))
APP.write_text(content.replace(old, new), encoding="utf-8")
print("✓ CORS patchad — starta om app.py")
