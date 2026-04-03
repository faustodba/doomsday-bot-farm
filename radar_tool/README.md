# radar_tool

Progetto standalone per censimento e classificazione delle icone
sulla mappa radar di Doomsday: Last Survivors.

## Installazione

```
pip install -r requirements.txt
```

## Flusso di lavoro

```
1. template_builder.py   ← definisci i template dei pin (click+drag)
2. scan.py               ← rileva tutti i pin sulla mappa
3. labeler.py            ← etichetta i pin con la GUI
4. train.py              ← addestra il classificatore
```

### 1. Crea i template  (GUI)
```
python template_builder.py map_full.png
```
- Click + drag sulla mappa per selezionare un pin
- Preview in tempo reale mentre trascini
- Inserisci il nome e salva (convezione: `pin_COLORE_TIPO`)
- Bottone **Test detection** per verificare i template sulla mappa
- Lista template a destra con miniatura e pulsante elimina

### 2. Scan
```
python scan.py map_full.png --debug
```
Genera `detections.json` e `dataset/crops/crop_NNN_tipo.png`

### 3. Etichetta  (GUI)
```
python labeler.py detections.json map_full.png
```
- Crop ingrandito 5× + contesto mappa
- Tasti rapidi: `1-9` label, `0`=sconosciuto, `D`=scarta, `Invio`=conferma
- Predizione Random Forest in tempo reale (dopo primo training)
- Bottone **Ri-addestra RF** senza uscire dalla GUI

### 4. Addestra
```
python train.py
```
Genera `dataset/classifier.pkl`

## Struttura

```
radar_tool/
├── template_builder.py   ← GUI interattiva template
├── scan.py               ← rilevamento pin
├── labeler.py            ← GUI etichettatura
├── train.py              ← addestramento RF
├── detector.py           ← logica detection (usato dagli altri)
├── classifier.py         ← logica RF (usato dagli altri)
├── requirements.txt
├── templates/            ← PNG dei pin di riferimento
│   ├── pin_viola_ped.png
│   ├── pin_rosso_skull.png
│   └── ...
└── dataset/
    ├── crops/            ← crop 64×64 estratti
    ├── labels.json       ← etichette
    └── classifier.pkl    ← modello addestrato
```

## Label disponibili

| Tasto | Label        |
|-------|-------------|
| 1     | zombie       |
| 2     | mostro       |
| 3     | avatar       |
| 4     | paracadute   |
| 5     | camion       |
| 6     | auto         |
| 7     | pedone       |
| 8     | skull        |
| 9     | numero       |
| 0     | sconosciuto  |
| D     | scarta (FP)  |
