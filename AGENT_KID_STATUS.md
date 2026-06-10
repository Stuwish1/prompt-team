# AGENT_KID_STATUS.md
> Senast verifierad mot: `origin/main` commit `3654bd7` · `index.html` rad 1–3835 · `app.py`
> Syfte: Klar byggbriefing. Läs detta, gör en task, leverera.

---

## Systemstatus — vad är sant just nu

| Komponent | Nuläge | Problemen |
|---|---|---|
| Välkomstskärm | `"🏢 IT-teamet väntar på din beställning"` | Fel ikon, fel text, teknisk Fas-lista |
| Run-knapp | `"▶ Skicka till teamet"` | "teamet" okänt för barn |
| Laddningsskärm | `"Kravanalytikern tolkar din idé"` | Agentnamn synliga |
| Fasrubriker | `"Fas 1 — Kravanalys"` etc. | Teknisk jargong i resultatvyn |
| KravBox-titel | `"📋 Kravanalytikern"` | Agentnamn synligt |
| Läge-knappar | `"Idé → färdig spec"` / `"Kod → backlog"` | "spec", "backlog" okänt |
| Förklaring av lägen | **Borttaget** (regression i 3654bd7) | Barnet klickar blind |
| "Extra kontext"-fält | **Alltid synligt** (regression i 3654bd7) | Teknisk placeholder |
| Byggkö-status | `"I kö"` / `"Byggs"` / `"Behöver dig"` | Kodinterna termer |
| Historik-badges | `"NY_FUNKTION"` i VERSALER | Råa mode-ID:n |
| Agentkort | 24 kort med GODKÄND/UNDERKÄND + kostnad | Aldrig visa för barn |
| Toast-meddelanden | 20+ med "spec", "köa", "Promptsmeden" | Teknisk jargong |
| Inställningspanel | Alltid synlig med API-nycklar | Aldrig visa för barn |
| Byggresultat-modal | `"teamet granskar mot specen"` | Hela modalen är admin-only |
| `push_to_github.bat` | Visas i banner + projektmodal | Aldrig visa för barn |
| `KID_MODE`-flagg | **Saknas helt** | Grundorsaken till alla problem |

**Kort:** Inget `KID_MODE`-skydd finns. Varje ny feature-push riskerar läcka teknisk text direkt till barnets skärm.

---

## Byggordning — vad beror på vad

```
TASK-01 (KID_MODE-flagg)
  ├─ TASK-05 (dölj settings)         — kräver .admin-only CSS
  ├─ TASK-09 (dölj Extra kontext)    — kräver .admin-only CSS
  ├─ TASK-12 (Beställarläge-toggle)  — kräver .admin-only CSS
  ├─ TASK-16 (dölj agentkort)        — kräver .admin-only CSS
  ├─ TASK-18 (dölj Byggsätt-flik)    — kräver .admin-only CSS
  ├─ TASK-19 (dölj Agentgranskning)  — kräver .admin-only CSS
  └─ alla övriga P1/P2 med kidMode-check

TASK-02 (.gitignore)                 — oberoende, gör direkt
TASK-03 (välkomstskärm)              — oberoende HTML-ändring
TASK-04 ("klistra in"-texten)        — oberoende, 2 rader
TASK-06 (statuskoder i kön)          — oberoende JS-ändring
```

**Bygg alltid TASK-01 och TASK-02 först.**

---

## TASK-01 · KID_MODE-flagg ⭐ BÖRJA HÄR

**Filer:** `settings.json` · `app.py` · `index.html`

**settings.json** — lägg till ett fält:
```json
{
  "kid_mode": true
}
```

**app.py** — i `load_settings()`, returnera fältet:
```python
# Befintlig funktion returnerar redan hela settings-dict.
# Kontrollera att "kid_mode" ingår med default True om det saknas:
settings.setdefault("kid_mode", True)
```

**index.html** — direkt efter DOMContentLoaded (rad ~3787), hämta flaggan:
```javascript
// Lägg till i window.addEventListener('DOMContentLoaded', ...) INNAN renderProjects():
const _settingsResp = await fetch('/api/settings').catch(() => ({}));
const _s = _settingsResp.json ? await _settingsResp.json().catch(() => ({})) : {};
window.kidMode = _s.kid_mode ?? true;
document.body.classList.toggle('kid-mode', window.kidMode);
```

**index.html** — lägg till i `:root`-blocket (rad ~8):
```css
body.kid-mode .admin-only { display: none !important; }
```

**Godkänt när:**
- `GET /api/settings` returnerar `"kid_mode": true`
- `document.body.classList.contains('kid-mode')` är sant i konsolen
- Element med `.admin-only` är osynliga

---

## TASK-02 · Återställ `.gitignore`

**Fil:** `.gitignore`

Lägg tillbaka raden som togs bort:
```
intrim_result*.json
```

Verifiera: `git status` ska inte lista `intrim_result.json` eller `intrim_result_concrete.json`.

---

## TASK-03 · Välkomstskärmen

**Fil:** `index.html` rad 876–882

```html
<!-- FÖRE -->
<div class="empty-icon">🏢</div>
<div class="empty-title">IT-teamet väntar på din beställning</div>
<div class="empty-sub" style="max-width:340px;">
  Beskriv din idé — teamet analyserar krav, granskar parallellt och levererar en komplett specifikation redo att skicka till Lovable, Claude eller Cursor.
  <br><br>
  <span style="font-size:11px;color:var(--text3);">Fas 1 → Kravanalys &nbsp;·&nbsp; Fas 2 → Specialistgranskning &nbsp;·&nbsp; Fas 3 → Specifikation</span>
</div>

<!-- EFTER -->
<div class="empty-icon">🚀</div>
<div class="empty-title">Vad vill du bygga idag?</div>
<div class="empty-sub" style="max-width:340px;">
  Berätta din idé — så sköter jag resten!
  <br><br>
  <span style="font-size:11px;color:var(--text3);">
    Jag förstår idén &nbsp;·&nbsp; Kontrollerar allt &nbsp;·&nbsp; Skriver en plan åt dig
  </span>
</div>
```

---

## TASK-04 · Ta bort "klistra in i din byggare" — 2 ställen

**Fil:** `index.html`

**Ställe 1** — rad ~1883–1884 (inuti `renderQueueBox`, kö-kortets action-block):
```javascript
// FÖRE:
actions = `<button class="btn btn-primary" onclick="startBuild('${it.id}', this)">▶ Bygg nästa</button>
           <span style="font-size:11px;color:var(--text3);">Specen kopieras — klistra in i din byggare</span>`;
// EFTER:
actions = `<button class="btn btn-primary" onclick="startBuild('${it.id}', this)">▶ Bygg det här!</button>`;
```

**Ställe 2** — rad ~1963 (inuti `startBuild()`):
```javascript
// FÖRE:
showToast('📋 Spec kopierad — klistra in i din byggare. Kom tillbaka med resultatet!', 4500);
// EFTER:
showToast('✅ Bygget är igång! Jag meddelar dig när det är klart.', 4000);
```

---

## TASK-05 · Dölj inställningspanelen (kräver TASK-01)

**Fil:** `index.html`

Hitta settings-knappen i headern (sökt med `onclick="openSettings()"`):
```html
<!-- Lägg till admin-only -->
<button class="btn btn-ghost admin-only" onclick="openSettings()">Inställningar ...</button>
```

Hitta `<div class="modal-bg" id="settingsModal">`:
```html
<div class="modal-bg admin-only" id="settingsModal">
```

---

## TASK-06 · Barnvänliga kö-statustexter

**Fil:** `index.html` rad ~1857

```javascript
// FÖRE:
const _Q_STATUS_LABEL = { 'kö': 'I kö', 'byggs': 'Byggs', 'behover_dig': 'Behöver dig', 'klar': 'Klar' };

// EFTER:
const _Q_STATUS_LABEL = window.kidMode
  ? { 'kö': '🕐 Väntar på sin tur', 'byggs': '⏳ Bygger just nu...', 'behover_dig': '🙋 Behöver din hjälp', 'klar': '✅ Klart!' }
  : { 'kö': 'I kö', 'byggs': 'Byggs', 'behover_dig': 'Behöver dig', 'klar': 'Klar' };
```

---

## TASK-07 · Lägg tillbaka förklaring under läge-knapparna (REGRESSION)

**Fil:** `index.html`

Lägg till en `div` direkt efter `.mode-btns`-blocket (efter rad ~751):
```html
<div id="modeHelp" style="font-size:13px;color:var(--text2);margin-top:10px;line-height:1.6;
  padding:8px 12px;background:var(--bg3);border-radius:var(--r-md);min-height:40px;"></div>
```

I `setMode()`-funktionen (rad ~1222), lägg till sista raden:
```javascript
const _MODE_HELP_KID = {
  ny_funktion: '💡 Berätta vad du vill bygga — jag förstår din idé och skriver en plan!',
  granska_kod: '🔍 Jag läser igenom din kod och berättar vad som kan bli bättre.',
  buggrapport: '🐛 Beskriv vad som gick fel — jag hittar problemet och skriver en fix.',
};
const helpEl = document.getElementById('modeHelp');
if (helpEl) helpEl.textContent = window.kidMode ? (_MODE_HELP_KID[mode] || '') : '';
```

---

## TASK-08 · Byt läge-knappars undertitlar

**Fil:** `index.html` rad ~745–751

```html
<!-- FÖRE -->
💡 Ny funktion<br><small style="font-weight:400;font-size:11px">Idé → färdig spec</small>
🔍 Granska kod<br><small style="font-weight:400;font-size:11px">Kod → backlog</small>
🐛 Buggrapport<br><small style="font-weight:400;font-size:11px">Fel → fix-spec</small>

<!-- EFTER -->
💡 Bygg något nytt<br><small style="font-weight:400;font-size:11px">Berätta vad du vill ha</small>
🔍 Kolla min kod<br><small style="font-weight:400;font-size:11px">Låt mig hitta problem</small>
🐛 Något är trasigt<br><small style="font-weight:400;font-size:11px">Hjälp mig fixa felet</small>
```

---

## TASK-09 · Dölj "Extra kontext"-fält (REGRESSION, kräver TASK-01)

**Fil:** `index.html`

Hitta blocket med `id="preContextInput"` (~rad 766) och linda det:
```html
<div class="admin-only">
  <div class="section-label">Extra kontext ...</div>
  <textarea id="preContextInput" ...></textarea>
</div>
```

Gör samma för `id="postContextInput"` (~rad 853).

---

## TASK-10 · Byt fasrubriker i resultatvyn

**Fil:** `index.html` rad 908, 917, 927

```javascript
// Kör direkt efter kidMode sätts (i DOMContentLoaded):
if (window.kidMode) {
  const labels = {
    'Fas 1 — Kravanalys':         'Del 1 — Jag förstår din idé',
    'Fas 2 — Specialistgranskning': 'Del 2 — Jag kontrollerar allt',
    'Fas 3 — Specifikation':       'Del 3 — Din byggplan',
  };
  document.querySelectorAll('.phase-label').forEach(el => {
    el.textContent = labels[el.textContent.trim()] || el.textContent;
  });
}
```

Alternativt: redigera HTML-texterna direkt + lägg till `data-admin`-attribut för admin-texten.

---

## TASK-11 · Laddningsskärmens text + dynamisk siffra

**Fil:** `index.html` rad 891–898

```html
<!-- FÖRE -->
<span>Kravanalytikern tolkar din idé</span>
<span id="lp2text">Specialisterna granskar parallellt</span>
<span>Promptsmeden skriver spec · Kompletthetscheck</span>

<!-- EFTER -->
<span>Jag läser och förstår din idé...</span>
<span id="lp2text">Jag kontrollerar allt noga...</span>
<span>Jag skriver din byggplan...</span>
```

Rad ~1695 — uppdatera `lp2text` dynamiskt:
```javascript
// FÖRE:
if (lp2text && total) lp2text.textContent = `${done}/${total} specialister klara`;
// EFTER:
if (lp2text && total) lp2text.textContent = `${done} av ${total} kontroller klara`;
```

---

## TASK-12 · Byt "Beställarläge"/"Teknisk läge" (kräver TASK-01)

**Fil:** `index.html` rad 930–931

```html
<!-- FÖRE -->
<button class="view-btn active" id="vt-bestallare" onclick="setSpecView('bestallare')">🧑‍💼 Beställarläge</button>
<button class="view-btn" id="vt-teknisk" onclick="setSpecView('teknisk')">👩‍💻 Teknisk läge</button>

<!-- EFTER -->
<button class="view-btn active" id="vt-bestallare" onclick="setSpecView('bestallare')">📋 Enkel vy</button>
<button class="view-btn admin-only" id="vt-teknisk" onclick="setSpecView('teknisk')">👩‍💻 Teknisk vy</button>
```

---

## TASK-13 · Barnvänlig varning vid trasigt projekt

**Fil:** `index.html` — `startBuild()`-funktionen (rad ~1951)

Lägg till guard FÖRE det befintliga `fetch`-anropet:
```javascript
async function startBuild(id, btn) {
  // KID-GUARD: varna om annat projekt är trasigt
  if (window.kidMode) {
    const items = window._lastQueueItems || [];
    const broken = items.find(i =>
      i.status === 'behover_dig' && i.id !== id
    );
    if (broken) {
      const go = window.confirm(`⚠️ "${broken.title}" behöver fixas!\nVill du ändå bygga vidare?`);
      if (!go) return;
    }
  }
  // ... befintlig kod fortsätter
```

OBS: Byt `confirm()` mot inline-dialog när TASK-17 är klar.

---

## TASK-14 · Historikvy — dölj råa lägesnamn

**Fil:** `index.html` — `loadHistory()`, inuti `sessions.map()` (rad ~3030)

```javascript
const _MODE_LABEL = {
  ny_funktion: '💡 Nytt',
  granska_kod: '🔍 Granskning',
  buggrapport: '🐛 Bugg',
};

// Byt:
`<span class="history-mode">${escHtml(s.mode)}</span>`
// Till:
`<span class="history-mode">${escHtml(_MODE_LABEL[s.mode] || s.mode)}</span>`
```

CSS rad 521 — ta bort `text-transform: uppercase` från `.history-mode`.

---

## TASK-15 · Dölj `push_to_github.bat` (kräver TASK-01)

**Fil:** `index.html` rad 725–726

```html
<!-- Ge bannern admin-only -->
<div id="mainNoRepoBanner" class="admin-only" style="display:none; ...">
```

Rad ~1015 i `#settingsModal` — ge paragrafen `admin-only`:
```html
<div style="font-size:11px;color:var(--text3);margin-top:4px;" class="admin-only">
  Fylls i automatiskt av push_to_github.bat
</div>
```

---

## TASK-16 · Dölj agentkort och kostnadsrad (kräver TASK-01)

**Fil:** `index.html` rad 920–921

```html
<div class="agents-grid admin-only" id="agentsGrid"></div>
<span class="phase-stat admin-only" id="reviewStat"></span>
```

Lägg till `renderKidSummary(results)` som anropas istället i barnläge:
```javascript
function renderKidSummary(results) {
  const ok = results.filter(r => r.verdict === 'GODKÄND').length;
  const bad = results.filter(r => r.verdict === 'UNDERKÄND').length;
  const total = results.length;
  const el = document.getElementById('kidSummaryBox');
  if (!el) return;
  el.innerHTML = bad === 0
    ? `<div style="color:var(--green);font-weight:600;">✅ Allt ser bra ut! (${total} kontroller)</div>`
    : `<div style="color:var(--yellow);font-weight:600;">⚠️ Jag hittade ${bad} saker att titta på.</div>`;
}
```

Lägg till `<div id="kidSummaryBox" style="padding:8px 0;"></div>` direkt efter `#reviewStat`.

---

## TASK-17 · Ersätt alert()/confirm() med inline-meddelanden

**Fil:** `index.html`

**Rad ~1525** — alert vid vag buggrapport:
```javascript
// FÖRE:
alert('Beskriv felet utförligare — minst en mening...');
// EFTER:
const hint = document.getElementById('bugDescHint');
if (hint) { hint.style.display = 'block'; hint.textContent = '💡 Berätta lite mer! Vad händer? Vad hoppades du på?'; }
return;
```
Lägg till `<div id="bugDescHint" style="display:none;color:var(--yellow);font-size:12px;margin-top:4px;"></div>` under `#bugDescInput`.

**Rad ~1575** — alert vid tom kod/bugg:
```javascript
// FÖRE: alert('Beskriv felet och/eller klistra in koden.');
// EFTER: showToast('💡 Beskriv felet, eller klistra in koden nedan.', 3000); return;
```

**"Markera klar ändå"-knappen** — lägg till `admin-only` (se TASK-01).

---

## TASK-18 · Dölj "Byggsätt"-fliken (kräver TASK-01)

**Fil:** `index.html` rad ~1064 + `#tab-byggsatt`-diven

```html
<button class="modal-tab admin-only" onclick="switchProjTab('byggsatt')">🛠️ Byggsätt</button>
<div class="tab-pane admin-only" id="tab-byggsatt">...</div>
```

---

## TASK-19 · Dölj "🔬 Agentgranskning"-knappen (kräver TASK-01)

**Fil:** `index.html` rad 934

```html
<button class="btn btn-ghost admin-only" onclick="exportAgentAudit()" ...>🔬 Agentgranskning</button>
```

---

## TASK-20 · Fixa buggrapport-fältets etikett

**Fil:** `index.html` — `#bugLogsInput`-blocket

```html
<!-- FÖRE label -->
📋 Felmeddelande / loggar <span>(valfritt — guld för rotorsaksanalysen)</span>
<!-- placeholder -->
Klistra in stacktrace, konsol-fel eller serverlogg...

<!-- EFTER label -->
📋 Ser du ett rött felmeddelande? <span style="font-weight:400">(valfritt)</span>
<!-- placeholder -->
Klistra in det röda felmeddelandet, om du har ett...
```

---

## TASK-21 · Fixa attention-bannern

**Fil:** `index.html` — `updateAttentionBanner()`

```javascript
attentionText.textContent = window.kidMode
  ? `🙋 '${redItem?.title || 'Ett projekt'}' behöver din hjälp!`
  : `⚠ ${needs} bygge${needs > 1 ? 'n' : ''} väntar på din kontroll`;
```

---

## TASK-22 · Fixa "HEMLIGHET HITTAD"-texten i app.py

**Fil:** `app.py` — `hemlighetsvakten`-agenten (lokal kod, ej pushad ännu)

Sök efter strängen `"HEMLIGHET HITTAD"` och byt till:
```python
secret_titles = ["⚠️ Koden innehåller något känsligt — be en vuxen titta på det"]
```

---

## TASK-23 · Dölj Supabase-bannerns SQL-text

**Fil:** `index.html` — `dbWarningBanner`-uppdateringslogiken

```javascript
// Sök efter den rad som sätter banner.innerHTML med "supabase_setup.sql"
// Lägg till kidMode-check:
banner.innerHTML = window.kidMode
  ? `⚠️ Systemet behöver en uppdatering. Be en vuxen hjälpa dig.`
  : `⚠️ Supabase-schemat ligger efter — kör supabase_setup.sql i SQL Editor.`;
```

---

## TASK-36 · Byt run-knappens text + depth-tooltips

**Fil:** `index.html` rad 862–866

```html
<!-- FÖRE -->
<button class="depth-btn" id="depth-snabb" title="7 kärnagenter — snabb iteration (~25s)">⚡ Snabbläge</button>
<button class="depth-btn active" id="depth-djup" title="Hela teamet — gedigen leverans (~60s)">🏢 Djupläge</button>
<button class="btn btn-primary" id="runBtn" onclick="runReview()">
  ▶ Skicka till teamet
</button>

<!-- EFTER -->
<button class="depth-btn" id="depth-snabb" title="Snabbare (~25s)">⚡ Snabb kontroll</button>
<button class="depth-btn active" id="depth-djup" title="Noggrannare (~60s)">🔍 Noggrann kontroll</button>
<button class="btn btn-primary" id="runBtn" onclick="runReview()">
  ▶ Kör!
</button>
```

I `setMode()` — uppdatera knapp-text dynamiskt:
```javascript
const _RUN_LABEL = {
  ny_funktion: '▶ Förstå min idé!',
  granska_kod: '▶ Kolla koden!',
  buggrapport: '▶ Hitta felet!',
};
const runBtn = document.getElementById('runBtn');
if (runBtn && !runBtn.disabled) runBtn.textContent = _RUN_LABEL[mode] || '▶ Kör!';
```

---

## TASK-37 · Byt kravBox-titel

**Fil:** `index.html` — `renderKravBox()` rad ~2315

```javascript
// FÖRE:
`<div class="krav-title">📋 Kravanalytikern</div>`

// EFTER:
`<div class="krav-title">📋 ${window.kidMode ? 'Jag förstår din idé så här:' : 'Kravanalytikern'}</div>`
```

---

## TASK-40 · Dölja Byggresultat-modalen i barnläge (kräver TASK-01)

**Fil:** `index.html` — `startBuild()`-funktionen rad ~1971–1977

```javascript
// Nuvarande kod öppnar buildResultModal efter att ha kopierat spec till clipboard.
// Lägg till guard FÖRE clipboard-anropet:
if (window.kidMode) {
  showToast('⏳ Bygget är skickat! Jag meddelar dig när det är klart.', 5000);
  if (btn) { btn.disabled = false; btn.textContent = '▶ Bygg det här!'; }
  return;
}
// ... befintlig kod med navigator.clipboard och openBuildResult()
```

---

## TASK-41 · Ge Projektprofil-fliken admin-only (kräver TASK-01)

**Fil:** `index.html` rad ~1062 + `#tab-profile`-diven

```html
<button class="modal-tab admin-only" onclick="switchProjTab('profile')">📋 Projektprofil</button>
<div class="tab-pane admin-only" id="tab-profile">...</div>
```

*Alternativ:* Behåll fliken men ge enbart "Teknikstack", "Arkitektur", "Kodkonventioner" och "Constraints"-blocken klassen `admin-only`. "Projektets syfte" kan barnet faktiskt fylla i.

---

## TASK-38 · Byt completenessBox-texter

**Fil:** `index.html` — `renderCompletenessBox()` rad ~2337

```javascript
// FÖRE:
isComplete ? '✅ Specifikationen är komplett' : '⚠️ Specifikationen kan förbättras'

// EFTER:
isComplete ? '✅ Din plan är redo att byggas!' : '⚠️ Din plan kan bli ännu bättre'
```

Lägg till poäng-förklaring under score-diven:
```javascript
`<div class="completeness-score ${cls}">${score}<span style="font-size:12px">/10</span></div>
${window.kidMode ? `<div style="font-size:11px;color:var(--text3);text-align:center;">hur komplett din plan är</div>` : ''}`
```

---

## TASK-39 · Rensa tekniska toast-meddelanden

**Fil:** `index.html` — lägg till hjälpfunktion direkt efter `showToast()`-definitionen:

```javascript
function kidToast(kidMsg, adminMsg, duration = 3000) {
  showToast(window.kidMode ? kidMsg : (adminMsg || kidMsg), duration);
}
```

Byt sedan ut dessa specifika anrop:

| Sök | Ersätt med |
|---|---|
| `showToast('Klistra in den byggda koden först.')` | `kidToast('Klistra in koden du fick.', 'Klistra in den byggda koden först.')` |
| `showToast('✅ Bygget godkänt och verifierat — nästa i kön är redo!', 5000)` | `kidToast('✅ Bra jobbat! Nästa projekt kan börja.', '✅ Bygget godkänt — nästa i kön är redo!', 5000)` |
| `` showToast(`⚠ Granskningen hittade ${n} kvarstående problem — se kortet.`, 5000) `` | `` kidToast(`⚠️ Jag hittade ${n} saker att fixa — se kortet.`, `⚠ ${n} kvarstående problem`, 5000) `` |
| `showToast('Ingen spec att köa.')` | `kidToast('Välj en plan att bygga först.', 'Ingen spec att köa.')` |
| `` showToast(`✅ Lagd i byggkön...`, 4000) `` | `` kidToast(`✅ Tillagd! Öppna 'Att bygga' för att starta.`, `✅ Lagd i byggkön`, 4000) `` |
| `showToast('⚠️ Promptsmeden behöver mer info...')` | `kidToast('Jag behöver mer info — beskriv lite mer.', '⚠️ Promptsmeden behöver mer info...')` |
| `showToast('⬇ Exporterad som Markdown')` | `kidToast('⬇ Filen är nedladdad!', '⬇ Exporterad som Markdown')` |
| `showToast('❌ ' + e.message)` | `kidToast('❌ Något gick fel. Försök igen.', '❌ ' + e.message)` |

---

## TASK-42 · Byt "Kvarstående:" i kö-korten

**Fil:** `index.html` — `renderQueueBox()` rad ~1892

```javascript
// FÖRE:
`<div class="qc-verdict"><b>Kvarstående:</b>${...}</div>`

// EFTER:
`<div class="qc-verdict"><b>${window.kidMode ? '⚠️ Behöver fixas:' : 'Kvarstående:'}</b>${...}</div>`
```

---

## TASK-43 · GitHub-sektionens labels

**Fil:** `index.html` — `#githubSection` (rad ~785–835)

```javascript
// I updateGithubSection() eller motsvarande init-funktion:
if (window.kidMode) {
  // Tooltip på Förhandsgranska-knappen
  const fetchBtn = document.getElementById('fetchBtn');
  if (fetchBtn) fetchBtn.title = 'Hämta den senaste koden';

  // "Gren:"-labeln
  const grenLabel = document.querySelector('#githubProjRow span[style*="font-size:11px"]');
  if (grenLabel && grenLabel.textContent.trim() === 'Gren:') grenLabel.textContent = 'Version:';

  // Default github-status text
  setGithubStatus('Klistra in koden, eller hämta från GitHub ovan');
}
```

---

## P2-tasks (lägre prio, snabba byten)

Dessa är enrads-ändringar — gör dem i ett svep:

| Task | Fil | Ändring |
|---|---|---|
| **TASK-24** | `renderBacklogBox()` | `P0·Kritisk` → `🔴 Måste fixas` etc. med kidMode-check |
| **TASK-25** | `renderBacklogBox()` | `"→ Gör till spec & köa"` → `"▶ Bygg det här"` |
| **TASK-26** | Queue/backlog empty states | `"Kön är tom — lägg en spec i byggkön"` → `"Inget att bygga än!"` |
| **TASK-27** | `#byggsattRow` | Lägg till `class="admin-only"` |
| **TASK-28** | `renderQuestions()` | `"skapar jag rätt prompt"` → `"förstår jag exakt vad du vill ha"` |
| **TASK-29** | `renderQueueBox()` | `"försök N"` + `"✍️ vN"` → lägg till `admin-only` |
| **TASK-30** | `renderQueueBox()` | `"underkänd och måste bli grön"` → `"Lös X innan det här kan byggas"` |
| **TASK-31** | `statEl.innerHTML` | Dölj `💰 ~$X.XXX` när kidMode |
| **TASK-32** | `loadAttBygga()` | Toast vid reset av stale "byggs" |
| **TASK-33** | `renderQueueBox()` | `"Markera klar ändå"` → lägg till `admin-only` |

---

## Verifieringssteg efter varje task

```bash
# Kör i webbläsarkonsolen för att verifiera TASK-01:
window.kidMode          // ska vara true
document.body.classList.contains('kid-mode')  // ska vara true
document.querySelectorAll('.admin-only').length  // ska vara > 0
getComputedStyle(document.querySelector('.admin-only')).display  // ska vara "none"
```

Manuellt test för varje task: öppna appen, kontrollera att det tekniska elementet är borta och att ett barnvänligt ersättningselement visas på rätt plats.

---

## Vad som INTE ska ändras

- `app.py` backend-logik (utom TASK-22 hemlighetsvakten)
- Agent-IDs, prompt-texter, AI-logik
- Supabase-schema
- `settings.json` API-nycklar
- GitHub-integrationen i sig (bara labels och tooltips)

---

*Skapat av: Claude Sonnet 4.6 · Baserat på genomgång av 43 tasks i KID_USER_PROMPT.md mot live-kod i origin/main (3654bd7)*
