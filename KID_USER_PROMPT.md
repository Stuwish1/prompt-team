# Prompt Team — Designguide & Taskboard för 10-årig användare

> **Syfte:** Den primära användaren är ett barn på 10 år. Alla byggbeslut testas mot:
> **"Kan ett 10-åigt barn förstå och använda detta utan hjälp?"**
>
> Varje agent som bygger något i projektet ska läsa den här filen **innan** de börjar.

---

## Vem är användaren?

| Egenskap | Beskrivning |
|---|---|
| Ålder | 10 år |
| Teknisk nivå | Vet vad en app är. Spelar spel. Har ALDRIG hört "git", "commit", "backlog", "spec" eller "endpoint" |
| Motivation | Vill bygga coola grejer — spel, appar, verktyg — utan att lära sig programmering |
| Tålamod | Lågt. Förvirring = bortklickat |
| Förväntan | Säg vad du vill → systemet fixar det → klart |

---

## Ordlista — tekniska termer förbjudna i barnvy

| Förbjudet i UI | Ersättning |
|---|---|
| `IT-teamet` / `teamet` | "Jag" (systemet talar i förstaperson) |
| `beställning` / `spec` | "Byggplan" / "Din plan" |
| `backlog` / `fynd` | "Din idélista" / "Saker att fixa" |
| `kö` / `byggs` / `klar` | "Väntar", "Bygger ⏳", "Klart ✅" |
| `behover_dig` | "Behöver din hjälp 🙋" |
| `Kravanalys` / `Kravanalytikern` | "Förstår din idé" |
| `Specialistgranskning` | "Kontrollerar allt" |
| `Specifikation` / `Promptsmeden` | "Skriver din plan" |
| `P0` / `P1` / `P2` | 🔴 Kritisk / 🟡 Viktig / 🟢 Senare |
| `GODKÄND` / `UNDERKÄND` | Visa aldrig |
| `Beställarläge` / `Teknisk läge` | "Enkel vy" / "Avancerad vy" |
| `Verifiera fix` / `Fixverifieraren` | "Kontrollera att det är fixat" |
| `commit` / `git push` | Visa aldrig |
| `stacktrace` / `serverlogg` | "Felmeddelande" |
| `token` / `kostnad` | Visa aldrig |
| `byggsätt` | Visa aldrig för barnet |
| `fas N/M` | "Del N av M" |
| `försök N` | Visa aldrig |
| `Snabbläge` / `Djupläge` | "Snabb kontroll ⚡" / "Noggrann kontroll 🔍" |
| `kvarstående problem` | "saker som inte stämmer" |
| `Specifikationen` | "Din plan" |

---

## TASKBOARD — prioriterade uppgifter för byggaren

**P0 = akut · P1 = viktigt · P2 = bra att ha · P3 = framtid**

---

### 🔴 P0 — Kritiska tasks

---

#### TASK-01 · Lägg till `KID_MODE`-flagg i systemet

**Fil:** `settings.json` + `app.py` + `index.html`

**Bakgrund:**
Fundamentet som alla andra tasks bygger på. Utan det riskerar varje ny feature-push
att läcka teknisk text in i barnvyn.

**Vad ska byggas:**
1. Lägg till `"kid_mode": true` i `settings.json`
2. `app.py → load_settings()`: exponera via `GET /api/settings`
3. `index.html`: läs `kid_mode` vid startup:
   ```javascript
   const kidMode = (await fetch('/api/settings').then(r=>r.json())).kid_mode ?? true;
   document.body.classList.toggle('kid-mode', kidMode);
   ```
4. Globalt CSS-skydd:
   ```css
   body.kid-mode .admin-only { display: none !important; }
   ```

**Godkänt när:** `kid_mode: true` döljer allt `.admin-only` utan att bryta övrig funktion.

---

#### TASK-02 · Fixa `.gitignore` — återställ `intrim_result*.json`

**Fil:** `.gitignore`

**Bakgrund:**
Lokal ändring tog bort `intrim_result*.json` ur `.gitignore`.
`intrim_result.json` och `intrim_result_concrete.json` är otrackade lokalt
och riskerar att committas med råa API-svar.

```gitignore
# Lägg tillbaka:
intrim_result*.json
```

**Godkänt när:** `git status` visar inte `intrim_result*.json` som untracked/staged.

---

#### TASK-03 · Fixa välkomstskärmen — första sidan barnet ser

**Fil:** `index.html` → `#emptyState` (rad ~876)

**Bakgrund:**
Välkomstskärmen är det allra första barnet ser. Just nu visar den:
- `"🏢 IT-teamet väntar på din beställning"` — ingen 10-åring vet vad "IT-teamet" eller "beställning" är
- Brödtext med: "teamet analyserar krav, granskar parallellt och levererar en komplett specifikation redo att skicka till Lovable, Claude eller Cursor"
- Förklaring: `"Fas 1 → Kravanalys · Fas 2 → Specialistgranskning · Fas 3 → Specifikation"` — teknisk jargong

**Vad ska göras:**
```html
<!-- FÖRE -->
<div class="empty-icon">🏢</div>
<div class="empty-title">IT-teamet väntar på din beställning</div>
<div class="empty-sub">Beskriv din idé — teamet analyserar krav...
  <span>Fas 1 → Kravanalys · Fas 2 → Specialistgranskning · Fas 3 → Specifikation</span>
</div>

<!-- EFTER -->
<div class="empty-icon">🚀</div>
<div class="empty-title">Vad vill du bygga idag?</div>
<div class="empty-sub">
  Berätta din idé — så sköter jag resten!
  <br><br>
  <span style="font-size:11px;color:var(--text3);">
    Jag förstår idén · Kontrollerar allt · Skriver en plan åt dig
  </span>
</div>
```

**Godkänt när:** Välkomstskärmen innehåller inga tekniska termer.

---

#### TASK-04 · Ta bort "Specen kopieras — klistra in i din byggare"

**Fil:** `index.html` rad ~1884 + rad ~1963

**Bakgrund:**
Texten och toasten existerar på **2 ställen** i origin/main (bekräftat).

**Vad ska göras:**
```javascript
// RAD ~1884 — kö-kortets action-block:
// FÖRE:
`<button ...>▶ Bygg nästa</button>
 <span>Specen kopieras — klistra in i din byggare</span>`
// EFTER:
`<button ...>▶ Bygg det här!</button>`

// RAD ~1963 — startBuild() toast:
// FÖRE:
showToast('📋 Spec kopierad — klistra in i din byggare. Kom tillbaka med resultatet!', 4500);
// EFTER:
showToast('✅ Bygget är igång! Jag meddelar dig när det är klart.', 4000);
```

**Godkänt när:** Orden "klistra in" och "byggare" syns inte i byggkö-flödet.

---

#### TASK-05 · Dölj inställningspanelen i barnläge (kräver TASK-01)

**Fil:** `index.html` → settings-knappen + `#settingsModal`

```html
<button class="btn btn-ghost admin-only" onclick="openSettings()">Inställningar ...</button>
```
Ge `#settingsModal`-diven klassen `admin-only`.

**Godkänt när:** Ingen inställningsknapp syns i barnläge.

---

#### TASK-06 · Ersätt statuskoderna i byggkön med barnvänliga texter

**Fil:** `index.html` → `_Q_STATUS_LABEL` (rad ~1857)

```javascript
const _Q_STATUS_LABEL_KID = {
  'kö':          '🕐 Väntar på sin tur',
  'byggs':       '⏳ Bygger just nu...',
  'behover_dig': '🙋 Behöver din hjälp',
  'klar':        '✅ Klart!'
};
const _Q_STATUS_LABEL = kidMode ? _Q_STATUS_LABEL_KID
  : { 'kö': 'I kö', 'byggs': 'Byggs', 'behover_dig': 'Behöver dig', 'klar': 'Klar' };
```

**Godkänt när:** Barnvy visar aldrig "I kö", "Byggs", "Behöver dig", "Klar".

---

### 🟠 P1 — Viktiga tasks

---

#### TASK-07 · Lägg tillbaka barnvänlig text under läge-knapparna (REGRESSION)

**Fil:** `index.html` → efter `.mode-btns` + `setMode()` (rad ~1230)

**Bakgrund:**
Senaste push tog bort `#modeHelp`-diven och `_MODE_HELP`-objektet. Nu finns
ingen förklaring av vad varje läge gör. Barnet klickar blind.

```html
<!-- Lägg till efter .mode-btns-blocket -->
<div id="modeHelp" style="font-size:13px;color:var(--text2);margin-top:10px;line-height:1.6;
  padding:8px 12px;background:var(--bg3);border-radius:var(--r-md);"></div>
```

```javascript
const _MODE_HELP_KID = {
  ny_funktion: '💡 Berätta vad du vill bygga — jag förstår din idé och skriver en plan!',
  granska_kod: '🔍 Jag läser igenom din kod och berättar vad som kan bli bättre.',
  buggrapport: '🐛 Beskriv vad som gick fel — jag hittar problemet och skriver en fix.',
};
// I setMode(): document.getElementById('modeHelp').textContent = _MODE_HELP_KID[mode] || '';
```

**Godkänt när:** En barnvänlig mening visas under läge-knapparna vid varje val.

---

#### TASK-08 · Byt läge-knappars texter och undertitlar

**Fil:** `index.html` → `.mode-btn` (rad ~745)

```html
<!-- FÖRE -->
💡 Ny funktion<br><small>Idé → färdig spec</small>
🔍 Granska kod<br><small>Kod → backlog</small>
🐛 Buggrapport<br><small>Fel → fix-spec</small>

<!-- EFTER -->
💡 Bygg något nytt<br><small style="font-weight:400;font-size:11px">Berätta vad du vill ha</small>
🔍 Kolla min kod<br><small style="font-weight:400;font-size:11px">Låt mig hitta problem</small>
🐛 Något är trasigt<br><small style="font-weight:400;font-size:11px">Hjälp mig fixa felet</small>
```

**Godkänt när:** Orden "spec", "backlog", "fix-spec" syns inte på läge-knapparna.

---

#### TASK-36 · Byt run-knappens text "Skicka till teamet"

**Fil:** `index.html` → `#runBtn` (rad ~865) + `depth-btn`-knapparna (rad ~862)

**Bakgrund:**
Huvud-knappen är det barnet klickar på för att starta. Den säger:
`"▶ Skicka till teamet"` — "teamet" är ett internt kodnamn barnet aldrig hört.
Depth-knapparna bredvid har tooltips: `"7 kärnagenter — snabb iteration (~25s)"` och
`"Hela teamet — gedigen leverans (~60s)"` — synliga vid hover.

**Vad ska göras:**
```html
<!-- FÖRE -->
<button class="depth-btn" title="7 kärnagenter — snabb iteration (~25s)">⚡ Snabbläge</button>
<button class="depth-btn active" title="Hela teamet — gedigen leverans (~60s)">🏢 Djupläge</button>
<button class="btn btn-primary" id="runBtn">▶ Skicka till teamet</button>

<!-- EFTER -->
<button class="depth-btn" title="Snabbare (~25s)">⚡ Snabb kontroll</button>
<button class="depth-btn active" title="Noggrannare (~60s)">🔍 Noggrann kontroll</button>
<button class="btn btn-primary" id="runBtn">▶ Kör!</button>
```

I `runReview()` när mode = `ny_funktion`:
```javascript
// Knapp-text anpassas per läge:
const _RUN_LABEL = {
  ny_funktion:  '▶ Förstå min idé!',
  granska_kod:  '▶ Kolla koden!',
  buggrapport:  '▶ Hitta felet!',
};
document.getElementById('runBtn').textContent = _RUN_LABEL[currentMode] || '▶ Kör!';
```

**Godkänt när:** Knappen säger aldrig "teamet". Tooltips innehåller ingen agent-jargong.

---

#### TASK-37 · Byt kravBox-titel "📋 Kravanalytikern"

**Fil:** `index.html` → `renderKravBox()` (rad ~2315)

**Bakgrund:**
Resultatvyns första block visar alltid `"📋 Kravanalytikern"` som rubrik.
Barnet har aldrig hört termen "Kravanalytikern".

```javascript
// FÖRE:
`<div class="krav-title">📋 Kravanalytikern</div>`

// EFTER:
`<div class="krav-title">📋 ${kidMode ? 'Jag förstår din idé så här:' : 'Kravanalytikern'}</div>`
```

**Godkänt när:** Barnvy visar "Jag förstår din idé så här:" — inte "Kravanalytikern".

---

#### TASK-09 · Dölj "Extra kontext"-fält i barnläge (REGRESSION)

**Fil:** `index.html` → `#preContextInput`-blocket + `#postContextInput`-blocket

**Bakgrund:**
Senaste push tog bort accordion-strukturen — "Extra kontext" syns nu alltid med
teknisk placeholder: `"T.ex: Det här gäller specifikt checkout-flödet. Befintlig auth finns i /lib/auth.ts..."`

```html
<!-- Lindra båda blocken i admin-only -->
<div class="admin-only">
  <div class="section-label">Extra kontext ...</div>
  <textarea id="preContextInput" ...></textarea>
</div>
```

**Godkänt när:** Barnvy ser inte "Extra kontext" med tekniska placeholders.

---

#### TASK-10 · Byt fasrubriker i resultatvyn

**Fil:** `index.html` → `phase-label`-spannarna (rad ~908, ~917, ~927)

**Bakgrund:**
Resultatvyn har tre synliga fasrubriker med teknisk jargong.

```html
<!-- FÖRE -->
<span class="phase-label">Fas 1 — Kravanalys</span>
<span class="phase-label">Fas 2 — Specialistgranskning</span>
<span class="phase-label">Fas 3 — Specifikation</span>

<!-- EFTER (barn-mode) -->
<span class="phase-label">Del 1 — Jag förstår din idé</span>
<span class="phase-label">Del 2 — Jag kontrollerar allt</span>
<span class="phase-label">Del 3 — Din byggplan</span>
```

Implementera med `kidMode`-ternär eller `data-kid`-attribut + CSS `content`.

**Godkänt när:** Barnvy ser aldrig "Kravanalys", "Specialistgranskning", "Specifikation".

---

#### TASK-11 · Fixa laddningsskärmens text + dynamisk agentsiffra

**Fil:** `index.html` → `#loadingPhases` (rad ~905) + `startProgressPolling()`

```html
<!-- EFTER -->
<span>Jag läser och förstår din idé...</span>
<span id="lp2text">Jag kontrollerar allt noga...</span>
<span>Jag skriver din byggplan...</span>
```

`lp2text` uppdateras dynamiskt: `"${done} av ${total} kontroller klara"` — aldrig hårdkodat antal.

**Godkänt när:** Inga agentnamn syns. Siffran är dynamisk och stämmer.

---

#### TASK-12 · Byt "Beställarläge"/"Teknisk läge"-toggle i barnläge

**Fil:** `index.html` → `#viewToggle` (rad ~929)

**Bakgrund:**
Fas 3-headern visar: `"🧑‍💼 Beställarläge"` / `"👩‍💻 Teknisk läge"`. "Beställarläge" är
okänd term för ett barn. Dessutom bör "Teknisk läge" döljas i barnläge.

```html
<!-- EFTER -->
<button class="view-btn active" id="vt-bestallare" onclick="setSpecView('bestallare')">
  📋 Enkel vy
</button>
<button class="view-btn admin-only" id="vt-teknisk" onclick="setSpecView('teknisk')">
  👩‍💻 Teknisk vy
</button>
```

**Godkänt när:** Barnvy ser bara "Enkel vy". "Teknisk vy" döljs.

---

#### TASK-13 · Lägg till barnvänlig varning vid trasigt projekt (ersätter grön-gate)

**Fil:** `index.html` → `startBuild()` (rad ~1951)

**Bakgrund:**
Backend tog bort grön-gate i senaste push — ingen blockering sker längre.
Barnet kan omedvetet bygga vidare ovanpå ett trasigt projekt.

```javascript
async function startBuild(id, btn) {
  if (kidMode) {
    const brokenItem = allQueueItems.find(i =>
      i.project_id === currentProjectId &&
      i.status === 'behover_dig' &&
      i.id !== id
    );
    if (brokenItem) {
      // Visa inline-varning — aldrig confirm()
      showInlineWarning(
        `⚠️ '${brokenItem.title}' behöver fixas! Vill du ändå bygga vidare?`,
        () => _doStartBuild(id, btn)
      );
      return;
    }
  }
  _doStartBuild(id, btn);
}
```

**Godkänt när:** Barnvy får tydlig, ej-teknisk varning om ett projekt är trasigt.

---

#### TASK-14 · Fixa historikvyn — dölj råa lägesnamn

**Fil:** `index.html` → `loadHistory()` (rad ~3030) + `.history-mode` CSS

**Bakgrund:**
Historiklistan visar `s.mode` med `text-transform: uppercase` →
barnet ser `"NY_FUNKTION"`, `"GRANSKA_KOD"`, `"BUGGRAPPORT"`.

```javascript
// I sessions.map() i loadHistory():
const _MODE_LABEL_KID = {
  ny_funktion:  '💡 Nytt',
  granska_kod:  '🔍 Granskning',
  buggrapport:  '🐛 Bugg',
};
// Byt:
`<span class="history-mode">${escHtml(s.mode)}</span>`
// Till:
`<span class="history-mode">${_MODE_LABEL_KID[s.mode] || escHtml(s.mode)}</span>`
```

Ta bort `text-transform: uppercase` från `.history-mode` i CSS.

**Godkänt när:** Historiken visar aldrig "NY_FUNKTION" etc.

---

#### TASK-15 · Dölj `push_to_github.bat`-bannern i barnläge

**Fil:** `index.html` → `#mainNoRepoBanner` (rad ~725) + rad ~1015

**Bakgrund:**
Bannern visar: `"Kör push_to_github.bat"` med inline `<code>`-element.
Rad ~1015 i projektmodalen: `"Fylls i automatiskt av push_to_github.bat"`.

```html
<!-- FÖRE -->
🔗 Main har inget GitHub-repo kopplat. Kör <code>push_to_github.bat</code> ...

<!-- EFTER barnläge -->
🔗 Projektet är inte kopplat till GitHub. Be en vuxen hjälpa dig.
```

Ge rad ~1015-texten klassen `admin-only`.

**Godkänt när:** Barnvy ser aldrig filnamnet `push_to_github.bat`.

---

#### TASK-16 · Dölj agentkortet GODKÄND/UNDERKÄND i barnläge (kräver TASK-01)

**Fil:** `index.html` → `#agentsGrid` + `#reviewStat`

```html
<div class="agents-grid admin-only" id="agentsGrid"></div>
<span class="phase-stat admin-only" id="reviewStat"></span>
```

Bygg `renderKidSummary()` som visar en enkel barnsammanfattning istället.

**Godkänt när:** Barnvy ser aldrig agentkort, badges eller kostnadssiffra.

---

#### TASK-17 · Ersätt alert()/confirm() med inline-bekräftelser

**Fil:** `index.html` → alla `alert()` och `confirm()`

**Identifierade ställen:**
- `alert('Beskriv felet och/eller klistra in koden.')` — rad ~1575
- `confirm(...)` — ta bort fynd, rensa alla fynd
- `"Markera klar ändå"` → ge klassen `admin-only`

Ersätt med inline-meddelanden direkt under respektive fält/knapp.

**Godkänt när:** Inga `alert()` / `confirm()` anropas i barnvy.

---

#### TASK-18 · Dölj "Byggsätt"-fliken i projektmodalen

**Fil:** `index.html` → `#tab-byggsatt` + knappen

```html
<button class="modal-tab admin-only" onclick="switchProjTab('byggsatt')">🛠️ Byggsätt</button>
<div class="tab-pane admin-only" id="tab-byggsatt">...</div>
```

**Godkänt när:** Barnvy ser bara "🔗 Anslutning" och "📋 Projektprofil".

---

#### TASK-19 · Dölj "🔬 Agentgranskning"-knappen

**Fil:** `index.html` → rad ~934

```html
<button class="btn btn-ghost admin-only" onclick="exportAgentAudit()">🔬 Agentgranskning</button>
```

---

#### TASK-20 · Fixa buggrapport-fältets etikett

**Fil:** `index.html` → `#bugLogsInput` label

```html
<!-- EFTER -->
<div class="section-label">📋 Ser du ett rött felmeddelande?
  <span style="font-weight:400">(valfritt)</span></div>
<textarea placeholder="Klistra in det röda felmeddelandet, om du har ett..."></textarea>
```

Orden "stacktrace", "serverlogg", "rotorsaksanalysen" försvinner.

---

#### TASK-21 · Fixa attention-bannern

**Fil:** `index.html` → `updateAttentionBanner()`

```javascript
attentionText.textContent = kidMode
  ? `🙋 '${redItem?.title || 'Ett projekt'}' behöver din hjälp!`
  : `⚠ ${needs} bygge${needs>1?'n':''} väntar på din kontroll`;
```

---

#### TASK-22 · Byt "HEMLIGHET HITTAD"-texten

**Fil:** `app.py` → hemlighetsvakten (lokal, ej pushad)

```python
# EFTER:
secret_titles = ["⚠️ Koden innehåller något känsligt — be en vuxen titta på det"]
```

---

#### TASK-23 · Dölj Supabase-schema-bannern tekniska text

**Fil:** `index.html` → schema-drift-banner

```javascript
banner.innerHTML = schemaBehind
  ? (kidMode
      ? `⚠️ Systemet behöver en uppdatering. Be en vuxen hjälpa dig.`
      : `⚠️ Supabase-schemat ligger efter — kör supabase_setup.sql i SQL Editor.`)
  : `...`;
```

---

### 🟡 P2 — Bra att ha

---

#### TASK-40 · Ge "Byggresultat"-modalen admin-only i barnläge

**Fil:** `index.html` → `#buildResultModal` (rad ~975)

**Bakgrund:**
Modalen "📦 Byggresultat" visas när barnet klickat "▶ Bygg det här!" och ska granska resultatet.
Den kräver att barnet klistrar in kod manuellt med texten:
`"Den byggda koden (teamet granskar + verifierar mot specen automatiskt)"` och
`"Klistra in koden som byggaren producerade..."`.
Det här är direkt kopplat till det manuella copy-paste-flödet som TASK-04 ersätter med chatbox.
Tills chatbox är klar: dölja modalen i barnläge, eller ersätt med ett "Väntar på byggaren..."-meddelande.

**Vad ska göras (tillfällig lösning tills TASK-04 är klar):**
```javascript
// I startBuild(): i barnläge, visa INTE buildResultModal
// Visa istället ett enkelt vänte-meddelande i kö-kortet
if (kidMode) {
  showToast('⏳ Bygget är skickat! Jag meddelar dig när det är klart.', 5000);
  return;
}
// Admin-flöde: öppna buildResultModal som vanligt
openBuildResult(id);
```

**Långsiktig lösning:** Hela detta flöde ersätts av chatbox-integrationen (AGENT_CHATBOX_BUILD.md).

**Godkänt när:** Barnvy ser aldrig "teamet granskar", "mot specen", "byggaren producerade".

---

#### TASK-41 · Ge Projektprofil-flikens tekniska fält `admin-only`

**Fil:** `index.html` → `#tab-profile` (rad ~1095)

**Bakgrund:**
Projektprofil-fliken innehåller fält som ett barn aldrig kan fylla i:
- "Teknikstack" (React, TypeScript...)
- "Arkitektur" (Server components, Monorepo...)
- "Kodkonventioner" (camelCase, snake_case...)
- "Constraints" (Får ej byta databas...)

**Vad ska göras:**
```html
<!-- Ge hela fliken admin-only -->
<button class="modal-tab admin-only" onclick="switchProjTab('profile')">📋 Projektprofil</button>
<div class="tab-pane admin-only" id="tab-profile">...</div>
```

Alternativt: behåll bara "Projektets syfte"-fältet synligt för barn (det kan ett barn faktiskt fylla i).

**Godkänt när:** Barnvy ser inte Teknikstack, Arkitektur, Kodkonventioner eller Constraints.

---

#### TASK-38 · Byt completenessBox-texterna

**Fil:** `index.html` → `renderCompletenessBox()` (rad ~2337)

**Bakgrund:**
Kompletthetsrutan visar `"✅ Specifikationen är komplett"` eller `"⚠️ Specifikationen kan förbättras"`.
"Specifikationen" är teknisk term. Rutan visar även ett poäng `7/10` utan förklaring.

```javascript
// FÖRE:
isComplete ? '✅ Specifikationen är komplett' : '⚠️ Specifikationen kan förbättras'

// EFTER (kid-mode):
isComplete ? '✅ Din plan är redo att byggas!' : '⚠️ Din plan kan bli ännu bättre'
```

Poänget `7/10` bör kompletteras med en förklaring i barnläge:
```javascript
`<div class="completeness-score">${score}<span>/10</span></div>`
// Lägg till under poänget:
kidMode ? `<div style="font-size:11px;color:var(--text3);">hur komplett din plan är</div>` : ''
```

**Godkänt när:** Barnvy ser aldrig "Specifikationen". Poänget har en förklaring.

---

#### TASK-39 · Rensa tekniska toast-meddelanden

**Fil:** `index.html` → alla `showToast()`-anrop med teknisk text

**Bakgrund:**
Systemet har 20+ toast-meddelanden. Dessa är tekniska och visas direkt för barnet:

| Rad | Nuvarande text | Barnvänlig ersättning |
|---|---|---|
| ~1986 | `"Klistra in den byggda koden först."` | `"Klistra in koden du fick från byggaren."` |
| ~1999 | `"Bygget godkänt och verifierat — nästa i kön är redo!"` | `"✅ Bra jobbat! Nästa projekt kan börja."` |
| ~2002 | `"Granskningen hittade ${n} kvarstående problem — se kortet."` | `"⚠️ Jag hittade ${n} saker att fixa — se kortet."` |
| ~2058 | `"Ingen spec att köa."` | `"Välj en plan att bygga först."` |
| ~2074 | `"Lagd i byggkön — öppna Att bygga för att bygga den"` | `"✅ Tillagd! Öppna 'Att bygga' för att starta."` |
| ~2205 | `"Promptsmeden behöver mer info — formulera om fyndet eller kör djupläge."` | `"Jag behöver mer info — beskriv problemet lite mer detaljerat."` |
| ~2668 | `"⬇ Exporterad som Markdown"` | `"⬇ Filen är nedladdad!"` |
| multipla | `"❌ " + e.message` (råa JS-fel) | `"❌ Något gick fel. Försök igen."` (barn) / full text (admin) |

**Vad ska göras:**
Skapa en hjälpfunktion:
```javascript
function kidToast(kidMsg, adminMsg, duration) {
  showToast(kidMode ? kidMsg : (adminMsg || kidMsg), duration);
}
```
Byt ut berörda `showToast()`-anrop till `kidToast()`.

**Godkänt när:** Barnvy ser aldrig "spec", "köa", "kön", "Promptsmeden", "Markdown" i toast-meddelanden.

---

#### TASK-42 · Fixa "Kvarstående:"-texten i kö-korten

**Fil:** `index.html` → `renderQueueBox()` (rad ~1892)

**Bakgrund:**
När ett bygge är underkänt visar kö-kortet direkt:
`"<b>Kvarstående:</b>"` följt av bullet-punkter.
"Kvarstående" är ett ovanligt ord för ett 10-årigt barn.

```javascript
// FÖRE:
`<div class="qc-verdict"><b>Kvarstående:</b>${...}</div>`

// EFTER:
`<div class="qc-verdict"><b>${kidMode ? '⚠️ Behöver fixas:' : 'Kvarstående:'}</b>${...}</div>`
```

**Godkänt när:** Barnvy visar "Behöver fixas:" i stället för "Kvarstående:".

---

#### TASK-43 · Fixa GitHub-sektionens labels i barnläge

**Fil:** `index.html` → `#githubSection` (rad ~785)

**Bakgrund:**
GitHub-sektionen (synlig i "Kolla min kod"- och "Buggrapport"-lägena) visar:
- Tooltip: `"Hämta koden nu för att se exakt vad teamet kommer granska"` — "teamet"
- "Gren:" label — teknisk term
- `"Lämna tomt för att klistra in kod manuellt"` — oklart för barn
- "Kod att granska" — OK men kan förbättras

```javascript
// GitHub-sektion tooltip (kid-mode):
fetchBtn.title = kidMode
  ? 'Hämta den senaste koden'
  : 'Hämta koden nu för att se exakt vad teamet kommer granska';

// "Gren:"-label (kid-mode):
kidMode ? 'Version:' : 'Gren:'

// "Lämna tomt..."-status:
kidMode
  ? 'Klistra in koden om du vill — annars hämtar jag den från GitHub'
  : 'Lämna tomt för att klistra in kod manuellt'
```

**Godkänt när:** Barnvy ser inte "teamet", "Gren" (som git-term) i GitHub-sektionen.

---

#### TASK-24 · Byt P0/P1/P2-etiketter i backlog-vyn

**Fil:** `index.html` → `renderBacklogBox()` (rad ~2115)

**Bakgrund:**
Varje backlog-item visar `"P0 · Kritisk"`, `"P1 · Viktig"`, `"P2 · Senare"` som badge.
P0/P1/P2 ska aldrig visas för barnet.

```javascript
// FÖRE:
const _PRIO_LABEL = { P0: 'Kritisk', P1: 'Viktig', P2: 'Senare' };
`<span class="bl-prio ${pc}">${it.priority} · ${_PRIO_LABEL[it.priority]||''}</span>`

// EFTER (kid-mode):
const _PRIO_KID = { P0: '🔴 Måste fixas', P1: '🟡 Bör fixas', P2: '🟢 Kan vänta' };
`<span class="bl-prio ${pc}">${kidMode ? (_PRIO_KID[it.priority]||'') : it.priority + ' · ' + (_PRIO_LABEL[it.priority]||'')}</span>`
```

**Godkänt när:** Barnvy ser aldrig "P0", "P1", "P2".

---

#### TASK-25 · Byt backlog-åtgärdsknapparna

**Fil:** `index.html` → `renderBacklogBox()` → åtgärderna per item

```html
<!-- FÖRE -->
→ Gör till spec & köa
🔍 Verifiera fix

<!-- EFTER -->
▶ Bygg det här
✅ Kontrollera att det är fixat
```

Status-selectorn: byt `"återkommit"` → `"kom tillbaka"`.

---

#### TASK-26 · Fixa tomma-lägen-texterna

**Fil:** `index.html` → tomma-state-meddelanden

```javascript
// Kön: "Kön är tom — lägg en spec i byggkön så hamnar den här."
// → "Inget att bygga än — välj något från din idélista ovan!"

// Backlog: "Inga fynd ännu — kör en granskning i Beställ-vyn."
// → "Inga förbättringar hittade ännu — kör en kontroll i Beställ-vyn!"
```

---

#### TASK-27 · Dölj/förenkla "🛠️ Standard byggsätt"-raden

**Fil:** `index.html` → `#byggsattRow` (rad ~737)

```html
<!-- Ge admin-only klassen -->
<div id="byggsattRow" class="admin-only" onclick="openEditProjectByggsatt()" ...>
  🛠️ Standard byggsätt
</div>
```

---

#### TASK-28 · Fixa förtydligande-frågans intro-text

**Fil:** `index.html` → `renderQuestions()` (rad ~2370)

```javascript
// FÖRE: "✍️ Svara på frågorna så skapar jag rätt prompt:"
// EFTER: "✍️ Svara på frågorna så förstår jag exakt vad du vill ha:"
```

---

#### TASK-29 · Dölj "försök N" och "✍️ v2"-badges i barnläge

**Fil:** `index.html` → `renderQueueBox()`

```javascript
${it.attempt_nr > 1 ? `<span class="admin-only">försök ${it.attempt_nr}</span>` : ''}
${(it.spec_versions||[]).length ? `<span class="admin-only">✍️ v${...}</span>` : ''}
```

---

#### TASK-30 · Fixa lås-texten på blockerade kö-kort

```javascript
// FRÅN: "'X' är underkänd och måste bli grön först"
// TILL:  "🔒 Lös 'X' innan det här kan byggas"
```

---

#### TASK-31 · Dölj kostnads-display i barnläge

**Fil:** `index.html` → `statEl.innerHTML` + toast i `sendSpec()`

```javascript
const costStr = (!kidMode && cost?.total_usd > 0)
  ? ` · 💰 ~$${cost.total_usd.toFixed(3)}` : '';
```

Detsamma för toast-meddelanden med `~$X.XXX`.

---

#### TASK-32 · Visa meddelande när "byggs" återställts vid omstart

Om servern återställde stale "byggs" vid omstart → visa toast:
```javascript
showToast('Jag startade om. Ditt projekt väntar på att byggas igen.');
```

---

#### TASK-33 · Dölj "Markera klar ändå"-knappen i barnläge

```html
<button class="btn btn-ghost admin-only" onclick="queueSetStatus(...)">Markera klar ändå</button>
```

---

### 🔵 P3 — Framtida förbättringar

---

#### TASK-34 · Sida för föräldra-/admininstallation

Separat `/setup`-sida (nås inte från barnvyn) där en vuxen:
- Konfigurerar API-nycklar
- Kopplar GitHub-repo
- Sätter `kid_mode: true/false`

#### TASK-35 · Serverstartsmeddelande i barnvyn

Om inga inställningar finns: visa välkomstsida med `"👋 Hej! Be en vuxen hjälpa dig komma igång."`

---

## Lösta tasks

| Task | Beskrivning | Status |
|---|---|---|
| ~~S1~~ | Stale "byggs" återställs vid serveromstart | ✅ Lokal fix (app.py) |
| ~~S2~~ | Hemlighetsvakten blockerar hårt | ✅ Lokal fix (app.py) |
| ~~S3~~ | Sessionsnamn från tolkad_ide | ✅ Lokal fix (app.py) |
| ~~S4~~ | Säkerhetsagenter alltid i snabbläge | ✅ Lokal fix (app.py) |
| ~~S5~~ | "Vad hör till ärendet?"-steg borttaget | ✅ Push 3654bd7 |
| ~~S6~~ | "📐 Planera ordning"-knapp borttagen | ✅ Push 3654bd7 |

---

## Checklista — vad barnet ska ALDRIG se

- [ ] "IT-teamet" / "beställning" / "spec"
- [ ] "Kravanalys" / "Specialistgranskning" / "Specifikation"
- [ ] GODKÄND / UNDERKÄND / FEL (agentbadges)
- [ ] P0 / P1 / P2
- [ ] Kostnad per API-anrop
- [ ] "Agentgranskning"-export
- [ ] "Specen kopieras — klistra in i din byggare"
- [ ] `push_to_github.bat`
- [ ] alert() / confirm() popups
- [ ] Stacktraces / serverloggar
- [ ] "NY_FUNKTION" / "GRANSKA_KOD" i historiken
- [ ] "Extra kontext" med tekniska placeholders
- [ ] "Beställarläge" / "Teknisk läge"
- [ ] Supabase SQL-banners
- [ ] "Standard byggsätt"-raden
- [ ] "Kön är tom — lägg en spec i byggkön"
- [ ] "Skicka till teamet" (run-knapp)
- [ ] "📋 Kravanalytikern" (kravBox-rubrik)
- [ ] "Specifikationen är komplett/kan förbättras"
- [ ] Toast-meddelanden med "spec", "köa", "Promptsmeden", "Markdown"
- [ ] Råa `❌ e.message`-fel visade direkt för barn
- [ ] "teamet granskar + verifierar mot specen" i Byggresultat-modalen
- [ ] Projektprofil-flikens tekniska fält (Teknikstack, Arkitektur, Kodkonventioner)
- [ ] "Gren:" + "teamet"-tooltip i GitHub-sektionen
- [ ] "Kvarstående:" i kö-korten

---

## Uppdateringslogg

| Datum | Vad gjordes | Av |
|---|---|---|
| 2026-06-10 | Initial genomgång — 10 grundfynd | Claude |
| 2026-06-10 | Granskning feat/agent-audit-export — 8 nya fynd | Claude |
| 2026-06-10 | Djupare iteration index.html — 12 nya fynd | Claude |
| 2026-06-10 | Lokala ocommittade ändringar — 3 nya fynd, 4 lösta | Claude |
| 2026-06-10 | Omstrukturering till 27 sendable builder tasks | Claude |
| 2026-06-10 | Ny push 3654bd7 — 2 regressions, 6 fynd, taskboard uppdaterat | Claude |
| 2026-06-10 | Djup iteration ogranskade delar — 10 nya fynd (välkomstskärm, fasrubriker, historikvy, backlog-etiketter). 35 tasks totalt, omordnat. | Claude |
| 2026-06-10 | Final iteration — 4 nya fynd (run-knapp, kravBox-titel, completenessBox, 20+ tekniska toasts). 39 tasks totalt. | Claude |
| 2026-06-10 | Sista iteration — 4 nya fynd (Byggresultat-modal, Projektprofil tekniska fält, Kvarstående-text, GitHub-sektionens labels). 43 tasks totalt. | Claude |

---

## Pushhistorik — granskade commits

| Commit | Titel | Barnvy-påverkan |
|---|---|---|
| `3654bd7` | feat: rapportkorrekthet | ⚠️ 2 regressions: modeHelp borttaget, Extra kontext alltid synlig |
| `39312fb` | feat: rapportkorrekthet | Mörkt tema (OK). Grön-gate borttaget → TASK-13 |
| `bfe460a` | fix: normalisera Supabase-URL | Neutral |
| `424f847` | feat: Supabase schema-migrationsledger | Banner med SQL-text → TASK-23 |
| `80db5b3` | feat: agentgranskning-export | Teknisk exportknapp → TASK-19 |

---

*Nästa steg: Bygg TASK-01 (KID_MODE) — det låser upp att validera samtliga övriga tasks med ett knapptryck.*
