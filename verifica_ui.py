# ==============================================================================
#  DOOMSDAY BOT V5 - verifica_ui.py
#  Verifica visiva tramite template matching cv2 per i punti critici del flusso.
#
#  ATTIVAZIONE: config.py → VERIFICA_UI_ABILITATA = True / False
#  Se False, ogni funzione ritorna True immediatamente (nessun overhead).
#
#  v5.24 — Pipeline in-memoria: _screen() usa screenshot_bytes()+decodifica_screenshot()
#           _match_mem() lavora su cv_img già decodificato — zero I/O disco.
#           _match() su file mantenuto per backward compat con altri moduli.
#
#  TEMPLATE (tutti in C:\Bot-farm\templates\):
#    pin_region.png        — pulsante toggle HOME  (basso-sx)
#    pin_shelter.png       — pulsante toggle MAPPA (basso-sx)
#    pin_field.png         — Field selezionato nel pannello lente
#    pin_sawmill.png       — Sawmill selezionato
#    pin_steel_mill.png    — Steel Mill selezionato
#    pin_oil_refinery.png  — Oil Refinery selezionato
#    pin_gather.png        — pulsante GATHER nel popup nodo
#    pin_create_squad.png  — pulsante CREATE SQUAD (nessuna squadra formata)
#    pin_march.png         — pulsante MARCH nella maschera invio
#    pin_clear.png         — pulsante CLEAR nella maschera invio
#    pin_max.png           — pulsante MAX nella maschera invio (squadre=0)
#    pin_no_squads.png     — pulsante NO SQUADS nella maschera invio
#
#  SOGLIE VALIDATE SU DATI REALI:
#    pin_region/shelter:   match=0.993  cross=0.30  soglia=0.80
#    pin_field/..refinery: match=0.991  cross=0.77  soglia=0.85
#    pin_gather:           match=0.987  cross=0.41  soglia=0.80
#    pin_create_squad:     match=0.984  cross=0.41  soglia=0.80
#    pin_march:            match=0.986  cross=0.27  soglia=0.80
#    pin_clear:            match=0.991  cross=0.55  soglia=0.75
#    pin_max:              match=0.991  cross=0.56  soglia=0.75
#    pin_no_squads:        match=0.991  cross=0.39  soglia=0.80
# ==============================================================================

import os
import cv2
import config

# ------------------------------------------------------------------------------
# Cache template in memoria (caricati lazy al primo uso)
# ------------------------------------------------------------------------------
_TMPL_DIR   = os.path.join(config.BOT_DIR, "templates")
_tmpl_cache = {}


def _tmpl(nome: str):
    """Ritorna il template cv2 dalla cache. None se file mancante."""
    if nome not in _tmpl_cache:
        path = os.path.join(_TMPL_DIR, nome)
        t = cv2.imread(path)
        _tmpl_cache[nome] = t
    return _tmpl_cache[nome]


def _match_mem(cv_img, template_file: str, roi: tuple) -> float:
    """
    Template matching in-memoria su cv_img già decodificato (pipeline v5.24).
    ROI (x1,y1,x2,y2) in coordinate 960x540 — scala automaticamente.
    Ritorna score 0-1, oppure -1.0 in caso di errore.
    """
    try:
        tmpl = _tmpl(template_file)
        if tmpl is None or cv_img is None:
            return -1.0

        h_img, w_img = cv_img.shape[:2]
        x1, y1, x2, y2 = roi
        if w_img != 960 or h_img != 540:
            sx = w_img / 960.0
            sy = h_img / 540.0
            x1, y1 = int(x1*sx), int(y1*sy)
            x2, y2 = int(x2*sx), int(y2*sy)

        roi_img = cv_img[y1:y2, x1:x2]
        if roi_img.size == 0:
            return -1.0

        res = cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        return float(max_val)
    except Exception:
        return -1.0


def _match(screen_path: str, template_file: str, roi: tuple) -> float:
    """
    Template matching su file — backward compat per moduli che usano screen_path.
    Internamente carica cv2 e delega a _match_mem().
    """
    try:
        img = cv2.imread(screen_path)
        return _match_mem(img, template_file, roi)
    except Exception:
        return -1.0


# ------------------------------------------------------------------------------
# Classe principale
# ------------------------------------------------------------------------------

class VerificaUI:
    """
    Verifica visiva template-based per i punti critici del flusso raccolta.

    v5.24 — Pipeline in-memoria: _screen() usa adb.screenshot_bytes() +
    adb.decodifica_screenshot() e restituisce cv_img. Nessun I/O disco
    durante le verifiche. _check() riceve cv_img direttamente.

    Uso tipico in raccolta.py:
        v = VerificaUI(porta, nome, logger)

        # dopo tap tipo x2
        if not v.tipo_selezionato("campo"):
            log("tipo non selezionato — retry")

        # dopo tap sul nodo
        if not v.gather_visibile():
            log("popup nodo non aperto — tap fallito")

        # dopo tap GATHER + selezione squadra
        if not v.maschera_invio_aperta():
            log("maschera invio non aperta")
    """

    def __init__(self, porta, nome: str = '', logger=None):
        self.porta = porta
        self.nome  = nome
        self._log  = logger

    def _abilitata(self) -> bool:
        return getattr(config, 'VERIFICA_UI_ABILITATA', True)

    def _log_msg(self, msg: str):
        if self._log:
            self._log(self.nome, f"[VERIFICA] {msg}")

    def _screen(self, cv_img=None):
        """
        Ritorna cv_img pronto per il matching.
        Se cv_img è già fornito lo usa direttamente (zero screenshot).
        Altrimenti scatta uno screenshot in-memoria via pipeline v5.24.
        Fallback su adb.screenshot() se exec-out fallisce.
        Ritorna None in caso di errore.
        """
        if cv_img is not None:
            return cv_img
        import adb
        png_bytes = adb.screenshot_bytes(self.porta)
        if png_bytes:
            _, cv = adb.decodifica_screenshot(png_bytes)
            if cv is not None:
                return cv
        # Fallback su file
        path = adb.screenshot(self.porta)
        if path:
            img = cv2.imread(path)
            if img is not None:
                return img
        self._log_msg("screenshot fallito")
        return None

    def _check(self, cv_img, template: str, roi: tuple,
               soglia: float, descrizione: str,
               default: bool = True) -> bool:
        """Esegue il match e logga il risultato. Fail-safe: ritorna default su errore."""
        if not self._abilitata():
            return True

        img = self._screen(cv_img)
        if img is None:
            return default

        score = _match_mem(img, template, roi)
        if score < 0:
            self._log_msg(f"{descrizione}: template '{template}' non disponibile — skip")
            return default

        ok = score >= soglia
        if not ok:
            self._log_msg(
                f"{descrizione}: score={score:.3f} < soglia={soglia} → NON trovato"
            )
        return ok

    # --------------------------------------------------------------------------
    # 1. Tipo nodo selezionato (alone dorato nel pannello lente)
    #    Chiama dopo tap tipo x2 in _cerca_nodo()
    # --------------------------------------------------------------------------
    _ROI_LENTE   = (350, 460, 870, 540)
    _SOGLIA_TIPI = 0.85
    _TIPO_TMPL   = {
        "campo":    "pin_field.png",
        "segheria": "pin_sawmill.png",
        "acciaio":  "pin_steel_mill.png",
        "petrolio": "pin_oil_refinery.png",
    }

    def tipo_selezionato(self, tipo: str, cv_img=None) -> bool:
        """Verifica che l'icona tipo sia evidenziata nel pannello lente."""
        tmpl = self._TIPO_TMPL.get(tipo)
        if not tmpl:
            return True   # tipo sconosciuto — fail-safe
        return self._check(cv_img, tmpl, self._ROI_LENTE,
                           self._SOGLIA_TIPI, f"tipo '{tipo}' selezionato")

    # --------------------------------------------------------------------------
    # 2. Popup nodo — pulsante GATHER visibile
    #    Chiama dopo tap sul nodo in _tap_invia_squadra()
    # --------------------------------------------------------------------------
    _ROI_GATHER  = (60, 350, 420, 420)

    def gather_visibile(self, cv_img=None) -> bool:
        """Verifica che il pulsante GATHER sia visibile nel popup nodo."""
        return self._check(cv_img, "pin_gather.png", self._ROI_GATHER,
                           0.80, "GATHER visibile")

    # --------------------------------------------------------------------------
    # 3. Maschera invio squadra — stato pulsanti in basso
    #    Chiama dopo tap GATHER e selezione squadra in _esegui_marcia()
    # --------------------------------------------------------------------------
    _ROI_MASCHERA = (400, 460, 870, 540)

    def march_visibile(self, cv_img=None) -> bool:
        """MARCH visibile → squadra configurata, pronta a marciare."""
        return self._check(cv_img, "pin_march.png", self._ROI_MASCHERA,
                           0.80, "MARCH visibile")

    def clear_visibile(self, cv_img=None) -> bool:
        """CLEAR visibile → squadra configurata (con MARCH)."""
        return self._check(cv_img, "pin_clear.png", self._ROI_MASCHERA,
                           0.75, "CLEAR visibile")

    def max_visibile(self, cv_img=None) -> bool:
        """MAX visibile → truppe non ancora assegnate."""
        return self._check(cv_img, "pin_max.png", self._ROI_MASCHERA,
                           0.75, "MAX visibile")

    def no_squads_visibile(self, cv_img=None) -> bool:
        """NO SQUADS visibile → nessuna squadra formata."""
        return self._check(cv_img, "pin_no_squads.png", self._ROI_MASCHERA,
                           0.80, "NO SQUADS visibile")

    def create_squad_visibile(self, cv_img=None) -> bool:
        """CREATE SQUAD visibile → nessuna squadra esistente."""
        return self._check(cv_img, "pin_create_squad.png", (600, 150, 870, 230),
                           0.80, "CREATE SQUAD visibile")

    def maschera_invio_aperta(self, cv_img=None) -> bool:
        """
        Verifica che la maschera invio sia aperta in qualsiasi stato.
        Scatta uno screenshot unico e lo riusa per tutti i check.
        Ritorna True se almeno uno dei pulsanti attesi è visibile.
        """
        if not self._abilitata():
            return True

        img = self._screen(cv_img)
        if img is None:
            return True   # fail-safe

        for fn in (self.march_visibile, self.clear_visibile,
                   self.max_visibile, self.no_squads_visibile,
                   self.create_squad_visibile):
            if fn(img):
                return True

        self._log_msg("maschera invio NON aperta (nessun pulsante trovato)")
        return False

    def maschera_invio_ancora_aperta(self, cv_img=None) -> bool:
        """
        Come maschera_invio_aperta ma SENZA logging dei singoli check.
        Usato nel POST-MARCIA dove la maschera chiusa è il comportamento atteso.
        Ritorna True solo se la maschera è ancora aperta (= problema).
        """
        if not self._abilitata():
            return False  # fail-safe inverso

        img = self._screen(cv_img)
        if img is None:
            return False

        for template, roi, soglia in (
            ("pin_march.png",        self._ROI_MASCHERA,    0.80),
            ("pin_clear.png",        self._ROI_MASCHERA,    0.75),
            ("pin_max.png",          self._ROI_MASCHERA,    0.75),
            ("pin_no_squads.png",    self._ROI_MASCHERA,    0.80),
            ("pin_create_squad.png", (600, 150, 870, 230),  0.80),
        ):
            score = _match_mem(img, template, roi)
            if score >= soglia:
                return True  # maschera ancora aperta
        return False  # maschera chiusa — comportamento atteso

    # --------------------------------------------------------------------------
    # 4. Popup coordinate aperto — header "Enter coordinates" visibile
    # --------------------------------------------------------------------------
    _ROI_COORD = (300, 85, 700, 125)

    def enter_coordinates_visibile(self, cv_img=None) -> bool:
        """Verifica che il popup 'Enter coordinates' sia aperto."""
        return self._check(cv_img, "pin_enter.png", self._ROI_COORD,
                           0.75, "Enter coordinates visibile")

    # --------------------------------------------------------------------------
    # 5. Lente di ricerca visibile in mappa
    # --------------------------------------------------------------------------
    _ROI_LENTE_ICONA = (0, 305, 80, 370)

    def lente_visibile(self, cv_img=None) -> bool:
        """Verifica che l'icona lente di ricerca sia visibile in mappa."""
        return self._check(cv_img, "pin_lente.png", self._ROI_LENTE_ICONA,
                           0.80, "lente ricerca visibile")

    # --------------------------------------------------------------------------
    # Utility: tap con verifica post-tap e retry automatico
    # --------------------------------------------------------------------------
    def tap_e_verifica(self, coord: tuple, fn_check,
                       descrizione: str, attesa_s: float = 1.0,
                       max_retry: int = 2) -> bool:
        """
        Tap su coord → attesa → verifica con fn_check().
        Se fallisce, ritappa e riverifica fino a max_retry volte.
        """
        import adb
        import time

        for i in range(max_retry):
            if i > 0:
                self._log_msg(f"'{descrizione}': retry {i}/{max_retry-1}")
                adb.tap(self.porta, coord)
            time.sleep(attesa_s)
            img = self._screen()
            if fn_check(img):
                return True
            if i == 0:
                adb.tap(self.porta, coord)

        self._log_msg(f"'{descrizione}': fallito dopo {max_retry} tentativi")
        return False
