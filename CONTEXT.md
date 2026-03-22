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
