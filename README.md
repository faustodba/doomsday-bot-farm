# 🤖 Doomsday Bot V5
Bot Python per l'automazione della raccolta risorse nel gioco **Doomsday: Last Survivors** su emulatori Android.

---
## ⚠️ Disclaimer
Questo progetto nasce come **studio personale** sulle tecnologie di automazione (Python, ADB, OCR con Tesseract, computer vision con OpenCV) applicato a un contesto di gioco.
- **Nessun fine di lucro** — **Solo uso personale** — **Fair use** su istanze emulate di proprietà dell'utente — **Nessuna garanzia**

---
## 📦 Dipendenze Python
```
pip install pillow opencv-python pytesseract numpy
```
Nessuna dipendenza aggiuntiva — `scipy` non è richiesto.

---
## ✅ Versione v5.20 (zaino settimanale + fix banner/stato)

### Zaino/Backpack unloader (`zaino.py` — nuovo)
- Nuovo task settimanale (ogni 168h) — scarica risorse dallo zaino quando sotto soglia
- Target: `soglia × ZAINO_MOLTIPLICATORE` (default 2×)
- Strategia: pezzature piccole prima; `MAX` se pezzatura ≤ gap residuo; pack misti ignorati
- Gestisce più risorse in sequenza nello stesso ciclo (acciaio, petrolio, legno, pomodoro)
- Configurabile: `ZAINO_ABILITATO`, `ZAINO_MOLTIPLICATORE`, `SCHEDULE_ORE_ZAINO`

### Fix anti-banner (`stato.py`)
- `assicura_home()`: invia sempre BACK preventivi prima di rilevare lo stato
  — i banner fullscreen venivano classificati erroneamente come "home"
- `vai_in_home()`: aggiunto re-check finale dopo N conferme consecutive
  — evita false conferme durante transizioni mappa→home

### Fix caricamento gioco (`emulatore_base.py`)
- Dopo le 3 conferme popup: sequenza di 5 BACK + verifica stato reale
  prima di dichiarare "Gioco pronto!" — un singolo BACK non era sufficiente
  a chiudere tutti i banner che si aprono all'avvio
- Aggiunto traceback completo nel log errore raccolta

### Fix VIP daily (`daily_tasks.py`)
- BACK nel `finally` prima del ritorno in home (garantisce stato pulito)
- Riconoscimento CLAIM free tramite pallino rosso invece di template matching
  — rimuove dipendenza da `btn_claim_free_it.png` (mai creato)

### Fix rifornimento (`rifornimento.py`)
- Fix calcolo `eta_sec`, flag `quota_esaurita`, visualizzazione `-0.0M`

---
## ✅ Versione v5.19 (task periodici + architettura consolidata)

### Radar Show (`radar_show.py` — nuovo)
- Nuovo task periodico schedulato ogni **12h**
- Apre Radar Station dalla home, raccoglie tutte le ricompense (pallini rossi)
- Riconoscimento pallini via **connected components numpy puro** — no scipy
- Filtro forma circolare: compattezza > 0.55, aspect ratio > 0.5, dimensione 8-22px
- Verifica badge rosso sull'icona prima di aprire — skip immediato se assente
- Delay 10s post-apertura per notifiche che scorrono
- Calibrato su dataset 9 screen reali

### VIP Daily Rewards (`daily_tasks.py`)
- Macchina a **2 stati**: cassaforte (coordinate fisse) + CLAIM free (template matching)
- Template lingua-dipendente risolto da `coords.btn_claim_free_template`
- ⚠️ `templates/btn_claim_free_it.png` mancante (BlueStacks IT)

### Contatore squadre in HOME (`raccolta.py`)
- Letto prima di `vai_in_mappa` — **early exit se slot pieni** senza entrare in mappa
- Risparmio ~15-20s per istanza con slot pieni

### Soglie rifornimento separate (`rifornimento.py`, `config.py`)
- 4 soglie indipendenti: campo 5M / legno 5M / petrolio 2.5M / acciaio 3.5M
- Acciaio abilitato all'invio (era escluso)
- Configurabili dalla dashboard senza riavvio

### Fascia oraria per istanza (`runtime.py`, `dashboard.html`)
- Campo `fascia_oraria: "HH:MM-HH:MM"` per istanza negli overrides
- `start < end` → fascia diurna | `start > end` → fascia notturna (span mezzanotte)
- Assente o vuoto → H24 (default)
- Dashboard: 2 time picker con checkbox on/off

### Produzione oraria con tempo reale (`status.py`)
- Calcolo M/h basato su delta timestamp ISO tra cicli consecutivi
- Non più diviso per durata ciclo — misura il tempo reale tra le letture OCR
- Storico cicli con `ts_iso` per gestire gap da interruzioni bot

### Dashboard aggiornata
- Label task in inglese: Alliance Gifts / Alliance Messages / VIP Daily Rewards / Radar Show / Supply Resources
- Layout 2 colonne sezione parametri globali
- Refresh 10s (era 3s)
- Colonna Fascia oraria con time picker

### Allocation ratio aggiornato
- Default: campo 35% / segheria 35% / petrolio 18.75% / acciaio 11.25% (era 6.25%)
- Configurabile dalla dashboard senza riavvio

---
## ✅ Versione v5.18 (selezione livello nodo + produzione oraria dashboard)
- Livello nodo configurabile per istanza (5/6/7), modificabile dalla dashboard
- OCR risorse: retry con backoff crescente 2s→3s→4s
- Dashboard: colonna Lv., pannello produzione oraria M/h

---
## ✅ Versione v5.17 (fix raccolta + robustezza)
- BUG1/BUG3/BUG4 raccolta, contatore reale, OCR retry, log rotation

---
## 🏗️ Architettura

### Flusso coordinate UI
```
config.py (costanti) → coords.py (UICoords.da_ist) → moduli operativi
```
Tutti i moduli ricevono `coords: UICoords` — nessuno legge `config.*` direttamente per le coordinate.

### Flusso configurazione runtime
```
config.py (default) → runtime.json (overrides) → runtime.applica() → config.* in memoria
```
Ogni ciclo rilegge `runtime.json` — modifiche dalla dashboard effettive al ciclo successivo.

### Flusso task periodici
```
scheduler.deve_eseguire() → modulo.esegui_*() → scheduler.registra_esecuzione()
```
Stato persistito in `istanza_stato_{nome}_{porta}.json` per istanza.

### File principali
| File | Ruolo |
|---|---|
| `main.py` | Loop principale, pool semaforo, selezione emulatore |
| `config.py` | Tutte le costanti e coordinate UI |
| `coords.py` | `UICoords` — coordinate risolte per istanza |
| `runtime.py` | Overrides runtime, fascia oraria, istanze attive |
| `raccolta.py` | Logica raccolta risorse, blacklist nodi, allocation |
| `allocation.py` | Algoritmo gap per sequenza ottimale nodi |
| `zaino.py` | Scarico settimanale backpack |
| `daily_tasks.py` | Task periodici: VIP, Radar Show, Zaino |
| `radar_show.py` | Radar Station — riconoscimento pallini con numpy |
| `status.py` | Scrittura status.json per dashboard |
| `scheduler.py` | Schedulazione task per istanza |
| `alleanza.py` | Raccolta doni alleanza |
| `rifornimento.py` | Invio risorse all'alleanza |

### Note repository
- File JSON runtime/stato **non versionati**
- PNG versionati **solo** in `templates/`
- Log, debug, output runtime esclusi via `.gitignore`

---
## 📄 Licenza
MIT License
