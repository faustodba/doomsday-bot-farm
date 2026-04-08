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
## 🚧 Versione v5.25 (WIP — sviluppo in corso)

### Store / Mysterious Merchant (`store.py` — nuovo modulo)
- Task periodico ogni 4h (`SCHEDULE_ORE_STORE=4`, chiave `"store"`)
- Scan spirale 5×5 (25 posizioni, passo 300px) sulla mappa per trovare l'edificio Store
- Flusso completo: scan → tap edificio → verifica label/mercante diretto → tap carrello → acquista pulsanti gialli (pin_legno/pomodoro/acciaio) su 3 pagine con swipe → free refresh → secondo ciclo acquisti → BACK
- Riconoscimento mercante diretto via `pin_mercante.png` prima del tap (se visibile → skip carrello)
- Feature flag: `STORE_ABILITATO=False` in `config.py` / `runtime.json`
- Integrato in `raccolta.py` come primo task nel dispatcher `_esegui_task_periodici`
- Integrato in `daily_tasks.py` via `esegui_store_guarded()`
- Toggle nella dashboard con sezione parametri soglie e scheduling

#### Bug fix — pipeline screenshot store (`store._screenshot`)
- Usava `adb.screenshot()` (ritorna path stringa) invece di `adb.screenshot_bytes()` (ritorna bytes PNG)
- `decodifica_screenshot()` riceveva una stringa → `(None, None)` su tutte le 25 posizioni → `best score=-1.000`
- Fix: `raw = adb.screenshot_bytes(porta)` — stessa pipeline exec-out usata da tutto il bot

#### Bug fix — soglie store calibrate per pipeline exec-out (`config.py`)
- Template `pin_store.png` catturato con vecchio metodo adb pull → match via exec-out produce scarto sistematico ~0.03-0.05 punti (FAU_06: best score=0.797 con soglia 0.80 → NON TROVATO)
- `STORE_SOGLIA_STORE=0.75`, `STORE_SOGLIA_STORE_ATTIVO=0.75`, `STORE_SOGLIA_MERCANTE=0.75`
- `STORE_SOGLIA_ACQUISTO` invariato a 0.80 (falso positivo = acquisto sbagliato)

### Fix `rifornimento._slot_liberi` — contatore slot errato
- `_slot_liberi()` chiamava `conta_squadre()` senza `n_squadre` → OCR leggeva "4/4" su istanza con 5 slot → `libere=0` invece di 1
- Fix: lookup `ISTANZE_MUMU` per porta → passa `n_squadre=max_squadre` a `conta_squadre()`
- Totale noto a priori garantisce calcolo corretto anche quando il display mostra X/X

### Boost Gathering Speed (`test_boost_detection.py` — test standalone)
- Test standalone flusso Manage Shelter → Economic Boost → Gathering Speed
- Logica: tap `pin_boost(142,47)` → verifica `pin_manage` → scroll finché `pin_speed` visibile → verifica `pin_50_` (boost già attivo → skip) → tap riga → cerca `pin_speed_8h` → tap `pin_speed_use` (fallback: `pin_speed_1d`)
- Tutto basato su template matching dinamico — zero coordinate hardcoded per speed/8h/1d/USE
- Template: `pin_boost`, `pin_manage`, `pin_speed`, `pin_50_`, `pin_speed_8h`, `pin_speed_1d`, `pin_speed_use`
- Output screenshot annotati in `debug/boost_test/`

### Nuovi template (`templates/`)
- Store: `pin_store.png`, `pin_store_attivo.png`, `pin_carrello.png`, `pin_merchant.png`, `pin_mercante.png`, `pin_legno.png`, `pin_pomodoro.png`, `pin_no_refresh.png`, `pin_free_refresh.png`, `pin_soldout.png`
- Banner: `pin_banner_aperto.png`, `pin_banner_chiuso.png`
- Boost: `pin_boost.png`, `pin_manage.png`, `pin_speed.png`, `pin_50_.png`, `pin_speed_8h.png`, `pin_speed_1d.png`, `pin_speed_use.png`
- Raccolta: `pin_frecce.png`

### ⚠️ Pending
1. `boost.py` — modulo integrato (test standalone completato, integrazione bot da fare)
2. `allocation.py` — mapping campo→pomodoro
3. `emulatore_base.py` — full traceback log
4. Radar Census — dataset FAU_06..FAU_09 + Random Forest
5. Rinnovo template store con pipeline exec-out per riportare soglie a 0.80

---
## ✅ Versione v5.24 (pipeline in-memory + verifica UI + radar RF + arena mercato)

### Pipeline screenshot in-memory (`adb.py`)
- `screenshot_bytes()`: exec-out screencap -p → PNG bytes diretti, nessun file su device, nessun pull
- `decodifica_screenshot()`: decode unico PIL+cv2 da bytes — zero I/O disco
- `salva_screenshot()`: scrittura disco opzionale solo quando serve il file
- Lock screencap da globale → per-porta (`_get_screencap_lock(porta)`) — istanze parallele non si bloccano
- Risparmio stimato: 150-300ms per chiamata

### Refactoring in-memory (`config.py`, `debug.py`, `adb.py`, `stato.py`, `ocr.py`, `raccolta.py`, `verifica_ui.py`)
- Pipeline applicata: `screenshot_bytes()` → `decodifica_screenshot()` → `(pil_img, cv_img)` in memoria
- `raccolta._screenshot_cv()`: ritorna `(path, pil_img, cv_img)` — 3 valori (fix unpack 2→3)
- `stato.rileva()`: usa pipeline in-memory, fallback su `screenshot()` tradizionale
- `stato.conta_squadre()`: usa `screenshot_bytes()` + `decodifica_screenshot()`
- PRE-LENTE fix: `rileva_screen_mem(pil, cv_img)` per evitare "truth value of array"

### Sistema verifica UI pin_ (`verifica_ui.py`)
- Ogni tap critico preceduto da precondizione pin_ e seguito da postcondizione
- Template validati: raccolta (pin_lente, pin_field/sawmill/steel_mill/oil_refinery, pin_enter, pin_gather, pin_create_squad, pin_march/clear/max/no_squads), VIP (pin_vip_01–07, pin_point), Arena (pin_arena_01–06)
- `maschera_invio_ancora_aperta()`: metodo silent aggiunto

### Radar Census RF (`radar_census.py`, `radar_tool/`)
- RF classifier da `radar_tool/dataset/classifier.pkl`
- Annotazione pura cv2 BGR (no PIL), labels: pedone/auto/camion/skull/avatar/numero/card/paracadute/fiamma/bottiglia/soldati/sconosciuto
- ROI=(75,115,870,485), NMS_DIST=30

### Arena Mercato (`daily_tasks.py`, `config.py`)
- `ARENA_TAP_CARRELLO`, `ARENA_TAP_PRIMO_ACQUISTO`, `ARENA_TAP_MAX_ACQUISTO`
- `SCHEDULE_ORE_ARENA_MERCATO=12`, chiave `"arena_mercato"`

### Zaino refactor (`config.py`, `runtime.py`, `zaino.py`, `dashboard.html`)
- `ZAINO_MOLTIPLICATORE` rimosso; per-risorsa: `ZAINO_USA_*` (bool) + `ZAINO_SOGLIA_*_M` (soglia assoluta)

### Rifornimento mappa — coordinate rifugio esternalizzate
- `RIFUGIO_X/Y` in `config.py` (684,532) — modificabili dalla dashboard
- `rifornimento_mappa.py`: usa `getattr(config, "RIFUGIO_X", ...)` dinamico

### Fix bug v5.24
- `arena_of_glory.py`: `registra_esecuzione()` spostato fuori dal blocco `sfide>0` (fix FAU_09/10 loop)
- `daily_tasks.py`: `TAP_VIP_CHIUDI_REWARD_FREE=(456,437)` per GATE-F; `tap_campaign` layout-dipendente per FAU_10
- `adb.py`: lock screencap da globale → per-porta (parallelismo reale tra istanze su porte diverse)

---
## ✅ Versione v5.23 (WIP — completata)

### Arena of Glory (`arena_of_glory.py` — nuovo)
- Task giornaliero: esegue 5 sfide nell'Arena of Glory
- Popup stagionale "Congratulations": pixel check pulsante giallo Continue
- Popup sfide esaurite: pixel check pulsante Cancel grigio → uscita anticipata
- Flag: `ARENA_OF_GLORY_ABILITATO` | Schedulazione: 24h chiave `"arena"`

### Rifornimento via mappa (`rifornimento_mappa.py` — nuovo)
- Navigazione diretta al rifugio tramite coordinate mappa — bypass lista Membri
- Loop ottimizzato: resta in mappa tra spedizioni (elimina cicli home↔mappa)
- Template matching pulsante RESOURCE SUPPLY: `btn_resource_supply_map.png`
- Attivabile da dashboard: toggle "Supply via Map"
- Stessa logica di `rifornimento.py`: quota, soglie, coda volo, snapshot

### Fix rifornimento (`rifornimento.py`)
- `KEYCODE_BACK` aggiunto prima di ogni `return` su quota esaurita (3 punti)

### Fix configurazione
- `ADB_EXE` default MuMu in `config.py`
- `RIFORNIMENTO_MAPPA_ABILITATO` in config/runtime/dashboard

### ⚠️ Pending
1. `allocation.py` — mapping campo→pomodoro
2. `emulatore_base.py` — full traceback log
3. Radar Census — dataset FAU_06..FAU_09 + Random Forest
4. `rifornimento_mappa.py` — coordinate rifugio da esternalizzare per istanza

---
## 🚧 Versione v5.22 (WIP — sviluppo sospeso)

### Modifiche completate
- Sostituzione globale `assicura_home()` → `vai_in_home()` in tutti i moduli
- VIP CLAIM_FREE: coordinate calibrate
- `rifornimento.py`: `sleep(2.5)` dopo Tap Membri
- Task VIP e Radar separati in `_run_guarded()` individuali
- `runtime.py`: aggiunto `RADAR_CENSUS_ABILITATO`

---

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
| `daily_tasks.py` | Task periodici: VIP, Radar Show, Zaino, Arena |
| `arena_of_glory.py` | Arena of Glory — sfide giornaliere |
| `radar_show.py` | Radar Station — riconoscimento pallini con numpy |
| `radar_census.py` | Census icone mappa — dataset + classificazione |
| `status.py` | Scrittura status.json per dashboard |
| `scheduler.py` | Schedulazione task per istanza |
| `alleanza.py` | Raccolta doni alleanza |
| `rifornimento.py` | Invio risorse all'alleanza (via lista Membri) |
| `rifornimento_mappa.py` | Invio risorse all'alleanza (via coordinate mappa) |
| `store.py` | Acquisto automatico Mysterious Merchant Store |
| `test_boost_detection.py` | Test standalone flusso Gathering Speed Boost |

### Note repository
- File JSON runtime/stato **non versionati**
- PNG versionati **solo** in `templates/`
- Log, debug, output runtime esclusi via `.gitignore`
- `config.py` — settings macchina-specifici, **non versionato**

---
## 📄 Licenza
MIT License
