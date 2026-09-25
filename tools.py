"""
Herramientas de Gmail, Calendar y Drive. Solo lectura en Drive a proposito.

Cada funcion devuelve un dict ya serializable. Ninguna imprime secretos.
Las de escritura piden confirmacion al usuario antes de ejecutarse: eso lo
decide el agente leyendo la descripcion de la herramienta, no este modulo.
"""

import base64
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import contacts
import gauth

# El usuario es de Espana: TODO el calendario va en hora de Madrid, sin excepcion.
# Madrid alterna +02:00 (verano) y +01:00 (invierno), asi que un offset fijo se
# romperia en enero. Se usa la zona real y se valida contra ella.
MADRID = ZoneInfo("Europe/Madrid")

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

BASE64_RE = re.compile(r"[^A-Za-z0-9+/=_-]")


# ---------------------------------------------------------------- Gmail


def gmail_list_labels() -> dict:
    # Sin includeAttributes=false, la respuesta trae atributos por etiqueta que
    # solo hacen ruido. Los contadores (messagesTotal/messagesUnread) los mete
    # labels.list cuando se piden con includeDetails via el recurso de etiqueta;
    # la lista plana no los trae, asi que se piden uno a uno solo si hacen falta.
    data = gauth.api_get(f"{GMAIL}/labels", params={"includeAttributes": "false"})
    out = []
    for l in data.get("labels", []):
        out.append(
            {
                "id": l["id"],
                "name": l["name"],
                "type": l.get("type"),
                "total": l.get("messagesTotal"),
                "unread": l.get("messagesUnread"),
            }
        )
    return {
        "labels": out,
        "nota": "total y unread vienen a null en la lista plana de Gmail; "
        "usa gmail_search con 'label:X' para contar de verdad.",
    }


def gmail_search(query: str, max_results: int = 10) -> dict:
    """Busca por sintaxis de Gmail: from:, subject:, has:attachment, is:unread,
    in:INBOX, after:2026/09/01, label:... Ver gmail-search-syntax.md."""
    query = (query or "").strip()
    if not query:
        raise ValueError("query vacio. Ejemplo: 'is:unread from:banco'")
    max_results = max(1, min(int(max_results), 50))

    listing = gauth.api_get(
        f"{GMAIL}/messages", params={"q": query, "maxResults": max_results}
    )
    ids = [m["id"] for m in listing.get("messages", [])]
    out = []
    for mid in ids:
        m = gauth.api_get(f"{GMAIL}/messages/{mid}", params={"format": "metadata"})
        out.append(_headers_to_dict(m))
    return {"query": query, "estimated_total": int(listing.get("resultSizeEstimate", 0)), "messages": out}


def gmail_get_email(message_id: str) -> dict:
    m = gauth.api_get(f"{GMAIL}/messages/{message_id}", params={"format": "full"})
    headers = _headers_to_dict(m)
    headers["body_preview"] = _extract_text(m)[:4000]
    return headers


def gmail_create_draft(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    """Crea un BORRADOR. No envia. El usuario revisa y envia desde Gmail."""
    if not to or "@" not in to:
        raise ValueError("'to' debe ser una direccion de email valida.")
    raw = _build_mime(to, subject, body, cc, bcc)
    d = gauth.api_post(
        f"{GMAIL}/drafts",
        {"message": {"raw": raw}},
    )
    return {
        "draft_id": d.get("id"),
        "status": "borrador creado, NO enviado",
        "para": to,
        "asunto": subject,
        "aviso": "Revisalo en Gmail y envialo tu. El agente no lo envio.",
    }


def gmail_send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    raw = _build_mime(to, subject, body, cc, bcc)
    d = gauth.api_post(f"{GMAIL}/messages/send", {"raw": raw})
    return {
        "message_id": d.get("id"),
        "thread_id": d.get("threadId"),
        "status": "ENVIADO",
        "para": to,
        "asunto": subject,
    }


def gmail_trash_email(message_id: str) -> dict:
    m = gauth.api_post(f"{GMAIL}/messages/{message_id}/trash", {})
    return {
        "message_id": message_id,
        "status": "movido a la papelera",
        "reversible": True,
        "nota": "Recuperable con POST /messages/{id}/untrash durante 30 dias.",
    }


def gmail_list_drafts(max_results: int = 10) -> dict:
    d = gauth.api_get(f"{GMAIL}/drafts", params={"maxResults": max(1, min(int(max_results), 50))})
    out = []
    for item in d.get("drafts", []):
        m = gauth.api_get(f"{GMAIL}/messages/{item['message']['id']}", params={"format": "metadata"})
        h = _headers_to_dict(m)
        h["draft_id"] = item["id"]
        out.append(h)
    return {"drafts": out}


def _build_mime(to: str, subject: str, body: str, cc: str, bcc: str) -> str:
    import email.message

    msg = email.message.EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject or ""
    msg.set_content(body or "")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _headers_to_dict(m: dict) -> dict:
    # Gmail devuelve payload.headers como lista de objetos {"name":..., "value":...},
    # NO como pares [nombre, valor]. Iterar con "for k, v in headers" recorría las
    # claves del dict ("name", "value") y construía {"name": "value"}, asi que todos
    # los campos salian vacios. Hay que acceder por item["name"] / item["value"].
    h = {}
    for item in (m.get("payload") or {}).get("headers") or []:
        name = str(item.get("name", "")).lower()
        if name:
            h[name] = item.get("value", "")
    return {
        "id": m.get("id"),
        "thread_id": m.get("threadId"),
        "de": h.get("from", ""),
        "para": h.get("to", ""),
        "asunto": h.get("subject", ""),
        "fecha": h.get("date", ""),
        "etiquetas": m.get("labelIds", []),
        "sin_leer": "UNREAD" in (m.get("labelIds") or []),
    }


def _extract_text(m: dict) -> str:
    """Recorre el arbol MIME y concatena solo las partes text/plain."""
    parts = []

    def walk(node):
        mime = node.get("mimeType", "")
        data = (node.get("body") or {}).get("data")
        if mime == "text/plain" and data:
            try:
                parts.append(base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace"))
            except Exception:
                pass
        for child in node.get("parts") or []:
            walk(child)

    walk(m.get("payload") or {})
    if not parts:
        snip = m.get("snippet")
        if snip:
            return snip
    return "\n".join(parts)


# ------------------------------------------------------------ Calendar


def calendar_list_events(days: int = 7, max_results: int = 25, calendar_id: str = "primary") -> dict:
    """Lista eventos de HOY a hoy+days.

    timeMin se trunca a MEDIANOCHE de hoy (Madrid), no a la hora actual. Con
    datetime.now() el rango empezaba a las 21:48, asi que un evento de las 20:45
    de manana quedaba FUERA y la herramienta devolia 0 eventos: hacia pensar que
    no estaba creado cuando si estaba. Empezar por el inicio del dia completo.
    """
    import datetime

    days = max(1, min(int(days), 180))
    # Inicio de HOY en Madrid, no este instante. Asi "hoy" incluye lo que ya ha
    # empezado, que es justo lo que el usuario quiere ver.
    hoy = datetime.datetime.now(MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    start = hoy.astimezone(datetime.timezone.utc)
    end = hoy + datetime.timedelta(days=days)
    now = start
    data = gauth.api_get(
        f"{CAL}/calendars/{urllib.parse.quote(calendar_id)}/events",
        params={
            "timeMin": now.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "maxResults": max(1, min(int(max_results), 250)),
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeZone": "Europe/Madrid",
        },
    )
    events = []
    for e in data.get("items", []):
        start = e.get("start", {})
        events.append(
            {
                "id": e.get("id"),
                "resumen": e.get("summary", "(sin titulo)"),
                "inicio": start.get("dateTime") or start.get("date"),
                "fin": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                "lugar": e.get("location", ""),
                "organizador": (e.get("organizer") or {}).get("email", ""),
                "asistentes": [a.get("email") for a in e.get("attendees", [])],
            }
        )
    return {"calendario": calendar_id, "proximos_dias": days, "eventos": events}


def calendar_find_free_slots(days: int = 7, calendar_id: str = "primary", work_hours: str = "09:00-18:00") -> dict:
    import datetime

    days = max(1, min(int(days), 60))
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=days)
    # freeBusy es POST-ONLY: acepta el cuerpo {items:[{id}]} y devuelve los
    # tramos ocupados. Con GET devuelve 404. Por eso va por api_post y no api_get.
    data = gauth.api_post(
        f"{CAL}/freeBusy",
        {
            "timeMin": now.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "timeZone": "Europe/Madrid",
            "items": [{"id": calendar_id}],
        },
    )
    busy = data.get("calendars", {}).get(calendar_id, {}).get("busy", [])
    try:
        h_in, h_out = work_hours.split("-")
        start_h, end_h = int(h_in[:2]), int(h_out[:2])
    except Exception:
        start_h, end_h = 9, 18

    def parse(s):
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

    busy_spans = sorted((parse(b["start"]), parse(b["end"])) for b in busy)
    free = []
    cursor = now
    limit = end
    while cursor < limit:
        day_start = cursor.replace(hour=start_h, minute=0, second=0, microsecond=0)
        day_end = cursor.replace(hour=end_h, minute=0, second=0, microsecond=0)
        if day_end <= cursor:
            cursor = (cursor + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            continue
        if day_start < cursor:
            day_start = cursor
        slots, t = [], day_start
        for bstart, bend in busy_spans:
            if bend <= t or bstart >= day_end:
                continue
            if bstart > t:
                slots.append((t, min(bstart, day_end)))
            t = max(t, bend)
        if t < day_end:
            slots.append((t, day_end))
        for s, e in slots:
            if e - s >= datetime.timedelta(minutes=30):
                # .astimezone(MADRID) explicito: no depender de la zona del sistema.
                ms, me = s.astimezone(MADRID), e.astimezone(MADRID)
                free.append(
                    {
                        "inicio": ms.isoformat(),
                        "fin": me.isoformat(),
                        "hora_local": f"{ms.strftime('%H:%M')}-{me.strftime('%H:%M')}",
                        "dia": ms.strftime("%Y-%m-%d %A"),
                        "horas": round((me - ms).total_seconds() / 3600, 2),
                    }
                )
        cursor = (cursor + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if len(free) > 40:
            break
    return {"calendario": calendar_id, "horario": work_hours, "huecos_libres": free[:40]}


# Coincidencia EXACTA de palabra, nunca por prefijo. Se intento lo contrario y
# fue un desastre: "los" -> lunes, "solo" -> sabado, "semanas" -> sabado,
# "de" -> domingo, "vez" -> viernes. Un prefijo de dos letras casa con cualquier
# palabra castellana, y ahi se cuelan dias que el usuario no ha pedido.
# Solo se aceptan las formas que estan escritas aqui, una a una.
_DIA_PALABRA = {
    # Castellano, singular y plural
    "lunes": "MO", "martes": "TU", "miercoles": "WE", "jueves": "TH",
    "viernes": "FR", "sabado": "SA", "domingo": "SU",
    "sabados": "SA", "domingos": "SU",
    # Castellano, abreviaturas que se usan al escribir
    "lun": "MO", "mar": "TU", "mie": "WE", "mier": "WE", "mi": "WE",
    "jue": "TH", "ju": "TH", "vie": "FR", "vier": "FR", "sab": "SA",
    "dom": "SU",
    # Ingles
    "monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH",
    "friday": "FR", "saturday": "SA", "sunday": "SU",
    "mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH",
    "fri": "FR", "sat": "SA", "sun": "SU",
}

# Letras sueltas: convencion espanola, M es MARTES y X es MIERCOLES.
_LETRA = {"l": "MO", "m": "TU", "x": "WE", "j": "TH", "v": "FR", "s": "SA", "d": "SU"}

# Codigos RRULE de Google, que llegan en mayusculas: "MO-WE-FR", "MO,WE,FR".
_CODIGO = {"MO": "MO", "TU": "TU", "WE": "WE", "TH": "TH",
           "FR": "FR", "SA": "SA", "SU": "SU"}

# Conectores de rango. OJO: "y" NO es conector. "lunes, miercoles y viernes" son
# tres dias sueltos; si "y" uniera el rango, miercoles-viernes se expandiria a
# jueves y apareceria un dia que nadie pidio.
_RANGO = ("a", "al", "hasta")

_ORDEN = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _token_a_dia(token: str):
    """Un token -> codigo de dia, o None si no es un dia. Nunca adivina."""
    if token in _CODIGO:            # "MO" en mayusculas, codigo RRULE
        return _CODIGO[token]
    bajo = _sin_tildes(token.lower())
    if bajo in _DIA_PALABRA:
        return _DIA_PALABRA[bajo]
    if len(bajo) == 1 and bajo in _LETRA:
        return _LETRA[bajo]
    return None


def _dias_de(frase: str) -> list:
    """Dias citados, en orden natural de semana y sin repetir.

    Estricto: si no reconoce nada devuelve [] en vez de adivinar. Devolver dias
    equivocados en silencio es peor que no devolver nada, porque el evento se crea
    con la recurrencia equivocada y el aviso de "no se aplico" no salta.
    """
    crudo = str(frase)
    # Los codigos RRULE ("MO,WE,FR") se buscan ANTES de pasar a minuscula.
    codigos = [t for t in re.findall(r"[A-Za-z]+", crudo) if t in _CODIGO]
    dias = []
    for t in codigos:
        if _CODIGO[t] not in dias:
            dias.append(_CODIGO[t])
    if dias:
        return sorted(dias, key=_ORDEN.index)

    limpio = _sin_tildes(crudo.lower())
    tokens = re.findall(r"[a-z]+", limpio)
    codigos_de = [_token_a_dia(t) for t in tokens]

    for d in codigos_de:
        if d and d not in dias:
            dias.append(d)

    # Rangos: "de lunes a viernes" -> los cinco dias laborables.
    for i in range(len(tokens) - 2):
        if tokens[i + 1] not in _RANGO:
            continue
        a, b = codigos_de[i], codigos_de[i + 2]
        if a and b and _ORDEN.index(a) < _ORDEN.index(b):
            for d in _ORDEN[_ORDEN.index(a):_ORDEN.index(b) + 1]:
                if d not in dias:
                    dias.append(d)

    return sorted(dias, key=_ORDEN.index)


def _sin_tildes(x: str) -> str:
    import unicodedata as _ud
    return "".join(c for c in _ud.normalize("NFD", x) if _ud.category(c) != "Mn")


def _rrule(spec: str) -> str:
    """Convierte texto en un RRULE de Google Calendar.

    Acepta cosas como "todos los lunes, miercoles y viernes", "todos los dias",
    "cada 2 semanas los martes", "lunes hasta 2026-12-31", "6 veces los lunes",
    "L-M-X-V". Devuelve "" si no entiende la frase (mejor no repetir que repetir
    mal).

    Orden importante: primero se quitan tildes y se limpian las frases negativas,
    despues se extraen los modificadores (hasta / N veces / cada N) SIN mutilar el
    resto, y solo entonces se buscan los dias.
    """
    crudo = str(spec or "").strip()
    if not crudo:
        return ""
    s = crudo.lower()

    # Frases que niegan
    limpio = _sin_tildes(s)
    if re.search(r"\bsin\b|\bno\b|\bnunca\b|\bninguno\b", limpio):
        return ""
    s = limpio

    hasta = ""
    m = re.search(r"(?:hasta|hasta el|until)\s+(\d{4}-\d{2}-\d{2})", s)
    if m:
        hasta = ";UNTIL=" + m.group(1).replace("-", "") + "T235959Z"
        s = s[:m.start()] + " " + s[m.end():]

    total = ""
    m = re.search(r"(\d+)\s*(?:veces|repeticiones|repeticiones)", s)
    if m:
        total = ";COUNT=" + m.group(1)
        s = s[:m.start()] + " " + s[m.end():]

    cada = ""
    m = re.search(r"cada\s+(\d+)\s*(?:semanas|semana|dias|dia)", s)
    if m:
        n = int(m.group(1))
        cada = ";INTERVAL=" + str(n) if n > 1 else ""
        s = s[:m.start()] + " " + s[m.end():]

    if re.search(r"\b(diario?|todos los dias|every day)\b", s):
        return "FREQ=DAILY" + cada + total + hasta

    dias = _dias_de(crudo)
    if not dias:
        return ""
    return "FREQ=WEEKLY;BYDAY=" + ",".join(dias) + cada + total + hasta


def _hint(start: str) -> str:
    """Devuelve un ejemplo de fecha ISO con el offset de Madrid correcto."""
    import datetime as _dt

    try:
        y = int(str(start)[0:4]) if str(start)[:4].isdigit() else _dt.datetime.now(MADRID).year
        ref = _dt.datetime(y, 7, 1, 12, 0, tzinfo=MADRID)  # julio => +02:00
        return ref.isoformat()
    except Exception:
        return "2026-09-26T20:45:00+02:00"


def calendar_create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
    calendar_id: str = "primary",
    repeat: str = "",
) -> dict:
    """Crea un evento. 'start' y 'end' en ISO 8601 con zona, p.ej.
    2026-09-26T20:45:00+02:00. 'attendees' es una lista de emails separada
    por comas: eso envia invitaciones por correo."""
    import datetime

    if not summary:
        raise ValueError("falta 'summary' (el titulo del evento).")
    try:
        s = datetime.datetime.fromisoformat(start)
        e = datetime.datetime.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(
            f"start/end deben ser ISO 8601 con zona, p.ej. 2026-09-26T20:45:00+02:00. Detalle: {exc}"
        ) from exc
    if s.tzinfo is None:
        raise ValueError(
            "'start' y 'end' necesitan zona horaria. Ejemplo correcto: "
            f"'{_hint(start)}. Sin zona, la cita se guarda con la hora que le de Google (UTC) y sale "
            "2 horas (o 1 en invierno) descuadrada."
        )
    if e <= s:
        raise ValueError("'end' debe ser posterior a 'start'.")

    # El usuario quiere TODO en hora de Madrid. Si el offset que llega no es el de
    # Madrid en esa fecha, casi siempre es un error de.utc() o un -05:00 arrastrado.
    for label, dt in (("start", s), ("end", e)):
        esperado = dt.astimezone(MADRID).utcoffset()
        if dt.utcoffset() != esperado:
            ref = dt.astimezone(MADRID)
            raise ValueError(
                f"'{label}' no está en hora de Madrid. Pides {dt.isoformat()} "
                f"(offset {dt.strftime('%z')}), pero en esa fecha Madrid va "
                f"{ref.strftime('%z')}. Reinterpreta la hora local en Madrid, p.ej. "
                f"{_hint(start)}, y vuelve a llamar."
            )

    body = {
        "summary": summary,
        "start": {"dateTime": s.isoformat(), "timeZone": "Europe/Madrid"},
        "end": {"dateTime": e.isoformat(), "timeZone": "Europe/Madrid"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    # Resolver NOMBRES a emails con el directorio local. "Eli" -> su direccion.
    # Sin esto el agente tenia que recordar el email y acababa pidiendotelo.
    emails, resueltos, sin_resolver = contacts.resolver_lista(attendees)
    if sin_resolver:
        raise ValueError(
            "No encuentro el contacto: %s. Conocidos: %s. O escribe el email completo."
            % (", ".join(sin_resolver), ", ".join(contacts.cargar().keys()) or "(directorio vacio)")
        )
    if emails:
        body["attendees"] = [{"email": a} for a in emails]

    rrule = _rrule(repeat)
    if repeat and not rrule:
        # Fallo SILENCIOSO: el usuario pidio repeticion y el parser no la entendio.
        # Antes se creaba el evento como una sesion y el usuario se enteraba
        # tres dias despues, al no aparecer el miercoles. Ahora se para y lo dice.
        return {
            "error": "No entiendo la repeticion que has pedido y NO he creado el evento.",
            "repeticion_no_entendida": repeat,
            "formatos_validos": [
                "todos los lunes, miercoles y viernes",
                "lunes miercoles viernes",
                "todos los dias",
                "cada 2 semanas los martes",
                "todos los lunes hasta 2026-12-31",
                "6 veces los lunes",
                "de lunes a viernes",
                "L-M-X-V",
            ],
            "que_hacer": "Repite la peticion con alguno de estos formatos, o pregunta al usuario cual queria. NO crees el evento sin repeticion ni lo repartas en varios eventos sueltos.",
        }
    if rrule:
        body["recurrence"] = ["RRULE:" + rrule]

    d = gauth.api_post(f"{CAL}/calendars/{urllib.parse.quote(calendar_id)}/events", body)
    return {
        "event_id": d.get("id"),
        "html_link": d.get("htmlLink"),
        "titulo": summary,
        "inicio": body["start"]["dateTime"],
        "fin": body["end"]["dateTime"],
        "invitados": emails,
        "invitados_resueltos": resueltos,
        "recurrencia": ("RRULE:" + rrule) if rrule else "",
        "status": "evento creado",
    }


def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> dict:
    # NO hacer "import urllib.request" aqui dentro: crea una variable local urllib
    # que tapa el import de modulo hecho arriba, y rompe urllib.parse.quote con
    # UnboundLocalError. El import va arriba, una sola vez.
    url = f"{CAL}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + gauth.access_token()}, method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=45):
            pass
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise gauth.AuthError(
                f"No existe el evento {event_id}. Puede que ya estuviera borrado."
            ) from e
        raise gauth.AuthError(f"No se pudo borrar el evento: API {e.code}") from e
    except urllib.error.URLError as e:
        raise gauth.AuthError(f"No se pudo contactar con Google: {e.reason}") from e
    return {"event_id": event_id, "status": "evento eliminado"}


# ---------------------------------------------------------------- Drive


def drive_search_files(query: str = "", max_results: int = 20) -> dict:
    """'query' usa la sintaxis de Drive. Dejarlo vacio lista los archivos
    recientes. Ejemplos: name contains 'factura' / mimeType contains 'pdf'
    / 'in parents' no se soporta, usa drive_list_folder."""
    max_results = max(1, min(int(max_results), 100))
    escaped = (query or "").replace("\\", "\\\\").replace("'", "\\'")
    q = f"name contains '{escaped}'" if query else "trashed = false"
    if query:
        q += " and trashed = false"
    data = gauth.api_get(
        f"{DRIVE}/files",
        params={
            "q": q,
            "maxResults": max_results,
            "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,owners),nextPageToken",
            "orderBy": "modifiedTime desc",
        },
    )
    return {
        "consulta": query or "(todos los no eliminados)",
        "archivos": [
            {
                "id": f.get("id"),
                "nombre": f.get("name"),
                "tipo": f.get("mimeType"),
                "tamano_bytes": f.get("size"),
                "modificado": f.get("modifiedTime"),
                "enlace": f.get("webViewLink"),
            }
            for f in data.get("files", [])
        ],
    }


def drive_read_file(file_id: str, max_chars: int = 20000) -> dict:
    meta = gauth.api_get(
        f"{DRIVE}/files/{urllib.parse.quote(file_id)}", params={"fields": "id,name,mimeType,size"}
    )
    out = {"id": meta.get("id"), "nombre": meta.get("name"), "tipo": meta.get("mimeType")}

    if meta.get("mimeType") == "application/vnd.google-apps.document":
        d = gauth.api_get(f"{DRIVE}/files/{urllib.parse.quote(file_id)}/export", params={"mimeType": "text/plain"})
        out["contenido"] = (d or "")[:max_chars]
        out["tipo_exportado"] = "texto plano"
        return out

    if meta.get("mimeType") == "application/vnd.google-apps.spreadsheet":
        vals = gauth.api_get(
            f"{DRIVE}/files/{urllib.parse.quote(file_id)}/values",
            params={"range": "A1:Z200"},
        )
        out["contenido"] = vals.get("values", [])[:200]
        out["tipo_exportado"] = "valores de hoja"
        return out

    d = gauth.api_get(f"{DRIVE}/files/{urllib.parse.quote(file_id)}", params={"alt": "media"})
    if isinstance(d, str):
        out["contenido"] = d[:max_chars]
    else:
        out["contenido"] = str(d)[:max_chars]
    return out


def drive_list_folder(folder_id: str = "root", max_results: int = 30) -> dict:
    data = gauth.api_get(
        f"{DRIVE}/files",
        params={
            "q": f"'{urllib.parse.quote(folder_id)}' in parents and trashed = false",
            "maxResults": max(1, min(int(max_results), 200)),
            "fields": "files(id,name,mimeType,size,modifiedTime),nextPageToken",
            "orderBy": "folder,name",
        },
    )
    return {
        "carpeta": folder_id,
        "elementos": [
            {
                "id": f.get("id"),
                "nombre": f.get("name"),
                "tipo": "carpeta" if f.get("mimeType") == "application/vnd.google-apps.folder" else "archivo",
                "modificado": f.get("modifiedTime"),
            }
            for f in data.get("files", [])
        ],
    }


# ---------------------------------------------------------------------------
# Drive: ESCRITURA. Solo con el scope drive.file, que permite crear y modificar
# archivos que la propia app ha creado, y nada mas. Borrar y mover NO existen
# a proposito: el agente deja cosas, no limpia el Drive del usuario.
# ---------------------------------------------------------------------------

_MIME = {
    ".md": "text/markdown", ".markdown": "text/markdown",
    ".txt": "text/plain", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".json": "application/json", ".xml": "application/xml",
    ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
    ".py": "text/x-python", ".sh": "text/x-shellscript", ".yaml": "text/yaml",
    ".yml": "text/yaml", ".sql": "text/x-sql", ".log": "text/plain",
}

FOLDER_MIME = "application/vnd.google-apps.folder"


def _mime_de(nombre: str) -> str:
    for ext, m in _MIME.items():
        if str(nombre).lower().endswith(ext):
            return m
    return "text/plain"


def drive_find_folder(name: str, parent_id: str = "root") -> dict:
    """Localiza una carpeta por nombre exacto dentro de 'parent_id'."""
    if not name:
        raise ValueError("falta el nombre de la carpeta.")
    esc = name.replace("\\", "\\\\").replace("'", "\\'")
    data = gauth.api_get(
        f"{DRIVE}/files",
        params={
            "q": f"name = '{esc}' and mimeType = '{FOLDER_MIME}' "
                 f"and '{parent_id}' in parents and trashed = false",
            "fields": "files(id,name,webViewLink)",
            "maxResults": 5,
        },
    )
    archivos = data.get("files", [])
    return {
        "nombre": name,
        "id": archivos[0]["id"] if archivos else "",
        "enlace": archivos[0].get("webViewLink", "") if archivos else "",
        "existe": bool(archivos),
    }


def drive_create_folder(name: str, parent_id: str = "root") -> dict:
    """Crea una carpeta. Si ya existe con ese nombre, la devuelve tal cual en
    vez de crear otra: dos carpetas con el mismo nombre son ruido."""
    previa = drive_find_folder(name, parent_id)
    if previa["existe"]:
        previa["ya_existia"] = True
        return previa
    d = gauth.api_post(
        f"{DRIVE}/files",
        {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
    )
    return {
        "nombre": d.get("name", name),
        "id": d.get("id", ""),
        "enlace": d.get("webViewLink", ""),
        "existe": True,
        "ya_existia": False,
    }


def drive_write_file(name: str, content: str, folder: str = "Hermes",
                     description: str = "") -> dict:
    """Crea o actualiza un archivo de texto.

    'folder' admite un id de carpeta o un nombre. Si es un nombre y no existe,
    la crea. Todo lo que escribe el agente cae ahi dentro, para no repartir
    archivos por el Drive del usuario.

    Si el archivo ya existe, lo ACTUALIZA, pero solo si lo creo la app. Con el
    scope drive.file, un archivo del usuario simplemente da 403 al intentar
    tocarlo, y eso se reporta con un mensaje claro en vez de un error generico.
    """
    if not name:
        raise ValueError("falta el 'name' del archivo (p.ej. notas.md).")
    if content is None:
        raise ValueError("falta el 'content'.")
    if "/" in name or name in (".", ".."):
        raise ValueError(
            "'name' es solo el nombre del archivo, sin carpetas. "
            "Usa 'folder' para decidir donde se guarda."
        )

    # Resolver carpeta: id si parece un id, nombre -> buscar o crear.
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", folder or ""):
        folder_id, folder_nombre = folder, "(id directo)"
    else:
        carpeta = drive_create_folder(folder or "Hermes")
        folder_id, folder_nombre = carpeta["id"], carpeta["nombre"]

    esc = name.replace("\\", "\\\\").replace("'", "\\'")
    previo = gauth.api_get(
        f"{DRIVE}/files",
        params={
            "q": f"name = '{esc}' and '{folder_id}' in parents and trashed = false",
            "fields": "files(id,name,modifiedTime,webViewLink)",
            "maxResults": 1,
        },
    ).get("files", [])

    cuerpo = str(content).encode("utf-8")
    mime = _mime_de(name)

    if previo:
        try:
            d = gauth.api_upload(
                DRIVE_UPLOAD + "/" + previo[0]["id"], cuerpo, mime, method="PATCH"
            )
        except gauth.AuthError as exc:
            if "403" in str(exc):
                raise gauth.AuthError(
                    "No puedo escribir en '%s': ese archivo ya existia y no lo creo la "
                    "aplicacion, asi que el permiso drive.file no me deja tocarlo. Es "
                    "a proposito. Usa otro nombre, o pidele al usuario que lo comparta "
                    "con la aplicacion. Detalle: %s" % (name, str(exc)[:160])
                ) from exc
            raise
        return {
            "accion": "actualizado",
            "nombre": d.get("name", name),
            "id": d.get("id"),
            "carpeta": folder_nombre,
            "enlace": d.get("webViewLink", ""),
            "bytes": len(cuerpo),
            "tipo": mime,
        }

    d = gauth.api_upload(
        DRIVE_UPLOAD,
        cuerpo,
        mime,
        metadata={"name": name, "parents": [folder_id], "description": description},
        params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
    )
    return {
        "accion": "creado",
        "nombre": d.get("name", name),
        "id": d.get("id"),
        "carpeta": folder_nombre,
        "enlace": d.get("webViewLink", ""),
        "bytes": len(cuerpo),
        "tipo": mime,
    }
