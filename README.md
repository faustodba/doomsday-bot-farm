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
## 🚧 Versione v5.21 (WIP — sviluppo sospeso, da riprendere)

### Modifiche completate
- Sostituzione globale `assicura_home()` → `vai_in_home()` in tutti i moduli
- VIP CLAIM_FREE: coordinate calibrate `CLAIM_FREE_BADGE_ZONA=(650,270,730,320)`, `TAP_VIP_CLAIM_FREE=(575,380)`
- `rifornimento.py`: `sleep(2.5)` dopo Tap Membri per stabilizzazione UI
- Task VIP e Radar separati in chiamate `_run_guarded()` individuali in `raccolta.py`
- `runtime.py`: aggiunto `RADAR_CENSUS_ABILITATO`

### Radar Census (`radar_census.py` — nuovo modulo)
- Fotografa e pre-classifica icone non-dot-rosso dalla mappa
- Dataset 34 campioni verificati (FAU_00..FAU_05)
- Problema aperto: zombie grandi non separabili da avatar con sole feature RGB
- Prossimo step: Random Forest (scikit-learn) + feature spaziali

### ⚠️ Pending alla ripresa
1. `allocation.py` — mapping campo→pomodoro non implementato
2. `emulatore_base.py` — full traceback nel log errore (formattazione incompleta)
3. Radar Census — dataset FAU_06..FAU_09 + Random Forest classifier

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
- `vai_in_home()`: aggiunto re-check finale dopo N conferme consecutive

### Fix caricamento gioco (`emulatore_base.py`)
- Dopo le 3 conferme popup: sequenza di 5 BACK + verifica stato reale
- Aggiunto traceback completo nel log errore raccolta

### Fix VIP daily (`daily_tasks.py`)
- BACK nel `finally` prima del ritorno in home
- Riconoscimento CLAIM free tramite pallino rosso — rimuove dipendenza da template IT/EN

### Fix rifornimento (`rifornimento.py`)
- Fix calcolo `eta_sec`, flag `quota_esaurita`, visualizzazione `-0.0M`
- `sleep(2.5)` dopo Tap Membri

---
## ✅ Versione v5.19 (task periodici + architettura consolidata)

### Radar Show (`radar_show.py` — nuovo)
- Task periodico ogni 12h — raccoglie ricompense Radar Station
- Connected components numpy puro — no scipy
- Verifica badge rosso prima di aprire — skip immediato se assente

### VIP Daily Rewards (`daily_tasks.py`)
- Macchina a 2 stati: cassaforte + CLAIM free
- CLAIM free ora via pixel detection (rimosso template matching IT/EN)

### Contatore squadre in HOME (`raccolta.py`)
- Early exit se slot pieni — risparmio ~15-20s per istanza

### Soglie rifornimento separate
- 4 soglie indipendenti: campo 5M / legno 5M / petrolio 2.5M / acciaio 3.5M
- Acciaio abilitato all'invio

### Fascia oraria per istanza
- Campo `fascia_oraria: "HH:MM-HH:MM"` — supporta fasce notturne (start > end)

### Produzione oraria con tempo reale (`status.py`)
- M/h basato su delta timestamp ISO — non più diviso per durata ciclo fissa

---
## ✅ Versione v5.18 (selezione livello nodo + produzione oraria dashboard)
- Livello nodo configurabile per istanza (5/6/7)
- OCR risorse: retry con backoff 2s→3s→4s
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
| `radar_census.py` | Census icone mappa — dataset + classificazione |
| `status.py` | Scrittura status.json per dashboard |
| `scheduler.py` | Schedulazione task per istanza |
| `alleanza.py` | Raccolta doni alleanza |
| `rifornimento.py` | Invio risorse all'alleanza |

### Note repository
- File JSON runtime/stato **non versionati**
- PNG versionati **solo** in `templates/`
- Log, debug, output runtime esclusi via `.gitignore`
- `config.py` — settings macchina-specifici, **non versionato**

---
## 📄 Licenza
MIT License
