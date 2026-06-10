# UX-agent Status
**Senast analyserad:** 2026-06-10 (automatisk körning, iteration 8)
**Metod:** Statisk kodanalys av index.html (3968 rader), app.py (4682 rader), PROJECT_STATUS.md, AGENT_CHATBOX_BUILD.md
**Primär persona:** 10-åring utan teknisk bakgrund (KID_USER_PROMPT.md)

---

## SNABBSAMMANFATTNING

| Svårighetsgrad | Antal | Blockar kernflöde? |
|---|---|---|
| 🔴 Kritisk | 2 | Ja — hela sidan kan vara trasig |
| 🟡 Medel | 6 | Delvis |
| 🟢 Liten | 5 | Nej |

---

## 🔴 KRITISKA UX-PROBLEM

---

### UX-KRIT-1 — `index.html` FORTFARANDE AVHUGGEN (BLOCKERANDE)

**Fil:** `index.html`, sista raden ~3968
**Status:** Rapporterad som fixad i E1/G1 i AGENT_CHATBOX_BUILD.md — men **VERIFIERAT FORTFARANDE TRASIG**.

Bevis: `showToast` anropas på 20+ ställen i filen men funktionen är **inte definierad** i filen (Python-sökning bekräftar). `DOMContentLoaded`-callbacken är inte stängd. Keydown-lyssnaren (Ctrl+Enter → runReview), paste-lyssnaren (skärmdumpar), live-reload-pollningen och `</html>` saknas alla.

**Konsekvens:** JS-parsern kastar `SyntaxError: Unexpected end of input` → hela sidan är vit/tom för användaren.

**Fix:** Lägg till exakt detta i slutet av `index.html` (identisk med G1/E1 i AGENT_CHATBOX_BUILD.md):

```javascript
    updateActiveProjBadge();
    loadHistory();
    updateGithubSection();
    refreshByggaBadge();
  });
  setTimeout(() => runHealthCheck(), 800);
});

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    if (!document.getElementById('runBtn').disabled) runReview();
  }
});

document.addEventListener('paste', (e) => {
  if (currentMode === 'ny_funktion') return;
  const items = (e.clipboardData || {}).items || [];
  for (const it of items) {
    if (it.type && it.type.startsWith('image/')) {
      const file = it.getAsFile();
      if (file) { _addScreenshot(file); showToast('📸 Skärmdump tillagd'); }
    }
  }
});

(async () => {
  let lastMtime = null;
  const poll = async () => {
    try {
      const r = await fetch('/api/version');
      const { mtime } = await r.json();
      if (lastMtime === null) { lastMtime = mtime; return; }
      if (mtime !== lastMtime) { location.reload(); }
    } catch {}
  };
  await poll();
  setInterval(poll, 1000);
})();
</script>
</body>
</html>
```

**Verifiera:** `tail -5 index.html` ska visa `</html>` som sista rad.

---

### UX-1 — `alert()` används på 7 ställen (FORTFARANDE OLÖST)

**Fil:** `index.html`
**Rader:** 1439, 1750, 1796, 1798, 1800, 1802, 1812

Browser-native `alert()` fryser UI:t och är skrämmande för barn. Rad 1750 är ny sedan iteration 6 — längre feltext men fortfarande `alert()`.

Se iteration 6:s UX-1 för komplett fix med `showFieldError()` och `@keyframes shake`.

**Prioritet: Sprint 1 — åtgärda direkt efter UX-KRIT-1.**

---

## 🟡 MEDEL UX-PROBLEM

---

### UX-6 — `confirm()` används på 4 ställen (FORTFARANDE OLÖST)

**Fil:** `index.html`
**Rader:** 2644 (`queueDelete`), 2815 (`deleteSession`), 2830 (`clearBacklog`), 3850 (historik-radering)

Alla browser-native popups som fryser UI. Se iteration 6 för undo-pattern-fix.

---

### UX-4 — Tom kö saknar CTA (FORTFARANDE OLÖST)

**Fil:** `index.html`, `renderQueueBox()` (~rad 2311)

Tom byggkö visar bara text utan klickbar åtgärd. Barn vet inte hur de navigerar vidare.
Se iteration 6:s UX-4 för fix med "→ Gå till Beställ"-knapp.

---

### UX-9 — `kontrolleraBuild()` visar bara toast, inte inline

**Fil:** `index.html`, `kontrolleraBuild()` (~rad 2547)

Efter granskning visas bara toast "GODKÄNT"/"UNDERKÄNT". Kvarstående problem syns inte direkt — användaren måste klicka runt för att förstå vad som gick fel.

Verifiera att `last_verdict.kvarstaende` sparas korrekt i `_queueItems` och visas i `qc-verdict`-blocket efter `loadAttBygga()`.

---

### UX-10 — modeHelp-text är densamma för alla lägen

**Fil:** `index.html`, `setMode()` och `#modeHelp` (~rad 868)

Texten "Beskriv din idé — teamet analyserar..." visas även för `granska_kod` och `buggrapport`.
Se iteration 6:s UX-10 för fix med `modeHelp`-objekt per läge.

---

### UX-2 — startBuild öppnar chatPanel men barnvänliga texter saknas

**Fil:** `index.html`, `startBuild()` (~rad 2516) och `renderQueueBox()` (~rad 2311)

Delvis åtgärdat: spec postas nu till chat-panel och `openChatPanel()` öppnas. Men:
- Knapptexten "▶ Bygg nästa" är för teknisk (ska vara "▶ Bygg det här!" per K2 i AGENT_CHATBOX_BUILD.md)
- Status-texter ("Byggs", "Behöver dig", "I kö") ska uppdateras till barnvänliga versioner (K2)

---

### UX-12 — Health-badge är för liten och saknar tooltip

**Fil:** `index.html`, `updateHealthBadges()` (~rad 1713)

Hälsostatusen är en tiny dot (`🟢`). Om API-nyckeln saknas märker barnanvändaren inte av det.
Se iteration 6:s UX-12 för fix med pulserade `⚠️`-märke + tooltip.

---

## 🟢 LITEN UX-POLISH

---

### UX-16 — `showToast()` definieras inte i filen (hänger ihop med UX-KRIT-1)

`showToast` anropas 20+ gånger men definieras inte — funktionen ligger i trunkerade delen. Fix: UX-KRIT-1 återställer den. Lägg samtidigt till `innerHTML`-stöd för UX-6:s ångra-knapp:
```javascript
t.innerHTML = msg;  // istället för t.textContent = msg
```

---

### UX-AL — `local_path` saknas i settings-UI (NYTT)

**Fil:** `index.html`, settings-modal

Backend sparar nu `local_path` (AI/I1 implementerat), men UI-fältet saknas. Stiven måste redigera `settings.json` manuellt för att sätta lokal repo-sökväg.

**Fix från I1 i AGENT_CHATBOX_BUILD.md** — lägg till i settings-modal HTML efter `selfRepoInput`:
```html
<div class="form-group">
  <label>Lokal sökväg till repo</label>
  <input type="text" id="localPathInput" placeholder="C:\innob-agent\prompt-team"
         style="font-family:monospace;font-size:12px;">
  <div style="font-size:11px;color:var(--text3);margin-top:4px;">
    Mappen agenten läser/skriver filer i. Standard = samma mapp som app.py.
  </div>
</div>
```
I `openSettings()`: `document.getElementById('localPathInput').value = s.local_path || '';`
I `saveSettings()`: `payload.local_path = document.getElementById('localPathInput').value.trim();`

---

### UX-14 — Ctrl+Enter-hint saknas OCH lyssnaren saknas (pga KRIT-1)

Keydown-lyssnaren saknas pga trunkering. Fix: UX-KRIT-1 återställer den.
Lägg sedan till synlig hint bredvid "Skicka till teamet"-knappen:
```html
<span style="font-size:10px;color:var(--text3);margin-left:4px;">Ctrl+↩</span>
```

---

### UX-19 — Byggabadge nollställs inte efter `kontrolleraBuild()`

**Fil:** `index.html`, `kontrolleraBuild()` (~rad 2547)

`refreshByggaBadge()` anropas inte efter godkänt/underkänt → badge visar gammalt värde.

**Fix:** Lägg till `refreshByggaBadge()` i `kontrolleraBuild()` efter `loadAttBygga()`.

---

### UX-17 — Avklarade items täpper igen byggkön

**Fil:** `index.html`, `renderQueueBox()`

`status: 'klar'`-items visas alltid utan filter. Se iteration 6:s UX-17 för toggle-fix.

---

## Löst sedan iteration 6

| Fynd | Åtgärd |
|---|---|
| UX-3 — attention banner på fel vyer | `updateAttentionBanner()` kollar `view-bygga` korrekt |
| UX-5 — AGENT_DISPLAY_NAMES hade 8 av 34 agenter | Nu 37 agenter med emoji + svenska namn |
| UX-7 — Historik saknade sökning | `filterHistory()` + `#historySearch` implementerade (P3-H) |
| UX-13 — switchView skrev över builder-active CSS | Fixat: `classList.remove/add` |
| UX-2 (delvis) — startBuild kopierade bara till clipboard | Spec postas till chat-panel, `openChatPanel()` öppnas |
| UX-8 (delvis) — projekt bara i localStorage | Serverlagring via `/api/projects` (G2) |
| Chat-feature | Chat-panel + chatt-flik implementerade (CHAT-1, CHAT-2, P2-A, P2-C) |

---

## Prioriterad åtgärdsordning

| Sprint | Task | Fil | Est. |
|---|---|---|---|
| 1 | **UX-KRIT-1** — index.html avhuggen | index.html | 5 min |
| 1 | UX-1 — alert() → inline errors + showFieldError | index.html | 30 min |
| 1 | UX-6 — confirm() → ångra-pattern | index.html | 20 min |
| 1 | UX-16 — showToast innerHTML (fixas med KRIT-1) | index.html | 5 min |
| 2 | UX-AL — local_path i settings UI | index.html | 15 min |
| 2 | UX-4 — CTA i tom kö | index.html | 10 min |
| 2 | UX-10 — modeHelp-text per läge | index.html | 10 min |
| 2 | UX-2 — barnvänliga knappar (K2) | index.html | 10 min |
| 3 | UX-9 — inline verdict efter kontrolleraBuild | index.html | 15 min |
| 3 | UX-12 — health-badge tydligare | index.html | 10 min |
| 3 | UX-14 — Ctrl+Enter hint | index.html | 5 min |
| 3 | UX-19 — badge reset efter kontrollera | index.html | 5 min |
| 4 | UX-17 — visa/dölj klar-items | index.html | 15 min |

---

**PRINCIPREGEL:** Systemet pushar ALDRIG automatiskt till git. Push är alltid en manuell användaråtgärd.
