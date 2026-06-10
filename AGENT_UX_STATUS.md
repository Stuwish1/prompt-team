# AGENT_UX_STATUS — UX-granskning av index.html

> **Granskad:** 2026-06-10, iteration 6
> **Bas:** index.html (4121 rader, trunkerad — se T1 i BYGG_TASKS.md)
> **Metod:** Statisk kodanalys av funktioner, flöden, HTML-struktur och interaktionsmönster.
> **Primär persona:** 10-åring utan teknisk bakgrund (KID_USER_PROMPT.md)

---

## SNABBSAMMANFATTNING

| Svårighetsgrad | Antal | Blockar kernflöde? |
|---|---|---|
| 🔴 Kritisk | 6 | Ja — startar bygge, ser resultat, förstår status |
| 🟡 Medel | 8 | Delvis — friction, förlust av kontext |
| 🟢 Liten | 5 | Nej — polish och konsekvens |

**Viktigaste att fixa innan chatbox-featuren (T4–T6) byggs:**
UX-1 (alert-dialoger), UX-2 (clipboard-bygge), UX-5 (AGENT_DISPLAY_NAMES), UX-6 (queueDelete ingen bekräftelse).

---

## 🔴 KRITISKA UX-PROBLEM

---

### UX-1 — `alert()` används för valideringsfel (6 ställen)

**Fil:** `index.html`
**Rader:** 1329, 1609, 1655, 1657, 1659, 1661

Browser-native `alert()` fryser UI:t, ser ut som ett OS-fel och är speciellt skrämmande för barn. Ingen av dem ger ledtrådar om _hur_ felet ska åtgärdas.

**Ställen att byta ut:**
```
1329 — Max 6 skärmdumpar               → inline toast / disabled-state på dropzone
1609 — Buggrapport för kort            → röd inline text under bugDescInput
1655 — GitHub-fetch misslyckades       → setGithubStatus(msg, 'error')
1657 — Beskriv vad du vill bygga       → röd outline + shake på ideaInput
1659 — Beskriv felet och/eller kod     → röd outline + shake på bugDescInput
1661 — Klistra in kod att granska      → röd outline + shake på codeInput
```

**Fix — hjälpfunktion att lägga till (före runReview):**
```javascript
function showFieldError(fieldId, msg) {
  const el = document.getElementById(fieldId);
  if (!el) { showToast('⚠️ ' + msg, 4000); return; }
  el.style.outline = '2px solid var(--red)';
  el.style.animation = 'shake .25s ease';
  setTimeout(() => { el.style.outline = ''; el.style.animation = ''; }, 1800);
  showToast('⚠️ ' + msg, 4000);
  el.focus();
}
```

Lägg till `@keyframes shake { 0%,100%{transform:translateX(0)} 25%,75%{transform:translateX(-4px)} 50%{transform:translateX(4px)} }` i `<style>`.

**Verifiera:** Lämna ideaInput tom → klicka Skicka → ingen `alert()`, istället röd puls + toast.

---

### UX-2 — `startBuild()` kopierar till clipboard utan förhandsvisning

**Fil:** `index.html`, funktion `startBuild()` (~rad 2111)

Flödet idag:
1. Användaren klickar "▶ Bygg nästa"
2. Backend skriver om spec → returnerar text
3. `navigator.clipboard.writeText(spec)` körs tyst
4. Toast: "Spec kopierad — klistra in i din byggare"

Problem:
- Användaren ser aldrig vad som kopierades
- `clipboard.writeText` misslyckas utan användargesten i vissa browsers + kräver HTTPS
- `catch(() => {})` sväljer felet helt — toast säger "Spec kopierad" även om clipboard failade
- Barn vet inte vad "klistra in i din byggare" betyder eller VAR de ska klistra in

**Temporär fix (UX, ingen ny feature krävs):**
Lägg till en synlig specbox i "Att bygga"-sektionen under queue-kortet vid `status === 'byggs'`. När `startBuild` lyckas: visa spec i en `<textarea readonly>` med en "Kopiera"-knapp. Inte bara en toast.

```javascript
// I startBuild(), efter await loadAttBygga():
const specBox = document.getElementById('builtSpecDisplay');
if (specBox) {
  specBox.value = spec;
  specBox.style.display = 'block';
  specBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
```

Lägg till i HTML (i `#attByggaView`, efter `#queueBox`):
```html
<div id="builtSpecDisplay" style="display:none;margin-top:12px;">
  <div style="font-size:12px;font-weight:600;margin-bottom:6px;color:var(--text2);">📋 Specen du ska klistra in i din byggare:</div>
  <textarea readonly rows="8" style="font-family:var(--mono);font-size:11px;background:var(--bg3);width:100%;resize:vertical;"></textarea>
  <div style="display:flex;gap:8px;margin-top:6px;">
    <button class="btn btn-primary" onclick="navigator.clipboard.writeText(document.getElementById('builtSpecDisplay').querySelector('textarea').value);showToast('✅ Kopierad!')">📋 Kopiera allt</button>
    <button class="btn btn-ghost" onclick="document.getElementById('builtSpecDisplay').style.display='none'">Stäng</button>
  </div>
</div>
```

**Verifiera:** Klicka "Bygg nästa" → spec visas i textarea-rutan under kön, kopieringsknappen fungerar.

---

### UX-3 — Attention-banner visas på fel vyer

**Fil:** `index.html`, `updateAttentionBanner()` (~rad 2097)

Bannern `⚠ 1 bygge väntar på din kontroll` visas hela tiden, även i Beställ-vyn och Historik-vyn. Användaren kan inte göra något åt det på de vyerna — det skapar oro utan handlingsväg.

**Fix:** Visa bannern bara när `status === 'behover_dig'` OCH inte i 'bygga'-vyn (för då är man redan rätt ställe):

```javascript
function updateAttentionBanner() {
  const needs = (_queueItems || []).filter(i => i.status === 'behover_dig').length;
  const banner = document.getElementById('attentionBanner');
  if (!banner) return;
  const inBygga = document.body.className === 'view-bygga';
  banner.style.display = (needs > 0 && !inBygga) ? 'flex' : 'none';
  if (needs > 0) {
    document.getElementById('attentionText').textContent =
      needs === 1 ? '⚠ 1 bygge behöver din granskning' : `⚠ ${needs} byggen behöver din granskning`;
  }
}
```

Anropa även `updateAttentionBanner()` i slutet av `switchView()` så bannern döljs korrekt vid vynavigering.

**Verifiera:** Skapa ett 'behover_dig'-item → gå till Beställ → bannern syns. Gå till Att bygga → bannern döljs.

---

### UX-4 — Att-bygga-vyn saknar CTA när den är tom

**Fil:** `index.html`, `renderBacklogBox()` + `renderQueueBox()` (~rad 2331, 2001)

När ingen backlog och tom kö: användaren ser:
```
"Inga fynd ännu — kör en granskning i Beställ-vyn."
"Kön är tom — lägg en spec i byggkön så hamnar den här."
```

Ingen klickbar åtgärd. Barn vet inte hur de "lägger en spec i byggkön".

**Fix i `renderQueueBox()`** — lägg till CTA-knapp när kön är tom:
```javascript
if (!items.length) {
  box.innerHTML = `<div style="text-align:center;padding:28px 0 20px;">
    <div style="font-size:28px;margin-bottom:8px;">🏗️</div>
    <div style="font-size:13px;font-weight:600;color:var(--text1);margin-bottom:4px;">Ingen spec i kön</div>
    <div style="font-size:12px;color:var(--text3);margin-bottom:14px;">Kör en granskning — klicka på "Godkänn" på ett fynd för att lägga det i byggkön.</div>
    <button class="btn btn-primary" onclick="switchView('bestall')">→ Gå till Beställ</button>
  </div>`;
  if (stat) stat.textContent = '';
  updateAttentionBanner();
  return;
}
```

**Verifiera:** Tom kö → CTA-knapp "→ Gå till Beställ" visas och fungerar.

---

### UX-5 — AGENT_DISPLAY_NAMES har bara 8 av 34 agenter

**Fil:** `index.html`, `const AGENT_DISPLAY_NAMES` (~rad 1357)

Backend har 34+ agenter men frontendens namnkarta har bara 8. I Fas 2-granskningsresultaten visas unknown agenter med sitt interna ID:
- `hemlighetsvakten` → visas som "hemlighetsvakten" (ingen emoji, inget snyggt namn)
- `rotorsak`, `backend`, `krypto`, `concurrency`, `agent_arkitektur` → raw IDs

**Fix:** Se BYGG_TASKS.md T11/T35 för komplett lista. Snabbfix — lägg till de vanligaste som fattas:

```javascript
const AGENT_DISPLAY_NAMES = {
  kravanalytikern:    '📋 Kravanalytikern',
  architecture:       '🏗️ Arkitekten',
  security:           '🔐 Säkerhetsagenten',
  ux:                 '🎨 UX-agenten',
  database:           '🗄️ Databasagenten',
  api:                '🔌 API-agenten',
  performance:        '⚡ Prestandaagenten',
  error_handling:     '🛡️ Felhanteringsagenten',
  edge_case:          '🔦 Kantfallsagenten',
  risk:               '⚠️ Riskvärderaren',
  integration:        '🔗 Integrationsanalytikern',
  i18n:               '🌍 Internationaliseringsagenten',
  accessibility:      '♿ Tillgänglighetsagenten',
  visual_qa:          '👁️ Visuell QA',
  mobile:             '📱 Mobilagenten',
  backend:            '⚙️ Backendagenten',
  frontend:           '🖥️ Frontendagenten',
  ai_ml:              '🤖 AI/ML-agenten',
  concurrency:        '🔀 Trådsäkerhetsagenten',
  krypto:             '🔑 Kryptografagenten',
  agent_arkitektur:   '🏛️ Agentarkitekten',
  hemlighetsvakten:   '🕵️ Hemlighetsvakten',
  dataskyddsjuristen: '⚖️ Dataskyddsjuristen',
  rotorsak:           '🔎 Rotorsaksanalytikern',
  prompt_smith:       '✍️ Promptsmeden',
  completeness:       '✅ Kompletthetsgranskaren',
  bestallarsammanfattaren: '🧑‍💼 Beställarsammanfattaren',
};
```

**Verifiera:** Kör en granskning i Djupläge → alla agentnamn i Fas 2 visar emoji + svenska namn.

---

### UX-6 — `queueDelete()` och `deleteSession()` saknar bekräftelse

**Fil:** `index.html`, rader ~2236 och ~3385

`queueDelete()` raderar direkt utan bekräftelse — ett missat klick tar bort ett bygge permanent.
`deleteSession()` använder `confirm()` (browser-native dialog, se UX-1).

**Fix `queueDelete()`** — lägg till inline confirm med undo-pattern (toast med timer):
```javascript
async function queueDelete(id) {
  // Optimistic: ta bort visuellt, ge ångra-knapp i 5 sekunder
  const item = _queueItems.find(x => x.id === id);
  const title = item?.title || 'Spec';
  showToast(`🗑 "${title.slice(0,30)}" borttagen — <button onclick="undoQueueDelete('${id}')" style="text-decoration:underline;background:none;border:none;color:inherit;cursor:pointer;font-size:12px;padding:0;">Ångra</button>`, 5000);
  _queueItems = _queueItems.filter(x => x.id !== id);
  renderQueueBox();
  // Faktisk radering efter 5s (eller om ångra klickas)
  window._pendingDelete = window._pendingDelete || {};
  window._pendingDelete[id] = setTimeout(async () => {
    await fetch('/api/build-queue/' + id, { method: 'DELETE' });
    delete window._pendingDelete[id];
  }, 5000);
}
async function undoQueueDelete(id) {
  if (window._pendingDelete?.[id]) {
    clearTimeout(window._pendingDelete[id]);
    delete window._pendingDelete[id];
    await loadAttBygga();
    showToast('↩ Återställd');
  }
}
```

**Fix `deleteSession()`** — ersätt `confirm()` med inline toast:
```javascript
async function deleteSession(e, id) {
  e.stopPropagation();
  showToast('Tryck igen för att bekräfta radering', 3000);
  if (deleteSession._pending === id) {
    clearTimeout(deleteSession._timer);
    deleteSession._pending = null;
    await fetch('/api/sessions/' + id, { method: 'DELETE' });
    if (_activeSessionId === id) { _activeSessionId = null; resetToEmpty(); }
    loadHistory();
    return;
  }
  deleteSession._pending = id;
  deleteSession._timer = setTimeout(() => { deleteSession._pending = null; }, 3000);
}
```

**Verifiera:** Klick 1 på 🗑 i queue → toast "borttagen + Ångra"-knapp. Ångra → item återkommer. Klick 2 utan ångra → item raderas permanent.

---

## 🟡 MEDEL UX-PROBLEM

---

### UX-7 — `loadHistory()` saknar sökning och paginering

**Fil:** `index.html`, `loadHistory()` (~rad 3300)

Alla sessioner laddas i ett enda anrop. Med 100+ sessioner: lång laddning, lång lista, inget sätt att hitta rätt.

**Min fix (sökning + paginering):** Se BYGG_TASKS.md T23 för backend-spec.

Frontend-tillägg: lägg till ett sök-input ovanför `#historyList`:
```html
<div style="padding:8px 14px 4px;">
  <input type="search" id="historySearch" placeholder="Sök session..."
    oninput="filterHistory(this.value)"
    style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r-md);padding:6px 10px;font-size:12px;color:var(--text1);">
</div>
```

```javascript
function filterHistory(q) {
  document.querySelectorAll('.history-item').forEach(el => {
    const text = el.querySelector('.history-name')?.textContent || '';
    el.style.display = text.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
  });
}
```

---

### UX-8 — Projekt lagras i localStorage men backend har `/api/projects`

**Fil:** `index.html`, `getProjects()`, `setProjects()`, `ensureMainProject()` (~rad 3403)

`getProjects()` läser från `localStorage`. Backend har nu `/api/projects` (se BYGG_TASKS.md T28b). De kan divergera — ny flik, annat browser, rensat localStorage → projekt försvinner.

**Fix (partiell, utan full T28b):** Lägg till en sync vid startup och vid projekt-switch:
```javascript
async function syncProjectsFromServer() {
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) return;
    const serverProjects = await res.json();
    if (serverProjects?.length) {
      setProjects(serverProjects);
      renderProjects();
      renderHeaderProjectSelect();
    }
  } catch {}
}
```
Anropa `syncProjectsFromServer()` i DOMContentLoaded-blocket.

---

### UX-9 — `kontrolleraBuild()` visar resultat bara som toast

**Fil:** `index.html`, `kontrolleraBuild()` (~rad 2140)

När "Kontrollera" är klar visas bara en toast: "GODKÄNT" eller "UNDERKÄNT — X problem". Användaren ser inte VILKA problem som hittades utan att klicka runt.

**Fix:** Visa verdict inline i queue-kortet direkt efter `kontrolleraBuild` returnerar. `renderQueueBox()` anropas redan via `loadAttBygga()` — `last_verdict.kvarstaende` ska visas i `qc-verdict`-blocket. Verifiera att `last_verdict` sparas korrekt i `_queueItems` efter review.

---

### UX-10 — Mode-toggle hjälptext är förvirrande

**Fil:** `index.html`, `<div id="modeHelp">` (~rad 868)

"Beskriv din idé — teamet analyserar, granskar och skriver en färdig beställning till din byggare."

Det stämmer för `ny_funktion`. För `granska_kod` borde det stå:
"Klistra in din kod — teamet hittar buggar och förbättringsförslag."
För `buggrapport`:
"Beskriv felet — teamet hittar rotorsaken och skriver en fix-spec."

**Fix i `setMode()`:** Uppdatera `modeHelp`-texten per läge:
```javascript
const modeHelp = {
  ny_funktion:  'Beskriv vad du vill ha — teamet analyserar, granskar och skriver en färdig spec till din byggare.',
  granska_kod:  'Klistra in din kod — teamet hittar buggar, säkerhetsbrister och förbättringsförslag.',
  buggrapport:  'Beskriv felet och klistra in koden — teamet hittar rotorsaken och skriver en fix-spec.',
};
document.getElementById('modeHelp').textContent = modeHelp[mode] || '';
```

---

### UX-11 — Historyvisning: `loadSession()` byter alltid till 'bestall'-vyn

**Fil:** `index.html`, `loadSession()` (~rad 3335)

`switchView('bestall')` körs alltid när en session laddas, även om användaren är i 'historik'-vyn och vill se resultaten utan att flytta sig.

**Fix:** Lägg till "Öppna i Beställ"-länk i history-item istället för att forcera switchView:
```javascript
// Visa resultaten inline i historik-panelen, eller ge en explicit knapp:
// I history-item HTML, lägg till en expanderbar resultatsektion
```

Alternativt: kalla `switchView('bestall')` men scrolla automatiskt till resultat-panelen:
```javascript
switchView('bestall');
setTimeout(() => document.getElementById('resultsView')?.scrollIntoView({behavior:'smooth'}), 200);
```

---

### UX-12 — Health-status är för liten och svår att se

**Fil:** `index.html`, `healthBadge` + `updateHealthBadges()` (~rad 1519)

`healthBadge` är en tiny span inuti "Inställningar"-knappen. Användare märker inte om API-nyckeln saknas eller om Supabase är nere.

**Fix:** Gör health-badgen mer synlig med tooltip-stöd. Om någon tjänst är nere — visa ett `⚠️`-märke som pulserar:
```javascript
function updateHealthBadges(services) {
  const unhealthy = services.filter(s => s.status !== 'ok').length;
  const badge = document.getElementById('healthBadge');
  if (badge) {
    badge.textContent = unhealthy > 0 ? ' ⚠️' : ' ✓';
    badge.style.color = unhealthy > 0 ? 'var(--red)' : 'var(--green)';
    badge.title = unhealthy > 0 ? `${unhealthy} tjänst${unhealthy > 1 ? 'er' : ''} svarar inte — klicka för detaljer` : 'Alla tjänster OK';
  }
}
```

---

### UX-13 — Ingen återgångspunkt efter att byggare hoppar ur flödet

**Fil:** `index.html`, `switchView()` (~rad 1957)

T2-buggen: `document.body.className = 'view-' + name` skriver över alla CSS-klasser inklusive `builder-active`. Om chatbox-panelen är öppen och användaren klickar på en annan flik — stängs panelen utan att fråga.

Se BYGG_TASKS.md T2 för komplett fix.

---

### UX-14 — Tangentbordsgenväg Ctrl+Enter finns men syns inte i UI

**Fil:** `index.html`, `keydown`-lyssnare (i trunkerad sektion, ~rad 4067 i originalet)

Ctrl+Enter skickar till teamet. Ingen användare vet om detta.

**Fix:** Lägg till hint bredvid "Skicka till teamet"-knappen:
```html
<button class="btn btn-primary" id="runBtn" onclick="runReview()">
  ▶ Skicka till teamet
</button>
<span style="font-size:10px;color:var(--text3);margin-left:4px;">Ctrl+↩</span>
```

---

## 🟢 LITEN UX-POLISH

---

### UX-15 — `clearBacklog()` använder `confirm()`

**Fil:** `index.html`, `clearBacklog()` (~rad 2419)

Ersätt `if (!confirm('...'))` med dubbelklick-pattern eller toast-ångra (se UX-6).

---

### UX-16 — Toast stöder inte HTML men UX-6 kräver det

**Fil:** `index.html`, `showToast()` (~rad 4053)

`showToast` använder `textContent` vilket inte renderar HTML. UX-6:s ångra-knapp kräver HTML.

**Fix:** Ändra `showToast` att använda `innerHTML` istället för `textContent`:
```javascript
function showToast(msg, duration = 3000) {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.innerHTML = msg;  // var: t.textContent = msg
  t.className = 'toast show';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), duration);
}
```

---

### UX-17 — `renderQueueBox` visar `klar`-items utan dölj-alternativ

**Fil:** `index.html`, `renderQueueBox()` (~rad 2001)

Avklarade byggen (`status: 'klar'`) visas alltid i listan. En lång historia av klarade byggen täpper igen kön-vyn.

**Fix:** Lägg till ett toggle-checkbox "Visa avklarade" ovanför kön:
```html
<label style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:4px;cursor:pointer;">
  <input type="checkbox" id="showCompleted" onchange="renderQueueBox()"> Visa avklarade
</label>
```

I `renderQueueBox()`: filtrera `items` baserat på checkbox-state.

---

### UX-18 — Skärmdump-gräns säger "Max 6" i alert men dropzone säger ingenting

**Fil:** `index.html`, dropzone (~rad 878), `_addScreenshot()` (~rad 1327)

Lägg till en räknare i dropzone-texten som uppdateras: "Klicka eller dra (0/6 bilder)".

---

### UX-19 — "Att bygga"-fliken har badge men badge nollställs inte korrekt

**Fil:** `index.html`, `refreshByggaBadge()` (~rad 2081)

Badge räknar `'öppen' + 'återkommit'` i backlog + aktiva i kön. Men efter att ett item godkänns och sätts till `'klar'` dröjer badge-uppdateringen tills nästa manuella reload. `refreshByggaBadge()` anropas inte i `kontrolleraBuild()` → badge kan visa gammalt värde.

**Fix:** Lägg till `refreshByggaBadge()` i `kontrolleraBuild()` efter `loadAttBygga()`.

---

## PRIORITERAD ÅTGÄRDSORDNING FÖR BYGGAREN

| Sprint | UX-task | Fil | Est. |
|---|---|---|---|
| 1 | UX-1 — alert() → inline errors | index.html | 30 min |
| 1 | UX-5 — AGENT_DISPLAY_NAMES komplett | index.html | 10 min |
| 1 | UX-6 — queueDelete ångra-pattern | index.html | 20 min |
| 1 | UX-16 — showToast stöder HTML | index.html | 5 min |
| 2 | UX-2 — spec visas inline efter startBuild | index.html | 30 min |
| 2 | UX-3 — attentionBanner döljs i rätt vy | index.html | 10 min |
| 2 | UX-4 — CTA i tom kö | index.html | 10 min |
| 2 | UX-10 — modeHelp-text per läge | index.html | 10 min |
| 3 | UX-7 — historik-sök | index.html | 20 min |
| 3 | UX-12 — health-badge tydligare | index.html | 10 min |
| 3 | UX-14 — Ctrl+Enter hint | index.html | 5 min |
| 3 | UX-19 — badge nollställs korrekt | index.html | 5 min |
| 4 | UX-8 — projekt-sync från server | index.html | 20 min |
| 4 | UX-17 — visa/dölj klar-items | index.html | 15 min |
| 4 | UX-15 — clearBacklog ångra | index.html | 15 min |

---

## RELATION TILL BYGG_TASKS.MD

| UX-task | Hanteras delvis av |
|---|---|
| UX-2 (spec inline) | T7 — ersätt clipboard med builderPanel |
| UX-5 (agent-namn) | T11/T35 — AGENT_DISPLAY_NAMES komplettera |
| UX-7 (paginering) | T23 — sessions-paginering |
| UX-8 (projekt-sync) | T28b — projektprofiler backend |
| UX-13 (switchView) | T2 — switchView builder-active |

UX-1, UX-3, UX-4, UX-6, UX-10, UX-12, UX-14–19 är INTE täckta av befintliga tasks och bör läggas till som nya tasks om de ska byggas separat.

---

**PRINCIPREGEL:** Systemet pushar ALDRIG automatiskt till git. Push är alltid en manuell användaråtgärd.
