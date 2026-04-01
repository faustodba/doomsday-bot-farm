# ============================================================================== 
# DOOMSDAY BOT V5 - dashboard_server.py (profilo + robustezza) 
# ============================================================================== 
import http.server
import threading
import os
import json
import time

PORT = 8080
LOG_TAIL_LINES = 300

# --- Validazione/merge runtime.json (robustezza) ---
def _clamp_int(v, default=0, vmin=None, vmax=None):
    try:
        iv = int(v)
    except Exception:
        iv = int(default)
    if vmin is not None and iv < vmin:
        iv = vmin
    if vmax is not None and iv > vmax:
        iv = vmax
    return iv


def _merge_runtime(existing, incoming):
    """Merge conservativo: preserva chiavi non presenti nell'incoming."""
    out = dict(existing or {})
    out.setdefault('globali', {})
    out.setdefault('overrides', {})
    out['overrides'].setdefault('bs', {})
    out['overrides'].setdefault('mumu', {})

    inc_g = (incoming or {}).get('globali', {}) or {}
    inc_o = (incoming or {}).get('overrides', {}) or {}

    out['globali'].update(inc_g)

    if isinstance(inc_o, dict) and ('bs' in inc_o or 'mumu' in inc_o):
        if isinstance(inc_o.get('bs'), dict):
            out['overrides']['bs'].update(inc_o.get('bs'))
        if isinstance(inc_o.get('mumu'), dict):
            out['overrides']['mumu'].update(inc_o.get('mumu'))
    elif isinstance(inc_o, dict):
        out['overrides']['bs'].update(inc_o)
        out['overrides']['mumu'].update(inc_o)

    g = out.get('globali', {})
    if 'RIFORNIMENTO_MAX_SPEDIZIONI_CICLO' in g:
        g['RIFORNIMENTO_MAX_SPEDIZIONI_CICLO'] = _clamp_int(g['RIFORNIMENTO_MAX_SPEDIZIONI_CICLO'], default=5, vmin=0, vmax=50)

    return out


def _importa_modulo(nome, cartella):
    import sys
    import importlib.util
    if nome not in sys.modules:
        spec = importlib.util.spec_from_file_location(nome, os.path.join(cartella, f"{nome}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[nome] = mod
    return sys.modules[nome]


def _safe_write(wfile, data: bytes):
    try:
        wfile.write(data)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _run():
    cartella = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cartella)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("ngrok-skip-browser-warning", "true")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/config_istanze.json"):
                return self._serve_config_istanze()
            if self.path.startswith("/log"):
                return self._serve_log()
            if self.path.startswith("/ping"):
                return self._json_ok({"ok": True, "ts": time.time(), "version": "profilo-fix"})
            if self.path.startswith("/robots.txt"):
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                _safe_write(self.wfile, body)
                return
            try:
                super().do_GET()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _serve_log(self):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                n = int(qs.get("n", [LOG_TAIL_LINES])[0])
                since = qs.get("since", [None])[0]
                filtro = qs.get("filter", [None])[0]

                log_path = os.path.join(cartella, "bot.log")
                if not os.path.exists(log_path):
                    return self._json_ok({"righe": [], "totale": 0})

                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    righe = f.readlines()

                if filtro:
                    righe = [r for r in righe if filtro in r]

                if since:
                    def _ts(riga):
                        try:
                            return riga[1:9]
                        except Exception:
                            return ""
                    righe = [r for r in righe if _ts(r) >= since]

                righe = righe[-n:]
                return self._json_ok({"righe": [r.rstrip("\n") for r in righe], "totale": len(righe), "ts": time.time()})
            except Exception as e:
                return self._json_err(str(e))

        def _serve_config_istanze(self):
            try:
                cfg = _importa_modulo("config", cartella)

                # FIX: leggi overrides da runtime.json e applicali ai valori config.py.
                # Senza questo, la dashboard calcola il delta rispetto ai valori "nudi"
                # di config.py, ignorando gli overrides già attivi — causando la
                # cancellazione dell'override quando il valore UI coincide con config.py.
                rt_path = os.path.join(cartella, "runtime.json")
                try:
                    with open(rt_path, "r", encoding="utf-8") as f:
                        rt = json.load(f)
                except Exception:
                    rt = {}
                ovr_bs   = rt.get("overrides", {}).get("bs",   {})
                ovr_mumu = rt.get("overrides", {}).get("mumu", {})

                def _bs(ist):
                    nome = ist.get("nome", "")
                    ovr  = ovr_bs.get(nome, {})
                    return {
                        "nome": nome,
                        "interno": ist.get("interno", ""),
                        "porta": ist.get("porta", ""),
                        "truppe":      ovr.get("truppe",      ist.get("truppe",      12000)),
                        "max_squadre": ovr.get("max_squadre", ist.get("max_squadre", 4)),
                        "layout":      ovr.get("layout",      ist.get("layout",      1)),
                        "lingua":      ovr.get("lingua",      ist.get("lingua",      "it")),
                        "abilitata":   ovr.get("abilitata",   ist.get("abilitata",   True)),
                        "livello":     ovr.get("livello",     ist.get("livello",     6)),
                        "profilo":     ovr.get("profilo",     ist.get("profilo",     "full")),
                        "fascia_oraria": ovr.get("fascia_oraria", ist.get("fascia_oraria", "")),
                    }

                def _mumu(ist):
                    nome = ist.get("nome", "")
                    ovr  = ovr_mumu.get(nome, {})
                    return {
                        "nome": nome,
                        "indice": ist.get("indice", ""),
                        "porta": ist.get("porta", 16384),
                        "truppe":      ovr.get("truppe",      ist.get("truppe",      12000)),
                        "max_squadre": ovr.get("max_squadre", ist.get("max_squadre", 4)),
                        "layout":      ovr.get("layout",      ist.get("layout",      1)),
                        "lingua":      ovr.get("lingua",      ist.get("lingua",      "en")),
                        "abilitata":   ovr.get("abilitata",   ist.get("abilitata",   True)),
                        "livello":     ovr.get("livello",     ist.get("livello",     6)),
                        "profilo":     ovr.get("profilo",     ist.get("profilo",     "full")),
                        "fascia_oraria": ovr.get("fascia_oraria", ist.get("fascia_oraria", "")),
                    }

                payload = {
                    "istanze_bs":   [_bs(i)   for i in getattr(cfg, "ISTANZE",      [])],
                    "istanze_mumu": [_mumu(i) for i in getattr(cfg, "ISTANZE_MUMU", [])],
                }
                return self._json_ok(payload)
            except Exception as e:
                return self._json_err(str(e))

        def do_POST(self):
            if not self.path.startswith("/runtime.json"):
                self.send_response(404)
                self.end_headers()
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                dati = json.loads(body.decode("utf-8"))

                path_json = os.path.join(cartella, "runtime.json")

                try:
                    if os.path.exists(path_json):
                        with open(path_json, "r", encoding="utf-8") as fr:
                            esistente = json.load(fr)
                    else:
                        esistente = {}
                except Exception:
                    esistente = {}

                dati = _merge_runtime(esistente, dati)

                path_tmp = path_json + ".tmp"
                with open(path_tmp, "w", encoding="utf-8") as f:
                    json.dump(dati, f, ensure_ascii=False, indent=2)
                os.replace(path_tmp, path_json)

                return self._json_ok({"ok": True})
            except Exception as e:
                return self._json_err(str(e))

        def _json_ok(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

        def _json_err(self, msg, status=500):
            body = json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[dashboard] Server avviato → http://localhost:{PORT}/dashboard.html")
    server.serve_forever()


def avvia():
    t = threading.Thread(target=_run, daemon=True)
    t.start()


if __name__ == "__main__":
    _run()
