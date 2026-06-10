# Loggfynd — ej inlagda i backlog (API nere)

---

## 2026-06-10 — KRITISK: app.py trunkerad rad 4676 — server startar inte (ny instans)

**Meddelande:** `SyntaxError: unterminated string literal (detected at line 4677)`

**Kontext:** `app.py` är trunkerad vid rad 4676, mitt i `get_project_settings_api()`-endpointen. Sista raden är: `"disabled": a["id"] in s.get("di` — strängen är avklippt. Filen är 4 676 rader (tidigare trunkering var vid 4 807). Appen startar inte. Felet är INTE samma som det tidigare SyntaxError-fyndet (som markerades ✅ i PROJECT_STATUS.md). Detta är ett nytt trunkerings-/skrivfel, troligen introducerat av senaste byggkörning.

**Föreslagen fix:** Återställ sista raden och avsluta endpoint-funktionen korrekt:
```python
                "disabled": a["id"] in s.get("disabled_agents", []),
            }
            for a in _AGENT_CATALOGUE
        ],
    }
```
Kontrollera även git-diff för att se vad som ändrades i senaste commit nära rad 4676.

**Status:** ej inlagd i backlog (API nere)

---

## 2026-06-10 — KRITISK: backlog.json korrupt (null-byte overflow)

**Meddelande:** `json.JSONDecodeError: Extra data: line 190 column 2 (char 11498)`

**Kontext:** backlog.json innehåller giltig JSON (10 items, 11 497 tecken) följt av 9 367 null-bytes (`\x00`). Orsakas troligen av en atomic write-operation som pre-allokerade filen till en större buffert men aldrig trunkerade den efteråt. `json.loads()` misslyckas vid parse → hela backloggen är oläsbar för appen.

**Föreslagen fix:**
1. Strippa null-bytes vid läsning i `_backlog_load()`:
   ```python
   content = path.read_text(encoding="utf-8").rstrip('\x00')
   ```
2. Lägg till trunkering i `_backlog_write()` (använd `f.truncate()` efter skrivning)
3. Korrigera den existerande filen omedelbart:
   ```bash
   python3 -c "
   import json, pathlib
   p = pathlib.Path('backlog.json')