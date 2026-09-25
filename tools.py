"""
Herramientas de Gmail, Calendar y Drive. Solo lectura en Drive a proposito.

Cada funcion devuelve un dict ya serializable. Ninguna imprime secretos.
Las de escritura piden confirmacion al usuario antes de ejecutarse: eso lo
decide el agente leyendo la descripcion de la herramienta, no este modulo.
"""

import base64
import re
import urllib.parse
from zoneinfo import ZoneInfo

import gauth

# El usuario es de Espana: TODO el calendario va en hora de Madrid, sin excepcion.
# Madrid alterna +02:00 (verano) y +01:00 (invierno), asi que un offset fijo se
# romperia en enero. Se usa la zona real y se valida contra ella.
MADRID = ZoneInfo("Europe/Madrid")

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"

BASE64_RE = re.compile(r"[^A-Za-z0-9+/=_-]")


# ---------------------------------------------------------------- Gmail


def gmail_list_labels() -> dict:
    data = gauth.api_get(f"{GMAIL}/labels")
    return {
        "labels": [
            {
                "id": l["id"],
                "name": l["name"],
                "type": l.get("type"),
                "total": l.get("messagesTotal"),
                "unread": l.get("messagesUnread"),
            }
            for l in data.get("labels", [])
        ]
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
    h = {k.lower(): v for k, v in (m.get("payload", {}).get("headers") or [])}
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
    import datetime

    days = max(1, min(int(days), 180))
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=days)
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
    data = gauth.api_get(
        f"{CAL}/freeBusy",
        params={
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
    emails = [a.strip() for a in (attendees or "").split(",") if "@" in a]
    if emails:
        body["attendees"] = [{"email": a} for a in emails]

    d = gauth.api_post(f"{CAL}/calendars/{urllib.parse.quote(calendar_id)}/events", body)
    return {
        "event_id": d.get("id"),
        "html_link": d.get("htmlLink"),
        "titulo": summary,
        "inicio": body["start"]["dateTime"],
        "fin": body["end"]["dateTime"],
        "invitados": emails,
        "status": "evento creado",
    }


def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> dict:
    url = f"{CAL}/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id)}"
    import urllib.request

    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + gauth.access_token()}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=45):
            pass
    except Exception as e:
        raise gauth.AuthError(f"No se pudo borrar el evento: {e}") from e
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
