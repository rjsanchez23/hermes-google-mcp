"""
Redaccion de la confirmacion. El agente no debe poder decir "hecho" con datos
que no son los del servidor: el texto lo pone esta funcion, a partir del
resultado real de la llamada, y el agente solo lo reenvia.

Por que existe: tres versiones de skill y el agente seguia fulfilliendo la
letra y saltando el fondo. Inventaba duraciones, inventaba ubicaciones, y
decia "verificado" mirando una herramienta que no verifica eventos. Escribir
la regla no era un candado; que no pueda redactar el mensaje si.

Formato de los textos: una linea de resultado, los datos exactos, y el
numero de recibo. Sin adornos, sin "listo", sin emojis de tick.
"""

import datetime


def _fecha_legible(iso: str) -> str:
    """'2026-09-26T20:45:00+02:00' -> 'sabado 26 de septiembre, 20:45'."""
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    try:
        d = datetime.datetime.fromisoformat(iso)
    except Exception:
        return iso
    return "%s %d de %s, %s" % (dias[d.weekday()], d.day, meses[d.month - 1], d.strftime("%H:%M"))


def _duracion(ini: str, fin: str) -> str:
    try:
        a = datetime.datetime.fromisoformat(ini)
        b = datetime.datetime.fromisoformat(fin)
        mins = int((b - a).total_seconds() // 60)
        h, m = divmod(mins, 60)
        if h and m:
            return "%dh %02dmin" % (h, m)
        if h:
            return "%dh" % h
        return "%dmin" % m
    except Exception:
        return "duracion desconocida"


def evento_creado(r: dict) -> str:
    lineas = [
        "Evento creado en Google Calendar.",
        "",
        "Titulo: %s" % r.get("titulo", "(sin titulo)"),
        "Empieza: %s" % _fecha_legible(r.get("inicio", "")),
        "Termina: %s (%s)" % (_fecha_legible(r.get("fin", "")), _duracion(r.get("inicio", ""), r.get("fin", ""))),
    ]
    if r.get("location"):
        lineas.append("Lugar: %s" % r["location"])
    if r.get("invitados"):
        lineas.append("Invitados: %s" % ", ".join(r["invitados"]))
        lineas.append("  (estan en estado pendiente. Nadie ha recibido ningun correo.)")
    else:
        lineas.append("Invitados: ninguno")
    if r.get("html_link"):
        lineas.append("Enlace: %s" % r["html_link"])
    lineas += ["", "Recibo: %s" % r.get("_recibo", "SIN RECIBO")]
    return "\n".join(lineas)


def evento_borrado(r: dict) -> str:
    return "\n".join([
        "Evento borrado del calendario.",
        "",
        "Id: %s" % r.get("event_id", "?"),
        "Recibo: %s" % r.get("_recibo", "SIN RECIBO"),
        "",
        "El evento se elimina de los calendarios de todos los invitados.",
    ])


def correo_enviado(r: dict) -> str:
    return "\n".join([
        "Correo ENVIADO.",
        "",
        "Para: %s" % r.get("para", "?"),
        "Asunto: %s" % r.get("asunto", ""),
        "Id: %s" % r.get("message_id", "?"),
        "",
        "No se puede deshacer. Para escribir sin enviar, usa gmail_create_draft.",
        "Recibo: %s" % r.get("_recibo", "SIN RECIBO"),
    ])


def borrador_creado(r: dict) -> str:
    return "\n".join([
        "Borrador creado. NO se ha enviado nada.",
        "",
        "Para: %s" % r.get("para", "?"),
        "Asunto: %s" % r.get("asunto", ""),
        "Id: %s" % r.get("draft_id", "?"),
        "",
        "Revisalo en Gmail y envialo tu.",
        "Recibo: %s" % r.get("_recibo", "SIN RECIBO"),
    ])


def correo_papelera(r: dict) -> str:
    return "\n".join([
        "Correo movido a la papelera.",
        "",
        "Id: %s" % r.get("message_id", "?"),
        "Recuperable durante 30 dias.",
        "Recibo: %s" % r.get("_recibo", "SIN RECIBO"),
    ])


REDACTORES = {
    "calendar_create_event": evento_creado,
    "calendar_delete_event": evento_borrado,
    "gmail_send_email": correo_enviado,
    "gmail_create_draft": borrador_creado,
    "gmail_trash_email": correo_papelera,
}


def redactar(tool: str, resultado: dict) -> str:
    """Texto oficial de la accion. Si no hay redactor, se devuelve None."""
    fn = REDACTORES.get(tool)
    if not fn:
        return None
    try:
        return fn(resultado)
    except Exception:
        return None
