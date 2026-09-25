"""
OAuth 2.0 para Google (authorization code + PKCE), solo librerias estandar.

Guarda el token en credentials/token.json con permisos 600 y lo refresca solo.
No imprime jamas el client_secret ni el refresh_token.
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRED_DIR = HERE / "credentials"
TOKEN_PATH = CRED_DIR / "token.json"
CLIENT_PATH = CRED_DIR / "client_secret.json"

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Scopes minimos: Gmail lectura+redaccion+envio, Calendar lectura+escritura,
# Drive SOLO lectura. Ampliar drive a escritura es deliberado, no un olvido:
# escribir en Drive es la accion mas destructiva de todo este servidor.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]

SCOPE_STR = " ".join(SCOPES)


class AuthError(RuntimeError):
    pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair():
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def load_client() -> dict:
    """Lee client_secret.json en formato 'installed' o 'web'."""
    if not CLIENT_PATH.exists():
        raise AuthError(
            f"Falta {CLIENT_PATH}. Descarga el client_secret.json de Google Cloud "
            "y copialo ahi (chmod 600)."
        )
    data = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
    section = data.get("installed") or data.get("web")
    if not section:
        raise AuthError("client_secret.json no tiene seccion 'installed' ni 'web'.")
    for field in ("client_id", "client_secret"):
        if not section.get(field):
            raise AuthError(f"client_secret.json sin '{field}'.")
    return section


def build_auth_url(client: dict, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE_STR,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return AUTH_URI + "?" + urllib.parse.urlencode(params)


def _post_token(payload: dict) -> dict:
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        TOKEN_URI,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        try:
            detail = json.loads(detail).get("error_description", detail)
        except Exception:
            pass
        raise AuthError(f"Google rechazo el token: {detail}") from e
    except urllib.error.URLError as e:
        raise AuthError(f"No se pudo contactar con Google: {e.reason}") from e


def exchange_code(client: dict, code: str, redirect_uri: str, verifier: str) -> dict:
    data = _post_token(
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    )
    if "refresh_token" not in data:
        raise AuthError(
            "Google no devolvio refresh_token. Suele pasar si la cuenta ya habia "
            "autorizado antes: revoca el acceso en "
            "https://myaccount.google.com/permissions y repite."
        )
    return data


def save_token(data: dict) -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(time.time()) + int(data.get("expires_in", 3600)),
        "scope": data.get("scope", SCOPE_STR),
        "token_uri": TOKEN_URI,
        "client_id": data.get("client_id", ""),
    }
    TOKEN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)
    try:
        CRED_DIR.chmod(0o700)
    except OSError:
        pass


def has_token() -> bool:
    return TOKEN_PATH.exists()


def token_status() -> dict:
    if not TOKEN_PATH.exists():
        return {"configured": False}
    data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    return {
        "configured": True,
        "expires_in_s": int(data.get("expires_at", 0)) - int(time.time()),
        "scopes": data.get("scope", "").split(),
    }


def access_token() -> str:
    """Devuelve un access_token válido, refrescando si hace falta."""
    if not TOKEN_PATH.exists():
        raise AuthError(
            "Google no esta autorizado. Ejecuta: python3 setup_oauth.py "
            "y sigue las instrucciones."
        )
    data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))

    if data.get("expires_at", 0) - int(time.time()) > 90:
        return data["access_token"]

    if not data.get("refresh_token"):
        raise AuthError("El token guardado no tiene refresh_token. Reautoriza.")

    client = load_client()
    fresh = _post_token(
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "refresh_token": data["refresh_token"],
            "grant_type": "refresh_token",
        }
    )
    # Google puede no devolver refresh_token al refrescar: se conserva el viejo.
    fresh.setdefault("refresh_token", data["refresh_token"])
    save_token(fresh)
    return fresh["access_token"]


def api_get(url: str, params=None) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + access_token()})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # access_token caducado por surprise: fuerza refresco y reintenta una vez
            data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
            data["expires_at"] = 0
            TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return api_get(url.split("?")[0], params)
        raise AuthError(f"API {e.code}: {e.read().decode()[:300]}") from e


def api_post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + access_token(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise AuthError(f"API {e.code}: {e.read().decode()[:300]}") from e
