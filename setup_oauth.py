#!/usr/bin/env python3
"""
Autoriza Google una vez y guarda el token en credentials/token.json.

Uso:
    python3 setup_oauth.py --start          # imprime la URL y espera el codigo
    python3 setup_oauth.py --code <CODE>    # (opcional) canjea un codigo a mano
    python3 setup_oauth.py --status         # estado del token
    python3 setup_oauth.py --reset          # borra el token guardado

El flujo normal es --start: imprime un enlace, tú lo abres en el navegador de tu
ordenador, autorizas, Google redirige a http://localhost:<puerto>, y un hilo
local recoge el codigo. No hay que copiar ni pegar nada.

El puerto de escucha (8765) debe coincidir con el redirect_uri registrado en el
cliente OAuth de tipo 'Desktop app' de Google Cloud.
"""

import argparse
import http.server
import sys
import threading
import urllib.parse
import webbrowser

import gauth

CALLBACK_PORT = 8765
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}"

# OAuth 'redirect error' de Google (por ejemplo, si el usuario cierra la ventana).
ALLOWED_ERRORS = {"access_denied", "consent_required", "invalid_scope"}


def _serve_once(state: str, got: dict) -> None:
    """Servidor local que captura el codigo de autorizacion. Un solo request."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (nombre impuesto por la stdlib)
            qs = urllib.parse.urlparse(self.path).query
            params = dict(urllib.parse.parse_qsl(qs))

            if params.get("state") != state:
                self._reply(400, "State incorrecto. Vuelve a intentarlo desde la terminal.",
                            "Se ha recibido una peticion con un 'state' que no coincide. Cierra esta pestana.")
                return

            if params.get("error"):
                err = params["error"]
                got["error"] = err
                self._reply(400, f"Google devolvio un error: {err}",
                            f"Google devolvio un error: {err}")
                return

            if not params.get("code"):
                self._reply(400, "No llego ningun codigo.", "No llego ningun codigo. Vuelve a intentarlo.")
                return

            got["code"] = params["code"]
            self._reply(
                200,
                "Autorizacion completada. Puedes cerrar esta pestana y volver a la terminal.",
                "<h2>Listo</h2><p>Google ya autorizo a Hermes. Cierra esta pestana.</p>",
            )

        def _reply(self, code: int, log_msg: str, html: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<meta charset='utf-8'><p>{html}</p>".encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *a):  # silencia el log de http.server
            pass

    srv = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def do_start() -> int:
    try:
        client = gauth.load_client()
    except gauth.AuthError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("\nPasos para conseguir client_secret.json:", file=sys.stderr)
        print("  1. console.cloud.google.com -> crea o elige un proyecto", file=sys.stderr)
        print("  2. APIs y servicios -> Biblioteca -> activa: Gmail API, Google Calendar API, Google Drive API",
              file=sys.stderr)
        print("  3. APIs y servicios -> Pantalla de consentimiento OAuth -> usuario externo, y PUBLISH en "
              "produccion (si lo dejas en 'Pruebas' el token caduca a los 7 dias)", file=sys.stderr)
        print("  4. APIs y servicios -> Credenciales -> Crear credenciales -> ID de cliente OAuth -> "
              "Aplicacion de escritorio", file=sys.stderr)
        print(f"  5. Copia el JSON a {gauth.CLIENT_PATH} y dale chmod 600", file=sys.stderr)
        return 1

    verifier, challenge = gauth.pkce_pair()
    import secrets as _s

    state = _s.token_urlsafe(24)
    url = gauth.build_auth_url(client, REDIRECT_URI, state, challenge)

    got: dict = {}
    srv = _serve_once(state, got)

    print("Abre este enlace en el navegador de tu ORDENADOR (no en la Raspberry):\n")
    print(url)
    print("\n(Robot tambien acepta localhost:" + str(CALLBACK_PORT) + ", pero para un 'Desktop app' basta localhost)")
    print("\nEsperando la autorizacion... (Ctrl+C para cancelar)\n")

    try:
        while not got:
            threading.Event().wait(0.3)
    except KeyboardInterrupt:
        print("\nCancelado.")
        srv.shutdown()
        return 1
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass

    if got.get("error"):
        if got["error"] in ALLOWED_ERRORS:
            print(f"Autorizacion cancelada ({got['error']}). No se guardo nada.")
            return 1
        print(f"Error de Google: {got['error']}")
        return 1

    try:
        data = gauth.exchange_code(client, got["code"], REDIRECT_URI, verifier)
    except gauth.AuthError as e:
        print(f"ERROR al canjear el codigo: {e}")
        return 1

    gauth.save_token(data)
    print("Token guardado correctamente.")
    print(f"  scopes: {data.get('scope', '')}")
    print(f"  archivo: {gauth.TOKEN_PATH} (600)")
    return 0


def do_code(code: str) -> int:
    """Canje manual, por si el navegador no puede alcanzar localhost de la Pi."""
    try:
        client = gauth.load_client()
    except gauth.AuthError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    verifier, _ = gauth.pkce_pair()
    print("El canje manual necesita el 'code_verifier' de la sesion PKCE original,")
    print("que solo existe en la maquina que genero la URL. Usa --start.", file=sys.stderr)
    return 1


def do_status() -> int:
    st = gauth.token_status()
    if not st["configured"]:
        print("No hay token. Ejecuta: python3 setup_oauth.py --start")
        return 1
    mins = st["expires_in_s"] / 60
    print(f"Token OK. Caduca en {mins:.0f} min (se refresca solo).")
    print("Scopes:")
    for s in st["scopes"]:
        print(f"  - {s}")
    return 0


def do_reset() -> int:
    if gauth.TOKEN_PATH.exists():
        gauth.TOKEN_PATH.unlink()
        print("Token borrado.")
    else:
        print("No habia token.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--start", action="store_true", help="imprime la URL y espera")
    g.add_argument("--code", help="canje manual (no soportado: usa --start)")
    g.add_argument("--status", action="store_true")
    g.add_argument("--reset", action="store_true")
    a = ap.parse_args()

    if a.start:
        sys.exit(do_start())
    if a.code:
        sys.exit(do_code(a.code))
    if a.status:
        sys.exit(do_status())
    sys.exit(do_reset())
