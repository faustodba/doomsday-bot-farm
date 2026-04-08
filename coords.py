# ==============================================================================
#  DOOMSDAY BOT V5 - coords.py
#  Coordinate UI per-istanza — unica fonte di verità
#
#  UTILIZZO:
#    from coords import UICoords
#    coords = UICoords.da_ist(ist)   # costruisci dall'elemento ISTANZE/ISTANZE_MUMU
#    adb.tap(porta, coords.alleanza)
#    tap_icona, tap_cerca = coords.per_tipo("campo")
#
#  PRINCIPIO:
#    - Tutte le coordinate dipendenti dal layout vengono risolte qui al momento
#      della costruzione, in base al campo layout_barra dell'istanza.
#    - Le coordinate indipendenti dal layout vengono lette direttamente da config.
#    - Nessun altro modulo (raccolta, rifornimento, alleanza, messaggi) deve
#      hardcodare coordinate o leggere config.COORD_* direttamente.
#
#  LAYOUT:
#    1 = barra standard 5 icone (Campagna / Zaino / Alleanza / Bestia / Eroe)
#    2 = barra compatta 4 icone (Campagna / Zaino / Alleanza / Eroe) — no Bestia
# ==============================================================================

from dataclasses import dataclass, field
from typing import Tuple, Dict
import config

Coord = Tuple[int, int]


@dataclass(frozen=True)
class UICoords:
    """
    Coordinate UI risolte per una specifica istanza.
    Immutabile (frozen=True) — creata una volta per ciclo, passata in giro.
    """

    # --- Barra inferiore (layout-dipendente) ---
    alleanza:     Coord   # pulsante Alleanza in home/mappa
    tap_campaign: Coord   # pulsante Campaign in home/mappa (layout-dipendente)

    # --- Mappa: ricerca nodi ---
    lente:               Coord
    lente_coord:         Coord
    tap_campo:           Coord
    tap_segheria:        Coord
    tap_acciaieria:      Coord
    tap_raffineria:      Coord
    cerca_campo:         Coord
    cerca_segheria:      Coord
    cerca_acciaieria:    Coord
    cerca_raffineria:    Coord
    nodo:                Coord

    # --- Maschera raccolta ---
    raccogli:    Coord
    squadra:     Coord
    marcia:      Coord
    cancella:    Coord
    campo_testo: Coord
    ok_tastiera: Coord
    livello_piu: Coord
    livello_meno: Coord

    # --- Toggle home/mappa ---
    toggle_home_mappa: Coord

    # --- Messaggi ---
    msg_icona:        Coord
    msg_tab_alleanza: Coord
    msg_tab_sistema:  Coord
    msg_leggi:        Coord

    # --- Mappa tipo nodo → (tap_icona, tap_cerca) ---
    _mappa_tipo: Dict[str, Tuple[Coord, Coord]] = field(repr=False)

    # --- Lingua istanza e template pulsanti lingua-dipendenti ---
    lingua:                    str   # "it" | "en"
    btn_rifornimento_template: str   # path template pulsante rifornimento
    btn_claim_free_template:   str   # path template pulsante CLAIM free VIP

    # --- Task periodici home ---
    tap_radar_icona: Coord   # icona Radar Station in home

    # ------------------------------------------------------------------
    # Factory — unico punto di costruzione
    # ------------------------------------------------------------------
    @classmethod
    def da_ist(cls, ist: dict) -> "UICoords":
        """
        Costruisce UICoords dall'elemento ISTANZE/ISTANZE_MUMU (dizionario).
        ist: {"nome": ..., "interno"/"indice": ..., "porta": ..., "layout": ..., ...}
        """
        alleanza    = config.get_coord_alleanza(ist)
        tap_campaign = config.get_coord_campaign(ist)

        tap_campo        = config.TAP_CAMPO
        tap_segheria     = config.TAP_SEGHERIA
        tap_acciaieria   = config.TAP_ACCIAIERIA
        tap_raffineria   = config.TAP_RAFFINERIA
        cerca_campo      = config.TAP_CERCA_CAMPO
        cerca_segheria   = config.TAP_CERCA_SEGHERIA
        cerca_acciaieria = config.TAP_CERCA_ACCIAIERIA
        cerca_raffineria = config.TAP_CERCA_RAFFINERIA

        mappa_tipo = {
            "campo":    (tap_campo,      cerca_campo),
            "segheria": (tap_segheria,   cerca_segheria),
            "acciaio":  (tap_acciaieria, cerca_acciaieria),
            "petrolio": (tap_raffineria, cerca_raffineria),
        }

        return cls(
            alleanza          = alleanza,
            tap_campaign      = tap_campaign,
            lente             = config.TAP_LENTE,
            lente_coord       = config.TAP_LENTE_COORD,
            tap_campo         = tap_campo,
            tap_segheria      = tap_segheria,
            tap_acciaieria    = tap_acciaieria,
            tap_raffineria    = tap_raffineria,
            cerca_campo       = cerca_campo,
            cerca_segheria    = cerca_segheria,
            cerca_acciaieria  = cerca_acciaieria,
            cerca_raffineria  = cerca_raffineria,
            nodo              = config.TAP_NODO,
            raccogli          = config.TAP_RACCOGLI,
            squadra           = config.TAP_SQUADRA,
            marcia            = config.TAP_MARCIA,
            cancella          = config.TAP_CANCELLA,
            campo_testo       = config.TAP_CAMPO_TESTO,
            ok_tastiera       = config.TAP_OK_TASTIERA,
            livello_piu       = config.TAP_LIVELLO_PIU,
            livello_meno      = config.TAP_LIVELLO_MENO,
            toggle_home_mappa = config.TAP_TOGGLE_HOME_MAPPA,
            msg_icona         = (config.MSG_ICONA_X,        config.MSG_ICONA_Y),
            msg_tab_alleanza  = (config.MSG_TAB_ALLEANZA_X, config.MSG_TAB_ALLEANZA_Y),
            msg_tab_sistema   = (config.MSG_TAB_SISTEMA_X,  config.MSG_TAB_SISTEMA_Y),
            msg_leggi         = (config.MSG_LEGGI_X,        config.MSG_LEGGI_Y),
            _mappa_tipo       = mappa_tipo,
            lingua            = config.get_lingua(ist),
            btn_rifornimento_template = config.get_btn_rifornimento_template(ist),
            btn_claim_free_template   = config.get_btn_claim_free_template(ist),
            tap_radar_icona           = config.TAP_RADAR_ICONA,
        )

    def per_tipo(self, tipo: str) -> Tuple[Coord, Coord]:
        """
        Ritorna (tap_icona, tap_cerca) per il tipo di nodo dato.
        Fallback a campo se tipo non riconosciuto.
        """
        return self._mappa_tipo.get(tipo, self._mappa_tipo["campo"])
