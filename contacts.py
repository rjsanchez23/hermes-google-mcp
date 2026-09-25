"""
Directorio de contactos local.

Sirve para que el agente no tenga que acordarse de un email: escribe "Eli" en el
campo attendees y el servidor lo resuelve a la direccion antes de llamar a Google.

Motivo: el agente NO resolvia nombres a emails y pedia el email cada vez, o peor,
se lo inventaba. Resolve aqui, en codigo, no en la skill, porque tres versiones
de skill ya demostraron que escrito no es candado.
"""

import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CONTACTS_PATH = HERE / "contacts.json"

# Acepta "Eli", "eli", "ELI", "  Eli  " y tambien el email entero.
def _normaliza(s: str) -> str:
    return "".join(c for c in str(s).strip().lower() if c.isalnum() or c.isspace()).strip()


def cargar() -> dict:
    if not CONTACTS_PATH.exists():
        return {}
    try:
        raw = json.loads(CONTACTS_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items() if not str(k).startswith("_") and isinstance(v, str)}
    except Exception:
        return {}


def guardar(d: dict) -> None:
    payload = {
        "_nota": (
            "Directorio de contactos locales. El servidor resuelve 'Eli' -> email al crear "
            "eventos, para que el agente no tenga que acordarse. Editar a mano o con la "
            "herramienta contact_set."
        )
    }
    payload.update(d)
    tmp = CONTACTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONTACTS_PATH)
    os.chmod(CONTACTS_PATH, 0o600)


def es_email(s: str) -> bool:
    s = str(s).strip()
    return s.count("@") == 1 and not s.startswith("@") and not s.endswith("@") and "." in s.split("@")[1]


def resolver(txt: str) -> tuple:
    """Devuelve (email, como_se_resolvio).

    como_se_resolvio es 'email' si ya venia una direccion, 'contacto' si se
    busco en el directorio, o None si no se pudo resolver.
    """
    txt = str(txt or "").strip()
    if not txt:
        return None, None
    if es_email(txt):
        return txt, "email"

    contactos = cargar()
    clave = _normaliza(txt)
    for nombre, email in contactos.items():
        if _normaliza(nombre) == clave:
            return email, "contacto"

    # coincidencia parcial: "Eli" deberia encontrar "Eli" aunque haya espacios extra,
    # y "el" no deberia(find-and por subcadena es demasiado laxo para nombres cortos)
    for nombre, email in contactos.items():
        n = _normaliza(nombre)
        if len(clave) >= 3 and (n.startswith(clave) or clave.startswith(n)):
            return email, "contacto"

    return None, None


def resolver_lista(atts: str) -> tuple:
    """Convierte 'Eli, ana@mail.com' en ['javisemaga26@gmail.com', 'ana@mail.com'].
    Devuelve (emails, resueltos, sin_resolver)."""
    emails, resueltos, fallidos = [], [], []
    for parte in str(atts or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        email, como = resolver(parte)
        if email:
            emails.append(email)
            resueltos.append({"entrada": parte, "email": email, "via": como})
        else:
            fallidos.append(parte)
    return emails, resueltos, fallidos
