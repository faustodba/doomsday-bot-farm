# ==============================================================================
#  PATCH main.py — blacklist nodi condivisa tra thread
#
#  1. Aggiungi dopo gli import esistenti:
# ==============================================================================

import threading

# Blacklist nodi condivisa tra tutte le istanze parallele
# chiave: "X_Y"  (es. "712_535")
# valore: timestamp Unix di prenotazione
_blacklist_nodi      = {}
_blacklist_nodi_lock = threading.Lock()

# ==============================================================================
#  2. Nella funzione che lancia ogni istanza (es. _esegui_istanza o simile),
#     aggiungi blacklist e blacklist_lock alla chiamata raccolta_istanza:
#
#  PRIMA:
#     raccolta.raccolta_istanza(porta, nome, truppe=..., max_squadre=...,
#                               logger=..., ciclo=ciclo)
#
#  DOPO:
#     raccolta.raccolta_istanza(porta, nome, truppe=..., max_squadre=...,
#                               logger=..., ciclo=ciclo,
#                               blacklist=_blacklist_nodi,
#                               blacklist_lock=_blacklist_nodi_lock)
# ==============================================================================