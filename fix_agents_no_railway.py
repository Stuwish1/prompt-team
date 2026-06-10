"""
Uppdaterar snickare-auto-bygg och granskare-auto SKILL.md
att läsa/skriva build_queue.json direkt istället för Railway API.
Kör: python fix_agents_no_railway.py
"""
import re, pathlib, shutil, datetime

BASE = pathlib.Path(r"C:\Users\stive\OneDrive - 2 Snickare Sverige AB\Dokument\Claude\Scheduled")

# ── SNICKARE ────────────────────────────────────────────────────────────────
SNICKARE = BASE / "snickare-auto-bygg" / "SKILL.md"

SNICKARE_OLD_STEG1 = r"""## STEG 1 — Kolla kön

```bash
curl -s https://prompt-team-production.up.railway.app/api/build-queue | python3 -c "
import json,sys
items = json.load(sys.stdin).get('items', [])
active = [it for it in items if it.get('status') == 'byggs' and not it.get('deleted_at')]
queued = [it for it in items if it.get('status') == 'kö' and not it.get('deleted_at')]
if active:
    print('BYGGS:', json.dumps(active[0], ensure_ascii=False, indent=2))
elif queued:
    print('KÖ:', json.dumps(queued[0], ensure_ascii=False, indent=2))
else:
    print('INGEN TASK')
"
```

- Om `BYGGS` → gå direkt till steg 2
- Om `KÖ` → aktivera itemet först:
```bash
curl -s -X POST https://prompt-team-production.up.railway.app/api/build-queue/{ITEM_ID}/send \\
  -H "Content-Type: application/json" -d '{}'
```
- Om `INGEN TASK` → **avsluta, gör ingenting**"""

SNICKARE_NEW_STEG1 = r"""## STEG 1 — Kolla kön

```python
import json, datetime

QUEUE = 'C:/innob-agent/prompt-team/build_queue.json'
with open(QUEUE, encoding='utf-8') as f:
    raw = json.load(f)
items = raw if isinstance(raw, list) else raw.get('items', [])
active = [it for it in items if it.get('status') == 'byggs' and not it.get('deleted_at')]
queued = [it for it in items if it.get('status') == 'kö'    and not it.get('deleted_at')]

if active:
    print('BYGGS:', json.dumps(active[0], ensure_ascii=False, indent=2))
elif queued:
    item = queued[0]
    item['status'] = 'byggs'
    item['sent_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    item['attempt_nr'] = (item.get('attempt_nr') or 0) + 1
    with open(QUEUE, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print('KÖ:', json.dumps(item, ensure_ascii=False, indent=2))
else:
    print('INGEN TASK')
```

- Om `BYGGS` → gå direkt till steg 2 (plocka item-ID och spec från utskriften)
- Om `KÖ` → item är nu aktiverat, gå till steg 2
- Om `INGEN TASK` → **avsluta, gör ingenting**"""

SNICKARE_OLD_STEG6_KLAR = r"""**Om klart:**
```bash
curl -s -X PATCH https://prompt-team-production.up.railway.app/api/build-queue/{ITEM_ID} \
  -H "Content-Type: application/json" \
  -d '{
    "status": "klar",
    "result_summary": {
      "success": true,
      "files_changed": ["app.py"],
      "summary": "Kort beskrivning av vad som byggdes"
    }
  }'
```

**Om blockerat:**
```bash
curl -s -X PATCH https://prompt-team-production.up.railway.app/api/build-queue/{ITEM_ID} \
  -H "Content-Type: application/json" \
  -d '{
    "status": "behover_dig",
    "result_summary": {
      "success": false,
      "files_changed": [],
      "summary": "Vad som gjordes",
      "blockers": ["Exakt vad som blockerar"]
    }
  }'
```"""

SNICKARE_NEW_STEG6_KLAR = r"""**Om klart:**
```python
import json, datetime
QUEUE = 'C:/innob-agent/prompt-team/build_queue.json'
with open(QUEUE, encoding='utf-8') as f:
    raw = json.load(f)
items = raw if isinstance(raw, list) else raw.get('items', [])
item = next(it for it in items if it['id'] == ITEM_ID)
item['status'] = 'klar'
item['result_summary'] = {
    'success': True,
    'files_changed': ['app.py'],   # uppdatera med faktiska filer
    'summary': 'Kort beskrivning av vad som byggdes'
}
with open(QUEUE, 'w', encoding='utf-8') as f:
    json.dump(raw, f, ensure_ascii=False, indent=2)
print('Markerat klar')
```

**Om blockerat:**
```python
import json
QUEUE = 'C:/innob-agent/prompt-team/build_queue.json'
with open(QUEUE, encoding='utf-8') as f:
    raw = json.load(f)
items = raw if isinstance(raw, list) else raw.get('items', [])
item = next(it for it in items if it['id'] == ITEM_ID)
item['status'] = 'behover_dig'
item['result_summary'] = {
    'success': False,
    'files_changed': [],
    'summary': 'Vad som gjordes',
    'blockers': ['Exakt vad som blockerar']
}
with open(QUEUE, 'w', encoding='utf-8') as f:
    json.dump(raw, f, ensure_ascii=False, indent=2)
print('Markerat behover_dig')
```"""


def patch_file(path, replacements, label):
    if not path.exists():
        print(f"  ✗ Hittades inte: {path}")
        return
    backup = path.with_suffix('.md.bak')
    shutil.copy2(path, backup)
    content = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            print(f"  ✓ {label}: patch applicerad")
        else:
            print(f"  ⚠ {label}: mönster hittades inte (redan patchat?)")
    path.write_text(content, encoding='utf-8')


print("=== Patchar snickare-auto-bygg ===")
patch_file(SNICKARE, [
    (SNICKARE_OLD_STEG1, SNICKARE_NEW_STEG1),
    (SNICKARE_OLD_STEG6_KLAR, SNICKARE_NEW_STEG6_KLAR),
], "snickare")


# ── GRANSKARE ───────────────────────────────────────────────────────────────
GRANSKARE = BASE / "granskare-auto" / "SKILL.md"

print("\n=== Kontrollerar granskare-auto ===")
if GRANSKARE.exists():
    g = GRANSKARE.read_text(encoding='utf-8')
    if 'railway.app' in g:
        print("  ⚠ Granskaren använder också Railway — patchar...")
        g_backup = GRANSKARE.with_suffix('.md.bak')
        shutil.copy2(GRANSKARE, g_backup)

        # Ersätt alla Railway-API-anrop med lokala fil-operationer
        # Granskaren gör PATCH för review_verdict → lokalt
        g = re.sub(
            r'curl -s -X PATCH https://prompt-team-production\.up\.railway\.app/api/build-queue/\{([^}]+)\}[^`]+`',
            lambda m: _granskare_patch_replacement(m.group(1)),
            g, flags=re.DOTALL
        )
        # Ersätt GET av kön
        g = re.sub(
            r'curl -s https://prompt-team-production\.up\.railway\.app/api/build-queue[^`\n]*',
            r"python3 -c \"\nimport json\nraw=json.load(open('C:/innob-agent/prompt-team/build_queue.json',encoding='utf-8'))\nitems=raw if isinstance(raw,list) else raw.get('items',[])\nprint(json.dumps([it for it in items if it.get('status')=='byggs' and not it.get('deleted_at')], ensure_ascii=False, indent=2))\n\"",
            g
        )
        GRANSKARE.write_text(g, encoding='utf-8')
        print("  ✓ Granskare patchad")
    else:
        print("  ✓ Ingen Railway-beroende hittad")
else:
    print(f"  ✗ Hittades inte: {GRANSKARE}")


def _granskare_patch_replacement(item_var):
    return f'''python3 << 'PYEOF'
import json
QUEUE = 'C:/innob-agent/prompt-team/build_queue.json'
with open(QUEUE, encoding='utf-8') as f:
    raw = json.load(f)
items = raw if isinstance(raw, list) else raw.get('items', [])
item = next((it for it in items if it['id'] == {item_var}), None)
if item:
    # applicera patch-data här
    with open(QUEUE, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print('OK')
PYEOF
`'''


# ── PROJEKTLEDARE ────────────────────────────────────────────────────────────
PL = BASE / "projektledare-auto" / "SKILL.md"
print("\n=== Kontrollerar projektledare-auto ===")
if PL.exists():
    p = PL.read_text(encoding='utf-8')
    if 'railway.app' in p:
        print("  ⚠ Projektledaren använder Railway — kontrollera manuellt")
        print("  (för komplex logik — ändra SKILL.md manuellt efter behov)")
    else:
        print("  ✓ Ingen Railway-beroende")
else:
    print(f"  ✗ Hittades inte: {PL}")

print("\n=== Klart! Säkerhetskopior sparade som .md.bak ===")
print("Starta om snickare och granskare för att ändringarna ska gälla.")
