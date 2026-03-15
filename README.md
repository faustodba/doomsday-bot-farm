# 🤖 Doomsday Bot V5

Bot Python per l'automazione della raccolta risorse nel gioco **Doomsday: Last Survivors** su emulatori Android.

---

## ⚠️ Disclaimer

Questo progetto nasce come **studio personale** sulle tecnologie di automazione (Python, ADB, OCR con Tesseract, computer vision con OpenCV) applicato a un contesto di gioco.

- **Nessun fine di lucro**: il software è sviluppato e distribuito gratuitamente
- **Solo uso personale**: non è previsto alcun uso commerciale
- **Fair use**: l'automazione avviene esclusivamente su istanze emulate di proprietà dell'utente
- **Nessuna garanzia**: il software è fornito "così com'è" — l'utilizzo è a proprio rischio

L'autore non è affiliato con IGG (International Game Group) né con i produttori di Doomsday: Last Survivors. Tutti i marchi citati appartengono ai rispettivi proprietari.

---

## 📋 Descrizione

Il bot gestisce in modo automatico le operazioni ripetitive del gioco su più istanze in parallelo:

- Raccolta messaggi (tab Alleanza e Sistema) — **schedulata ogni 12 ore per istanza**
- Raccolta ricompense Alleanza (Negozio + Attività) — **schedulata ogni 12 ore per istanza**
- Invio rifornimenti con gestione quota giornaliera e **delta reale OCR pre/post invio**
- Ricerca e invio raccoglitori su nodi risorse (campo/segheria/acciaieria/raffineria)
- **Sistema decisionale adattivo** basato sul gap deposito vs target per allocare gli slot
- **Verifica territorio alleanza** prima di inviare raccoglitori (pixel verde "+30%")
- Gestione blacklist nodi con attesa dinamica basata su ETA marcia OCR
- **OCR completo deposito:** pomodoro, legno, acciaio, petrolio, diamanti
- **Dashboard web** con dati storici persistenti tra riavvii
- **Configurazione runtime** modificabile senza riavviare il bot

---

## 🖥️ Emulatori supportati

| Emulatore | Versione | Note |
|-----------|----------|------|
| BlueStacks | 5+ | Avviato e stoppato per ogni ciclo |
| MuMuPlayer | 12 | Integrato con Provider Pattern |

---

## ⚙️ Architettura

```
main.py
│
├── runtime.py          ← rilettura config JSON ogni ciclo (no riavvio)
│
├── Pool con Semaphore (max N istanze parallele)
│   └── worker per istanza
│       ├── avvia_blocco()         → emulatore (BS/MuMu)
│       ├── attendi_e_raccogli_istanza() → emulatore_base
│       │   ├── polling popup (3 conferme)
│       │   └── raccolta_istanza() → raccolta.py
│       │       ├── messaggi.py    ← skip se <12h dall'ultima
│       │       ├── alleanza.py    ← skip se <12h dall'ultima
│       │       ├── rifornimento.py   ← HOME, delta reale OCR pre/post VAI
│       │       └── loop invio squadre
│       │           ├── allocation.py  ← sequenza adattiva gap-based
│       │           ├── verifica territorio (pixel verde)
│       │           └── blacklist nodi (RESERVED/COMMITTED/ETA dinamica)
│       └── chiudi_istanza()
└── cleanup_istanze_appese()
```

---

## 📦 Moduli

| Modulo | Descrizione |
|--------|-------------|
| `main.py` | Entry point, pool con semaforo, loop principale |
| `raccolta.py` | Flusso raccolta risorse per singola istanza |
| `allocation.py` | **NUOVO** Sistema decisionale allocazione slot (gap proporzionale) |
| `runtime.py` | **NUOVO** Configurazione modificabile a runtime via JSON |
| `alleanza.py` | Automazione menu Alleanza/Dono — schedulata |
| `messaggi.py` | Raccolta messaggi in-game — schedulata |
| `rifornimento.py` | Invio rifornimenti con delta OCR reale e soglie per risorsa |
| `scheduler.py` | Schedulazione task periodici su file stato |
| `bluestacks.py` | Gestione ciclo vita BlueStacks |
| `mumu.py` | Gestione ciclo vita MuMuPlayer 12 |
| `emulatore_base.py` | Logica comune condivisa tra emulatori |
| `adb.py` | Comandi ADB (tap, screenshot, keyevent) |
| `ocr.py` | OCR Tesseract — risorse complete + ETA marcia |
| `stato.py` | Rilevamento stato gioco |
| `config.py` | Configurazione centralizzata |
| `timing.py` | EWMA adaptive timing |
| `log.py` | Logging centralizzato |
| `debug.py` | Screenshot diagnostici |
| `status.py` | status.json per dashboard — persistente tra riavvii |
| `report.py` | Report HTML a fine ciclo |
| `launcher.py` | GUI tkinter (in sviluppo) |
| `dashboard.html` | Dashboard web real-time |
| `dashboard_server.py` | HTTP server porta 8080 + endpoint POST runtime |

---

## 🔧 Requisiti

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [ADB](https://developer.android.com/tools/adb)
- BlueStacks 5+ e/o MuMuPlayer 12

```bash
pip install pillow pytesseract opencv-python
```

---

## 🚀 Avvio

```bash
cd C:\Bot-raccolta\V5

# Avvio bot
python main.py --emulatore 1

# Dashboard (finestra separata)
python dashboard_server.py
# Aprire: http://localhost:8080/dashboard.html
```

---

## 📊 Sistema decisionale allocazione slot

Ad ogni ciclo il bot calcola il **gap** tra la percentuale attuale di ogni risorsa nel deposito e il target prefissato:

```
RATIO_TARGET:
  pomodoro  →  37.5%   (nodo lv6: 1.200.000)
  legno     →  37.5%   (nodo lv6: 1.200.000)
  petrolio  →  18.75%  (nodo lv6:   600.000)
  acciaio   →   6.25%  (nodo lv6:   240.000)
```

Gli slot disponibili vengono assegnati ai tipi con gap positivo maggiore. Configurabile a runtime dalla dashboard senza riavviare il bot.

---

## 🗺️ Verifica territorio alleanza

Prima di inviare un raccoglitore, il bot verifica che il nodo sia **nel territorio dell'alleanza** controllando la presenza del buff "+30% velocità raccolta" (pixel verdi nella zona del popup). I nodi fuori territorio vengono scartati e il bot passa al tipo successivo.

---

## ⚙️ Configurazione runtime

Modifica i parametri **senza riavviare il bot** tramite la dashboard web o editando `runtime.json`:

| Parametro | Descrizione |
|-----------|-------------|
| `ISTANZE_BLOCCO` | Istanze in parallelo |
| `WAIT_MINUTI` | Attesa tra cicli |
| `RIFORNIMENTO_ABILITATO` | Abilita/disabilita invio risorse |
| `RIFORNIMENTO_SOGLIA_M` | Soglia minima invio pomodoro/legno |
| `RIFORNIMENTO_SOGLIA_PETROLIO_M` | Soglia minima invio petrolio |
| `ALLOCATION_RATIO` | Pesi allocazione slot per risorsa |
| `istanze_bs/mumu` | Abilitazione, truppe, max squadre per istanza |

---

## 📈 Calcolo produzione

```
produzione_ciclo_N = (deposito_inizio_N+1 - deposito_inizio_N) + inviato_N
```
Disponibile dal 2° ciclo in poi. Visibile nella dashboard per istanza e aggregato nello storico.

---

## 📁 File di output runtime

```
C:\Bot-raccolta\V5\
├── bot.log
├── status.json
├── runtime.json                     ← configurazione runtime
├── timing.json
├── rifornimento_stato_{nome}_{porta}.json
├── schedule_stato_{nome}_{porta}.json
└── debug\ciclo_NNN\
    ├── report_ciclo_NNN.html
    └── *.png
```

---

## 🗂️ Struttura repository

```
V5\
├── *.py              ← moduli principali
├── tests\            ← script di test e calibrazione
├── templates\        ← immagini template matching (avatar, pulsanti)
├── archive\          ← versioni archiviate (non in uso)
├── runtime.json      ← config runtime (generato al primo avvio)
├── CONTEXT.md        ← contesto sessioni Claude
├── LICENSE           ← MIT License
└── README.md
```

---

## 📜 Storico versioni

| Versione | Note |
|----------|------|
| V2 | AutoHotkey — 14 istanze Sandboxie |
| V3 | Python, singolo emulatore |
| V4 | Multithreading, multi-emulatore, MuMu |
| V5 | Alleanza, messaggi, rifornimento, launcher, dashboard |
| V5.9 | Blacklist, lettura reale post-MARCIA |
| V5.10 | Loop while, OCR retry |
| V5.11 | rifornimento template matching |
| V5.12 | Rifornimento completo, quota giornaliera |
| V5.13 | Blacklist RESERVED/COMMITTED |
| V5.13.2 | ETA marcia OCR, attesa dinamica |
| V5.14 | OCR completo deposito, produzione inter-ciclo, schedulazione 12h, dashboard storico+diamanti+inviato |
| V5.15 | allocation.py (gap decisionale 4 risorse), 4 tipi nodo + verifica territorio alleanza, soglie rifornimento per risorsa, runtime.json configurazione live, pannello Runtime in dashboard |

---

## 📄 Licenza

Distribuito sotto licenza **MIT** — vedi [LICENSE](LICENSE) per i dettagli.

In sintesi: puoi usare, copiare, modificare e distribuire questo software liberamente, anche senza chiedere permesso, a condizione di mantenere il copyright originale. Il software è fornito senza alcuna garanzia.

---

## 🗂️ Contesto sessioni Claude

```
# A inizio sessione:
"leggi il contesto"
# Claude fa web_fetch su CONTEXT.md da GitHub
```
