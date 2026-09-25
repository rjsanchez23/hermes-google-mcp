#!/usr/bin/env python3
"""
Servidor MCP (stdio) para Gmail, Calendar y Drive de Google.

Solo librerias estandar. Sin pip, sin node_modules.

Por que existe: los MCP oficiales de Google (gmailmcp/drivemcp/calendarmcp) estan
en Developer Preview, exigen entrar en un programa con formulario y no documentan
un flujo OAuth sin pantalla, que es justo el caso de una Raspberry Pi. Este
servidor usa las APIs de Google en general, que son gratuitas y sin limites
practicos, y expone herramientas con nombre fijo (importa: el modelo de la Pi es
pequeno y se pierde con menus dinamicos como el de Composio).

El token vive en credentials/token.json. El cliente MCP (Hermes) nunca ve OAuth.
"""

import datetime
import json
import os
import sys
import traceback

import contacts
import gauth
import confirm
import tools

CONTACT_TOOL = {
    "name": "contact_lookup",
    "description": "Mira un contacto guardado y devuelve su email. Úsalo cuando el usuario nombre a "
    "alguien para un evento o un correo: el agente no tiene que acordarse de los emails. "
    "Sin argumentos, lista todos los contactos conocidos.",
    "inputSchema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Nombre del contacto. Opcional."}},
    },
}

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "google-workspace", "version": "1.2.0"}

# Rastro de acciones. El agente ha dicho "ya está guardado" tres veces sin haber
# llamado a ninguna herramienta. Con este log, cualquier afirmación suya se
# puede contrastar contra la realidad: si no aparece aqui, no ocurrió.
AUDIT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.log")

# Herramientas que CAMBIAN algo en la cuenta del usuario. Se auditan siempre.
WRITE_TOOLS = {
    "gmail_send_email",
    "gmail_create_draft",
    "gmail_trash_email",
    "calendar_create_event",
    "calendar_delete_event",
    "drive_create_folder",
    "drive_write_file",
}


def audit(tool: str, args: dict, result, is_error: bool) -> str:
    """Una linea JSON por accion, en el servidor, que el agente no puede editar.
    Devuelve un codigo unico que el agente debe copiar en su respuesta."""
    rid = "no-auditado"
    entry = {
        "recibo": None,
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "tool": tool,
        "args": _redact(args),
        "ok": not is_error,
    }
    if isinstance(result, dict):
        for k in ("event_id", "html_link", "message_id", "draft_id", "thread_id", "status"):
            if k in result:
                entry["result_" + k] = result[k]
        if is_error:
            entry["error"] = str(result.get("error", ""))[:200]
    try:
        import hashlib

        semilla = entry["ts"] + tool + json.dumps(entry["args"], sort_keys=True)
        rid = hashlib.sha256(semilla.encode()).hexdigest()[:10]
        entry["recibo"] = rid
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(AUDIT_PATH, 0o600)
    except Exception as exc:  # el log nunca debe tumbar la herramienta
        print(f"[google-workspace] no se pudo auditar: {exc}", file=sys.stderr)
    return rid


def _redact(args: dict) -> dict:
    """No al bodies de correo en el log: pueden llevar datos personales."""
    safe = {}
    for k, v in (args or {}).items():
        if k in ("body", "description"):
            safe[k] = f"<{len(str(v))} chars, omitido>"
        else:
            safe[k] = v
    return safe

# --------------------------------------------------------------- catalogue
# Nombres fijos y explicitos. El agente no tiene que "descubrir" nada.
TOOL_DEFS = [
    CONTACT_TOOL,
    {
        "name": "gmail_list_labels",
        "description": "Lista las etiquetas del buzon con totales de mensajes y sin leer. Útil para orientarse antes de buscar.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "gmail_search",
        "description": "Busca correos con la sintaxis de Gmail. query es obligatorio. Ejemplos: 'is:unread', "
        "'from:banco after:2026/09/01', 'subject:factura has:attachment', 'in:INBOX is:starred'. "
        "Devuelve remitente, asunto, fecha y etiquetas (NO el cuerpo).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta con sintaxis de Gmail."},
                "max_results": {"type": "integer", "description": "Máximo de resultados (1-50). Por defecto 10."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_get_email",
        "description": "Lee un correo concreto por su id, incluido el cuerpo en texto plano. "
        "El mensaje_id se obtiene de gmail_search.",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string", "description": "Id del mensaje."}},
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_list_drafts",
        "description": "Lista los borradores sin enviar, con su texto.",
        "inputSchema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer", "description": "Máximo (1-50)."}},
        },
    },
    {
        "name": "gmail_create_draft",
        "description": "Crea un BORRADOR y NO envía. Úsalo por defecto para cualquier correo: el usuario "
        "Revisalo y envialo tu. La respuesta trae _confirmacion: copiala literal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Destinatario."},
                "subject": {"type": "string", "description": "Asunto."},
                "body": {"type": "string", "description": "Cuerpo del correo."},
                "cc": {"type": "string", "description": "CC opcional, separado por comas."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_send_email",
        "description": "ENVÍA un correo de verdad. Irreversible. "
        "Muestra destinatario, asunto y cuerpo, y pide confirmacion ANTES de llamar. "
        "La respuesta trae _confirmacion: copiala literal. Ante la duda, gmail_create_draft.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {"type": "string", "description": "CC opcional."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_trash_email",
        "description": "Mueve un correo a la papelera. Reversible 30 dias. "
        "La respuesta trae _confirmacion: copiala literal.",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    {
        "name": "calendar_list_events",
        "description": "Lista los eventos de los próximos días. Zona horaria Europe/Madrid.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Días a mirar hacia adelante (1-180). Por defecto 7."},
                "max_results": {"type": "integer", "description": "Máximo de eventos (1-250)."},
            },
        },
    },
    {
        "name": "calendar_find_free_slots",
        "description": "Calcula huecos libres dentro del horario laboral, saltándose lo ocupado. "
        "Útil para '¿cuándo tengo libre el jueves?'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Días a mirar (1-60). Por defecto 7."},
                "work_hours": {"type": "string", "description": "Horario laboral 'HH:MM-HH:MM'. Por defecto 09:00-18:00."},
            },
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Crea un evento en el calendario del usuario, EN HORA DE MADRID (Europe/Madrid). "
        "IMPORTANTE: start y end deben ser ISO 8601 y el offset debe ser el de Madrid en esa fecha: "
        "+02:00 entre marzo y octubre, +01:00 en invierno. El servidor RECHAZA cualquier otro offset "
        "con un mensaje que dice cuál corresponde. Si el usuario dice 'mañana a las 10', calcula la "
        "fecha y aplica el offset correcto; no uses utcnow() ni +00:00. "
        "MUESTRA al usuario titulo, fecha y hora ANTES de crearlo y pide confirmacion. "
        "Al ejecutarla, la respuesta trae _confirmacion: REENVIA ESE TEXTO TAL CUAL, "
        "sin reescribirlo ni resumirlo, porque lo ha generado el servidor con los datos reales.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Título del evento."},
                "start": {"type": "string", "description": "ISO 8601 con zona, p.ej. 2026-09-26T20:45:00+02:00"},
                "end": {"type": "string", "description": "ISO 8601 con zona, posterior a start."},
                "description": {"type": "string", "description": "Descripción opcional."},
                "location": {"type": "string", "description": "Lugar opcional."},
                "attendees": {"type": "string", "description": "Nombres o emails separados por comas. Los NOMBRES se resuelven solos con el directorio de contactos (p.ej. 'Eli'). Poner a alguien como invitado NO le manda ningun correo: queda pendiente hasta que lo acepta."},
                "repeat": {"type": "string", "description": "Opcional. Recurrencia en palabras: 'todos los lunes, miercoles y viernes', 'todos los dias', 'cada 2 semanas los martes', 'todos los lunes hasta 2026-12-31', '6 veces los lunes', 'L-M-X-V'. Crea UN solo evento que se repite, no uno por sesion. Si no se dice nada, no se repite."},
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": "Elimina un evento del calendario. Irreversible. Confirma antes. "
        "La respuesta trae _confirmacion: copiala literal.",
        "inputSchema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "drive_search_files",
        "description": "Busca archivos en Drive por nombre. Sin query lista los modificados recientemente. "
        "Solo lectura.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar dentro del nombre. Opcional."},
                "max_results": {"type": "integer", "description": "Máximo (1-100)."},
            },
        },
    },
    {
        "name": "drive_read_file",
        "description": "Lee el contenido de un archivo de Drive. Google Docs se exporta a texto y Google Sheets "
        "a valores. Solo lectura.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Id del archivo, de drive_search_files o drive_list_folder."},
                "max_chars": {"type": "integer", "description": "Máximo de caracteres a devolver."},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "drive_list_folder",
        "description": "Lista el contenido de una carpeta de Drive. Usa 'root' para la raíz. Solo lectura.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Id de carpeta. Por defecto 'root'."},
                "max_results": {"type": "integer", "description": "Máximo (1-200)."},
            },
        },
    },
    {
        "name": "drive_create_folder",
        "description": "Crea una carpeta en Drive. Si ya existe con ese nombre, la devuelve sin crear otra. Solo puede crear carpetas nuevas: no puede tocar las que ya tenias.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre de la carpeta."},
                "parent_id": {"type": "string", "description": "Carpeta donde crearla. Por defecto 'root' (tu Drive)."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "drive_write_file",
        "description": "Escribe un archivo de TEXTO en Drive. Si ya existe con ese nombre en esa carpeta, lo actualiza. No hay forma de borrar: el agente deja cosas, no las quita.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre del archivo con extension, p.ej. notas.md o datos.json. SIN carpetas dentro del nombre."},
                "content": {"type": "string", "description": "El texto a escribir. Es el contenido COMPLETO del archivo, no un parche: si actualizas, incluye todo."},
                "folder": {"type": "string", "description": "Carpeta de destino: un id, o un nombre (se crea si no existe). Por defecto 'Hermes'."},
                "description": {"type": "string", "description": "Descripcion opcional del archivo."},
            },
            "required": ["name", "content"],
        },
    },
]

def _lookup_contact(nombre: str) -> dict:
    email, via = contacts.resolver(nombre)
    if email:
        return {"nombre": nombre, "email": email, "resuelto_por": via}
    return {
        "nombre": nombre,
        "email": None,
        "error": "No hay ningun contacto con ese nombre.",
        "contactos_conocidos": list(contacts.cargar().keys()),
    }


DISPATCH = {
    "contact_lookup": lambda a: (
        {"contactos": contacts.cargar()}
        if not a.get("name")
        else _lookup_contact(a.get("name", ""))
    ),
    "gmail_list_labels": lambda a: tools.gmail_list_labels(),
    "gmail_search": lambda a: tools.gmail_search(a.get("query", ""), a.get("max_results", 10)),
    "gmail_get_email": lambda a: tools.gmail_get_email(a.get("message_id", "")),
    "gmail_list_drafts": lambda a: tools.gmail_list_drafts(a.get("max_results", 10)),
    "gmail_create_draft": lambda a: tools.gmail_create_draft(
        a.get("to", ""), a.get("subject", ""), a.get("body", ""), a.get("cc", "")
    ),
    "gmail_send_email": lambda a: tools.gmail_send_email(
        a.get("to", ""), a.get("subject", ""), a.get("body", ""), a.get("cc", "")
    ),
    "gmail_trash_email": lambda a: tools.gmail_trash_email(a.get("message_id", "")),
    "calendar_list_events": lambda a: tools.calendar_list_events(a.get("days", 7), a.get("max_results", 25)),
    "calendar_find_free_slots": lambda a: tools.calendar_find_free_slots(
        a.get("days", 7), work_hours=a.get("work_hours", "09:00-18:00")
    ),
    "calendar_create_event": lambda a: tools.calendar_create_event(
        a.get("summary", ""), a.get("start", ""), a.get("end", ""),
        a.get("description", ""), a.get("location", ""), a.get("attendees", ""),
    ),
    "calendar_delete_event": lambda a: tools.calendar_delete_event(a.get("event_id", "")),
    "drive_search_files": lambda a: tools.drive_search_files(a.get("query", ""), a.get("max_results", 20)),
    "drive_read_file": lambda a: tools.drive_read_file(a.get("file_id", ""), a.get("max_chars", 20000)),
    "drive_list_folder": lambda a: tools.drive_list_folder(a.get("folder_id", "root"), a.get("max_results", 30)),
    "drive_create_folder": lambda a: tools.drive_create_folder(
        a.get("name", ""), a.get("parent_id", "root")
    ),
    "drive_write_file": lambda a: tools.drive_write_file(
        a.get("name", ""), a.get("content", ""), a.get("folder", "Hermes"),
        a.get("description", "")
    ),
}


def log(msg: str) -> None:
    """ stderr, nunca stdout: stdout es el canal del protocolo MCP. """
    print(f"[google-workspace] {msg}", file=sys.stderr, flush=True)


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def ok(req_id, result):
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def err(req_id, code, message):
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def handle(req: dict) -> None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Gmail, Calendar y Drive del usuario (rjsemaga@gmail.com). "
                "Para escribir (enviar correo, crear evento, papelera) muéstrale antes al usuario "
                "qué vas a hacer y pide confirmación. Ante la duda, gmail_create_draft en vez de enviar. "
                "Las fechas del calendario van en Europe/Madrid con zona explícita (+02:00 en verano, "
                "+01:00 en invierno); calendar_create_event rechaza cualquier otro offset."
            ),
        })
        return

    if method in ("notifications/initialized", "notifications/cancelled"):
        return

    if method == "ping":
        ok(req_id, {})
        return

    if method == "tools/list":
        ok(req_id, {"tools": TOOL_DEFS})
        return

    if method == "tools/call":
        name = (req.get("params") or {}).get("name", "")
        args = (req.get("params") or {}).get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            err(req_id, -32602, f"Herramienta desconocida: {name}")
            return
        try:
            result = fn(args)
            if name in WRITE_TOOLS:
                rid = audit(name, args, result, False)
                if isinstance(result, dict):
                    result = dict(result)
                    result["_recibo"] = rid
                    # El texto lo escribe el servidor, no el modelo. El agente no
                    # puede inventar duraciones ni ubicaciones porque no redacta:
                    # solo copia este bloque. _confirmacion es la UNICA fuente de
                    # verdad sobre lo que se ha hecho.
                    oficial = confirm.redactar(name, result)
                    if oficial:
                        result["_confirmacion"] = oficial
            ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                "isError": False,
            })
        except gauth.AuthError as e:
            if name in WRITE_TOOLS:
                audit(name, args, {"error": str(e)}, True)
            ok(req_id, {
                "content": [{"type": "text", "text": f"Error de autorizacion de Google: {e}"}],
                "isError": True,
            })
        except ValueError as e:
            if name in WRITE_TOOLS:
                audit(name, args, {"error": str(e)}, True)
            ok(req_id, {
                "content": [{"type": "text", "text": f"Argumentos incorrectos: {e}"}],
                "isError": True,
            })
        except Exception as e:
            log(f"ERROR en {name}: {e}\n{traceback.format_exc()}")
            if name in WRITE_TOOLS:
                audit(name, args, {"error": f"{type(e).__name__}: {e}"}, True)
            ok(req_id, {
                "content": [{"type": "text", "text": f"Error ejecutando {name}: {type(e).__name__}: {e}"}],
                "isError": True,
            })
        return

    if req_id is not None:
        err(req_id, -32601, f"Metodo no soportado: {method}")


def main() -> None:
    log(f"arrancado (python {sys.version.split()[0]}); token configurado: {gauth.has_token()}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"JSON invalido: {e}")
            continue
        try:
            handle(req)
        except Exception as e:
            log(f"fallo no controlado: {e}\n{traceback.format_exc()}")
            if req.get("id") is not None:
                err(req["id"], -32603, str(e))


if __name__ == "__main__":
    main()
