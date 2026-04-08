# Doomsday Bot V5 — CONTEXT FILE

## Architettura generale

### Pattern coordinate UI
Tutte le coordinate UI seguono un flusso centralizzato a 3 livelli:
1. **`config.py` sezione 5** — definisce costanti coordinate (es. `TAP_RADAR_ICONA`)
2. **`coords.py` `UICoords`** — dataclass frozen che espone le coordinate per istanza; costruita una volta per ciclo da `UICoords.da_ist(ist)`
3. **Moduli operativi** — ricevono `coords` come parametro, non leggono mai `config.*` direttamente

Eccezione: coordinate globali invarianti tra istanze (es. `RADAR_MAPPA_ZONA`) vengono lette direttamente da `config` nei moduli interni.

### Pattern template matching
I template lingua-dipendenti (IT/EN) seguono lo stesso flusso:
- Costanti in `config.py`: `RIFORNIMENTO_BTN_TEMPLATE`, `VIP_CLAIM_FREE_TEMPLATE`, ecc.
- Getter in `config.py`: `get_btn_rifornimento_template(ist)`, `get_btn_claim_free_template(ist)`
- Risoluzione in `coords.py`: `btn_rifornimento_template`, `btn_claim_free_template`
- Uso nei moduli: `coords.btn_rifornimento_template`

### Pattern task periodici
Tutti i task schedulati seguono lo stesso schema:
1. Flag abilitazione in `config.py` (es. `DAILY_RADAR_ABILITATO`)
2. Intervallo schedulazione in `config.py` (es. `SCHEDULE_ORE_RADAR = 12`)
3. Flag e intervallo sovrascrivibili da `runtime.json` → dashboard
4. Controllo schedulazione tramite `scheduler.deve_eseguire(nome, porta, task)`
5. Esecuzione nel modulo dedicato (es. `radar_show.esegui_radar_show(porta, nome, coords, logger)`)
6. Registrazione in `scheduler.registra_esecuzione(nome, porta, task)`
7. Stato persistito in `istanza_stato_{nome}_{porta}.json`

### Pattern runtime
- `config.py` — valori default statici
- `runtime.json` — overrides globali e per-istanza (riletto ogni ciclo)
- `runtime.py applica()` — sovrascrive `config.*` in memoria con i valori da runtime.json
- `runtime.py istanze_attive()` — lista istanze fresh da config + overrides applicati
- Dashboard → modifica runtime.json → effetto al ciclo successivo senza riavvio

### Pattern status/produzione
- `status.py` — scrive `status.json` in tempo reale per la dashboard
- Produzione calcolata come delta inter-ciclo: `(res_inizio_N+1 - res_inizio_N) + res_inviato_N`
- Timestamp ISO `ts_res_inizio` salvato ad ogni lettura OCR → M/h calcolato con tempo reale
- Storico cicli con `ts_iso` per calcolo gap reale tra cicli (gestisce interruzioni bot)

---

## 2026-03-22 — V5.19

### daily_tasks.py (nuovo task Radar Show)
- Aggiunto task `radar` eseguito dopo VIP, schedulazione 12h
- `esegui_daily_tasks()` riceve `coords` (UICoords) e lo passa ai task
- Flag `DAILY_RADAR_ABILITATO` in config/runtime/dashboard

### radar_show.py (nuovo modulo)
- Task Radar Station: raccolta ricompense dalla mappa dinamica
- Verifica badge rosso sull'icona prima di aprire (pixel detection)
- Connected components numpy puro (no scipy) per trovare pallini rossi
- Filtro forma circolare: compattezza > 0.55, aspect_ratio > 0.5, 8≤w/h≤22px
- Delay 10s post-apertura per notifiche che scorrono
- Calibrato su dataset 9 screen reali FAU_00..FAU_09
- Pattern architetturale: `coords.tap_radar_icona` per coordinata icona

### raccolta.py
- Contatore squadre letto in **HOME** prima di `vai_in_mappa`
- Early exit immediato se slot pieni — evita viaggio home→mappa→home
- Fallback: se lettura home era assunta (0/N), rilegge in mappa per conferma

### daily_tasks.py (VIP)
- Macchina a 2 stati: cassaforte (coordinate fisse) + CLAIM free (template matching)
- Template CLAIM free risolto da `coords.btn_claim_free_template`
- STATO 1: tap badge VIP → tap cassaforte → dismiss popup ricompense
- STATO 2: screenshot → cerca `btn_claim_free_en/it.png` → tap se trovato
- ⚠️ `btn_claim_free_it.png` ancora mancante (BlueStacks IT)

### config.py
- `SCHEDULE_ORE_RADAR = 12`, `DAILY_RADAR_ABILITATO = True`
- Coordinate Radar Station: `TAP_RADAR_ICONA`, `RADAR_MAPPA_ZONA`, `RADAR_*`
- 4 soglie rifornimento separate: `RIFORNIMENTO_SOGLIA_CAMPO/LEGNO/PETROLIO/ACCIAIO_M`
- `QTA_ACCIAIO` abilitato (era 0)
- Fascia oraria per istanza: commento campo `fascia_oraria`

### coords.py
- Aggiunto `tap_radar_icona: Coord` al dataclass UICoords
- Aggiunto `btn_claim_free_template: str` al dataclass UICoords

### runtime.py
- `DAILY_RADAR_ABILITATO` in `_default()` e `applica()`
- `DAILY_VIP_ABILITATO` in `_default()` e `applica()`
- 4 soglie rifornimento separate in `_default()` e `applica()`
- Fascia oraria per istanza: `_in_fascia(fascia)` + filtro in `istanze_attive()`

### dashboard.html
- Label task in inglese: Alliance Gifts / Alliance Messages / VIP Daily Rewards / Radar Show / Supply Resources
- Checkbox Radar Show (`rt_radar_on`)
- Layout 2 colonne sezione parametri globali
- 4 campi soglia rifornimento separati con emoji risorsa
- Colonna Fascia oraria con 2 time picker (checkbox on/off + HH:MM start/end)
- Refresh 10s (era 3s)

### status.py
- `ts_res_inizio` / `ts_res_inizio_prec`: timestamp ISO lettura OCR risorse
- `_calcola_produzione()`: aggiunge `_mh` (M/h per risorsa) con tempo reale
- `ciclo_completato()`: aggiunge `ts_iso` nello storico cicli

### rifornimento.py
- Soglie per risorsa da 4 parametri separati (era `RIFORNIMENTO_SOGLIA_M` unico)
- Acciaio non più escluso con `float("inf")`

### allocation.py
- `RATIO_TARGET` default aggiornato: 35/35/18.75/11.25 (acciaio era 6.25%)
- `_sequenza_default` ricostruita: acciaio appare dalla posizione 6

### main.py
- Stampa configurazione runtime con label EN e tutte le soglie rifornimento

---

## 2026-03-21 — V5.18 (selezione livello nodo + produzione oraria dashboard)

### raccolta.py
- `_cerca_nodo`: selezione livello nodo via popup UI
- OCR risorse: retry con backoff 2s→3s→4s

### config.py
- Campo `"livello": 6` a tutte le istanze

### dashboard.html
- Colonna Lv. con select 5/6/7
- Pannello produzione oraria M/h

---

## 2026-03-18 — V5.17 (fix raccolta + robustezza)

### raccolta.py
- BUG1/BUG3/BUG4 fix, contatore reale, OCR retry

### stato.py / alleanza.py / mumu.py / log.py
- Fix navigazione, timing, cleanup processi, rotazione log

---

## 2026-03-24 — V5.20 (zaino settimanale + fix banner/stato)

### zaino.py (nuovo modulo)
- Task settimanale: scarica risorse dallo zaino/backpack quando sotto soglia
- Trigger: ogni lunedì (SCHEDULE_ORE_ZAINO=168h), solo se almeno una risorsa < soglia
- Target: soglia × ZAINO_MOLTIPLICATORE (default 2×)
- Strategia: pezzature piccole prima; usa MAX se pezzatura ≤ gap residuo; pack misti ignorati
- Apertura: TAP_ZAINO_APRI=(430,18) barra alta → sidebar sempre su Food al primo tap
- Sidebar risorse: Food(80,130) Wood(80,200) Steel(80,270) Oil(80,340)
- Griglia pack: USE_X=722, MAX_X=601, prima riga Y=140, altezza righe 80px
- Chiusura: tap X=(783,68)
- Risorse gestite in ordine: acciaio → petrolio → legno → pomodoro (solo quelle sotto soglia)

### stato.py
- `assicura_home()`: aggiunto BACK preventivi (N_BACK_ASSICURA=3, DELAY_BACK_ASSICURA=0.4s)
  prima di `rileva()` — chiude banner fullscreen che venivano classificati erroneamente come "home"
- `vai_in_home()`: aggiunto re-check finale con sleep(1.0) dopo N conferme consecutive
  per evitare false conferme durante transizioni mappa→home
- Nuove costanti: N_BACK_ASSICURA, DELAY_BACK_ASSICURA

### emulatore_base.py
- Dopo le 3 conferme popup caricamento: sostituito singolo BACK+0.6s con sequenza
  N_BACK_PULIZIA=5 × DELAY_BACK_PULIZIA=0.5s + verifica stato reale via stato.rileva()
  Prima di dichiarare "Gioco pronto!" lo stato viene confermato esplicitamente
- Aggiunto `import traceback` e `traceback.format_exc()` nel blocco except raccolta
- Nuove costanti: N_BACK_PULIZIA, DELAY_BACK_PULIZIA

### daily_tasks.py
- VIP: aggiunto KEYCODE_BACK nel finally prima del ritorno in home (bug fix V5.20)
- VIP: sostituito template matching CLAIM free con riconoscimento pallino rosso
  (CLAIM_FREE_BADGE_ZONA=(650,270,730,320), TAP_VIP_CLAIM_FREE=(575,380))
  (stessa logica di radar_show — no più dipendenza template IT/EN)
- ⚠️ `btn_claim_free_it.png` non più necessario

### rifornimento.py
- Fix calcolo `eta_sec` (divisione per zero in edge case)
- Fix flag `quota_esaurita` (veniva resettato incorrettamente)
- Fix visualizzazione `-0.0M` nel log (ora mostra `0.0M`)
- `assicura_home()` chiamato correttamente prima di ogni spedizione
- Aggiunto `sleep(2.5)` dopo Tap Membri per stabilizzazione UI

### raccolta.py
- Integrazione chiamata `zaino.esegui_zaino()` nel ciclo prima di rifornimento
- Aggiunto sleep post home→mappa per stabilizzazione UI

### config.py
- `ZAINO_ABILITATO = True`
- `ZAINO_MOLTIPLICATORE = 2`
- `SCHEDULE_ORE_ZAINO = 168` (7 giorni)
- TAP_ZAINO_APRI, coordinate sidebar e griglia zaino

### scheduler.py
- `zaino: 168` aggiunto in `_DEFAULT_ORE`
- `_ore_intervallo()` legge `SCHEDULE_ORE_ZAINO` da config

---

## 2026-03-26 — V5.21 WIP (in sviluppo — sessione sospesa)

### Modifiche completate
- Sostituzione globale `assicura_home()` → `vai_in_home()` in tutti i moduli
- VIP CLAIM_FREE: coordinate calibrate `CLAIM_FREE_BADGE_ZONA=(650,270,730,320)`, `TAP_VIP_CLAIM_FREE=(575,380)`
- `rifornimento.py`: `sleep(2.5)` dopo Tap Membri (stabilizzazione UI)
- `raccolta.py`, `daily_tasks.py`: task VIP e Radar separati in chiamate `_run_guarded()` individuali
- `runtime.py`: aggiunto `RADAR_CENSUS_ABILITATO`

### Radar Census (`radar_census.py` — nuovo modulo)
- Dataset 34 campioni verificati (FAU_00..FAU_05)
- Problema aperto: zombie grandi non separabili da avatar con sole feature RGB
- Prossimo step: Random Forest con scikit-learn + feature spaziali
  (g_top_ratio, r_top_ratio, hue_dominante, edge_density)
- Da completare: raccolta campioni FAU_06..FAU_09

### ⚠️ PENDING — da completare alla ripresa
1. **`allocation.py`** — mapping campo→pomodoro non ancora implementato
2. **`emulatore_base.py`** — full traceback nel log errore (import traceback già presente, log formattato incompleto)
3. **Radar Census** — completare dataset FAU_06..FAU_09, poi implementare Random Forest classifier

### Regole di sviluppo consolidate
- Fix bug uno alla volta da log live — nessun refactoring rename globale
- Richiedere sempre il file attuale dal PC prima di modifiche — mai lavorare da memoria
- Git commit file per file con `git add` esplicito
- CONTEXT.md e README.md aggiornati prima di ogni tag

---

## 2026-03-28 — V5.23 WIP

### arena_of_glory.py (nuovo modulo)
- Task giornaliero Arena of Glory (Arena of Doom): esegue MAX_SFIDE=5 sfide
- Navigazione: HOME → Campaign → Arena of Doom → tap ultima sfida → START CHALLENGE
- Popup stagionale "Congratulations/Glory Silver": pixel check pulsante giallo Continue
- Popup sfide esaurite "Purchase more attempts?": pixel check pulsante Cancel grigio
- Nessun OCR — contatore fisso MAX_SFIDE, uscita anticipata su popup esaurite
- Tutte le coordinate in `config.py` sezione `# --- Arena of Glory ---`
- Integrato come daily task 24h in `daily_tasks.esegui_arena_guarded()`
- Chiave schedulazione: `"arena"` in `istanza_stato_{nome}_{porta}.json`
- Flag: `ARENA_OF_GLORY_ABILITATO` in config/runtime/dashboard

### rifornimento_mappa.py (nuovo modulo)
- Flusso alternativo invio risorse via coordinate mappa (bypass lista Membri)
- Navigazione: HOME → Mappa → lente coordinate → digita X,Y → conferma → tap castello → RESOURCE SUPPLY
- Loop ottimizzato: resta in mappa tra spedizioni consecutive (no cicli home↔mappa)
- Template matching: `templates/btn_resource_supply_map.png` per pulsante RESOURCE SUPPLY
- Coordinate rifugio hardcoded: `RIFUGIO_X=684, RIFUGIO_Y=532` (TODO: esternalizzare)
- Stessa logica di `rifornimento.py`: controllo quota, soglie, coda volo, snapshot pre/post
- Dispatcher in `raccolta.py`: `RIFORNIMENTO_MAPPA_ABILITATO` sceglie il flusso
- ADB_EXE default MuMu in `config.py` (`ADB_EXE = MUMU_ADB or BS_ADB`)

### rifornimento.py
- Fix: `KEYCODE_BACK` prima di `return` su quota esaurita (3 punti)
  - `_compila_e_invia`: provviste=0 iniziale e dopo compilazione
  - `esegui_rifornimento`: quota_esaurita nel loop principale

### config.py
- `ADB_EXE = MUMU_ADB or BS_ADB` (default MuMu)
- Sezione `# --- Arena of Glory (960x540) ---` con 16 costanti coordinate/pixel
- `ARENA_OF_GLORY_ABILITATO = False`, `SCHEDULE_ORE_ARENA = 24`
- `RIFORNIMENTO_MAPPA_ABILITATO = False`

### runtime.py
- `ARENA_OF_GLORY_ABILITATO` in `_default()` e `applica()`
- `RIFORNIMENTO_MAPPA_ABILITATO` in `_default()` e `applica()`

### raccolta.py
- Task Arena dopo Zaino: `_daily.esegui_arena_guarded(porta, nome, logger)`
- Dispatcher rifornimento: se `RIFORNIMENTO_MAPPA_ABILITATO` usa `rifornimento_mappa`, altrimenti vecchio flusso

### daily_tasks.py
- `esegui_arena_guarded()`: scheduling 24h chiave "arena", pattern identico a VIP/Radar

### dashboard.html
- Toggle "Arena of Glory" (`rt_arena_on`)
- Toggle "Supply via Map" (`rt_rif_mappa_on`) con default false

### ⚠️ PENDING — invariati da V5.21
1. **`allocation.py`** — mapping campo→pomodoro non ancora implementato
2. **`emulatore_base.py`** — full traceback nel log errore
3. **Radar Census** — dataset FAU_06..FAU_09 + Random Forest classifier
4. **`rifornimento_mappa.py`** — coordinate rifugio da esternalizzare in JSON per istanza

---

## 2026-04-08 — V5.25 WIP

### store.py (nuovo modulo)
- Task periodico ogni 4h, chiave `"store"`, flag `STORE_ABILITATO=False`
- Scan spirale 5×5 (25 posizioni, passo 300px): `GRIGLIA` lista delta (dx,dy)
- Gestione banner: `_comprimi_banner()` / `_ripristina_banner()` via `pin_banner_aperto/chiuso.png`
- Ricerca edificio: `_match(cv_img, "pin_store.png", roi=roi_corrente)` — ROI dipende da banner aperto/chiuso
- Mercante diretto: check `pin_mercante.png` pre-tap → se visibile skip carrello
- Flusso negozio: `_gestisci_negozio()` → label → carrello → merchant → acquista × 3 pagine → refresh → secondo ciclo
- Acquisto: `_acquista_pagina()` → `_conta_pulsanti()` → NMS su pin_legno/pomodoro/acciaio → tap tutti → verifica rimasti
- Integrato in `raccolta._esegui_task_periodici()` come primo task
- Integrato in `daily_tasks.esegui_store_guarded()` con pattern scheduler standard

#### Bug fix critico — `store._screenshot()` (v5.25.1)
- **Prima**: `raw = adb.screenshot(porta)` → ritorna path stringa → `decodifica_screenshot(str)` crash silenzioso → `(None, None)` × 25 → `best score=-1.000`
- **Dopo**: `raw = adb.screenshot_bytes(porta)` → bytes PNG → pipeline corretta
- `adb.screenshot()` → ritorna **path stringa** (backward compat) — MAI usare con `decodifica_screenshot`
- `adb.screenshot_bytes()` → ritorna **bytes PNG** — SEMPRE usare nei nuovi moduli

#### Bug fix soglie — exec-out vs adb pull (v5.25.2)
- Template catturati con adb pull → exec-out produce scarto sistematico ~0.03-0.05
- FAU_06 best score=0.797 con soglia 0.80 → store NON TROVATO
- `STORE_SOGLIA_STORE=0.75`, `STORE_SOGLIA_STORE_ATTIVO=0.75`, `STORE_SOGLIA_MERCANTE=0.75`
- `STORE_SOGLIA_ACQUISTO=0.80` invariato — falso positivo = acquisto sbagliato
- Dopo rinnovo template con exec-out riportare soglie a 0.80

### rifornimento.py — fix `_slot_liberi`
- **Prima**: `conta_squadre(porta, n_letture=3)` senza `n_squadre` → OCR legge "4/4" su istanza 5 slot → `libere=4-4=0`
- **Causa**: il gioco mostra X/Y dove Y = slot raccolta configurati per istanza, non totale assoluto
- **Dopo**: lookup `ISTANZE_MUMU` per porta → `n_squadre=ist.get("max_squadre")` → passato a `conta_squadre`
- Fallback: porta non trovata → `n_squadre=-1` (comportamento precedente, non blocca)

### config.py
- Sezione `# --- Store / Mysterious Merchant ---` aggiunta (10 costanti)
- `STORE_ABILITATO=False`, `SCHEDULE_ORE_STORE=4`
- Soglie calibrate exec-out: STORE=0.75, STORE_ATTIVO=0.75, MERCANTE=0.75, ACQUISTO=0.80
- Commento calibrazione con motivazione e condizione per riportare a 0.80

### test_boost_detection.py (nuovo — test standalone)
- Pattern identico a `test_store_detection.py`
- Step 1: tap `(142,47)` → verifica `pin_manage.png`
- Step 2-3: scroll max 8 → cerca `pin_speed.png`; stessa screenshot → check `pin_50_.png`
- Step 4: boost attivo → BACK×3 → exit
- Step 5: tap coordinate trovate da match `pin_speed`
- Step 6: `pin_speed_8h` + `pin_speed_use` → tap USE
- Step 7: fallback `pin_speed_1d` + `pin_speed_use` → tap USE
- Step 8: nessun boost disponibile → BACK×3 → exit
- Soglie iniziali tutte 0.75 — calibrare dopo primo test reale

### Nuovi template (tutti in `templates/`)
- Store (10): `pin_store`, `pin_store_attivo`, `pin_carrello`, `pin_merchant`, `pin_mercante`, `pin_legno`, `pin_pomodoro`, `pin_no_refresh`, `pin_free_refresh`, `pin_soldout`
- Banner (2): `pin_banner_aperto`, `pin_banner_chiuso`
- Boost (7): `pin_boost`, `pin_manage`, `pin_speed`, `pin_50_`, `pin_speed_8h`, `pin_speed_1d`, `pin_speed_use`
- Raccolta (1): `pin_frecce`

### ⚠️ PENDING
1. `boost.py` — modulo integrato nel bot (test standalone completato)
2. `allocation.py` — mapping campo→pomodoro
3. `emulatore_base.py` — full traceback log
4. Radar Census — dataset FAU_06..FAU_09 + Random Forest
5. Rinnovo template store con exec-out → soglie tornano a 0.80
