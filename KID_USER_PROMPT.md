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