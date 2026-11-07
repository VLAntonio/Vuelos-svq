#!/usr/bin/env python3
"""
Alertas de vuelos baratos desde Sevilla.

Para cada destino y duración consulta el calendario de precios de Google Flights
(todas las aerolíneas) y avisa por correo y/o WhatsApp cuando:
  1) un precio baja del umbral (entra en zona barata), o
  2) estando ya bajo el umbral, vuelve a bajar respecto al último precio visto.
Si el precio sube por encima del umbral, la alerta se "rearma" para la próxima bajada.

Uso:
  python vuelos_alerta.py                # ejecución normal
  python vuelos_alerta.py --sin-enviar   # imprime los avisos sin mandarlos
  python vuelos_alerta.py --prueba-aviso # manda un mensaje de prueba y sale

Variables de entorno (todas opcionales; sin ellas ese canal se desactiva):
  SMTP_USUARIO, SMTP_PASSWORD, EMAIL_DESTINO, [SMTP_SERVIDOR=smtp.gmail.com, SMTP_PUERTO=465]
  WHATSAPP_TELEFONO (+34...), WHATSAPP_APIKEY   (CallMeBot)
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import time
import tomllib
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUTA_CONFIG = BASE / "config.toml"
RUTA_ESTADO = BASE / "estado.json"


# ─────────────────────────── configuración ───────────────────────────
def cargar_config(ruta: Path = RUTA_CONFIG) -> dict:
    with open(ruta, "rb") as f:
        cfg = tomllib.load(f)
    umbrales: dict[str, float] = {}
    for grupo in cfg.get("grupos", {}).values():
        for d in grupo["destinos"]:
            umbrales[d] = float(grupo["umbral"])
    for d, u in cfg.get("umbral_destino", {}).items():
        umbrales[d] = float(u)
    cfg["umbrales"] = umbrales
    return cfg


# ─────────────────────────── estado ───────────────────────────
def cargar_estado(ruta: Path = RUTA_ESTADO) -> dict:
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {}


def guardar_estado(estado: dict, ruta: Path = RUTA_ESTADO) -> None:
    ruta.write_text(json.dumps(estado, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def clave(destino: str, ida: str, vuelta: str) -> str:
    return f"{destino}|{ida}|{vuelta}"


# ─────────────────────────── lógica de alertas (pura, testeable) ───────────────────────────
def evaluar(precios: list[dict], estado: dict, umbrales: dict, bajada_minima: float, hoy: date) -> list[dict]:
    """
    precios: [{destino, ida, vuelta, precio}]
    estado:  {clave: {"precio": último visto, "bajo_umbral": bool}}  (se modifica in situ)
    Devuelve la lista de alertas a enviar.
    """
    alertas = []
    for p in precios:
        if p["precio"] is None or p["precio"] <= 0:
            continue
        umbral = umbrales.get(p["destino"])
        if umbral is None:
            continue
        k = clave(p["destino"], p["ida"], p["vuelta"])
        previo = estado.get(k)
        actual = float(p["precio"])

        if actual < umbral:
            if previo is None or not previo.get("bajo_umbral"):
                alertas.append({**p, "motivo": "nuevo", "umbral": umbral, "anterior": previo["precio"] if previo else None})
            elif previo["precio"] - actual >= bajada_minima:
                alertas.append({**p, "motivo": "bajada", "umbral": umbral, "anterior": previo["precio"]})
            estado[k] = {"precio": actual, "bajo_umbral": True}
        else:
            estado[k] = {"precio": actual, "bajo_umbral": False}

    # limpiar fechas pasadas
    hoy_s = hoy.isoformat()
    for k in [k for k in estado if k.split("|")[1] < hoy_s]:
        del estado[k]
    return alertas


# ─────────────────────────── Google Flights ───────────────────────────
def enlace_google(origen: str, destino: str, ida: str, vuelta: str, moneda: str) -> str:
    try:
        from fast_flights import FlightQuery, Passengers, create_query
        q = create_query(
            flights=[FlightQuery(date=ida, from_airport=origen, to_airport=destino),
                     FlightQuery(date=vuelta, from_airport=destino, to_airport=origen)],
            trip="round-trip", passengers=Passengers(adults=1), currency=moneda,
        )
        return q.url()
    except Exception:
        texto = f"Flights from {origen} to {destino} on {ida} through {vuelta}"
        return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(texto)


def consultar_precios(cfg: dict, hoy: date) -> tuple[list[dict], int, int]:
    """Devuelve (precios, peticiones_ok, peticiones_fallidas)."""
    from fast_flights import get_calendar_graph

    origen, moneda = cfg["origen"], cfg["moneda"]
    max_esc = None if cfg.get("max_escalas", -1) < 0 else cfg["max_escalas"]
    fin = hoy + timedelta(days=cfg["horizonte_dias"])
    bloque = cfg["bloque_dias"]
    precios, ok, ko = [], 0, 0

    for destino in cfg["umbrales"]:
        for dur in cfg["duraciones"]:
            ini = hoy + timedelta(days=1)
            while ini <= fin:
                tope = min(ini + timedelta(days=bloque - 1), fin)
                for intento in range(3):
                    try:
                        cal = get_calendar_graph(
                            from_airport=origen, to_airport=destino,
                            date_range=(ini.isoformat(), tope.isoformat()),
                            trip_duration=dur, max_stops=max_esc,
                            separate_tickets=True, currency=moneda, language="es",
                        )
                        for e in cal.entries:
                            if e.price and ini.isoformat() <= e.outbound_date <= tope.isoformat():
                                precios.append({"destino": destino, "ida": e.outbound_date,
                                                "vuelta": e.return_date, "precio": float(e.price)})
                        ok += 1
                        break
                    except Exception as exc:
                        if intento == 2:
                            ko += 1
                            print(f"  ✗ {destino} {dur}n {ini}: {exc}", file=sys.stderr)
                        time.sleep(cfg["pausa_segundos"] * (3 + intento * 5))
                time.sleep(cfg["pausa_segundos"])
                ini = tope + timedelta(days=1)
        print(f"  {destino}: hecho", flush=True)
    return precios, ok, ko


# ─────────────────────────── mensajes ───────────────────────────
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def fecha_corta(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def linea(a: dict) -> str:
    extra = "🆕" if a["motivo"] == "nuevo" else f"⬇️ antes {a['anterior']:.0f}€"
    return f"{a['precio']:.0f}€  {fecha_corta(a['ida'])} → {fecha_corta(a['vuelta'])}  {extra}"


def agrupar(alertas: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for a in sorted(alertas, key=lambda x: (x["destino"], x["precio"], x["ida"])):
        g.setdefault(a["destino"], []).append(a)
    # destinos ordenados por su mejor precio
    return dict(sorted(g.items(), key=lambda kv: kv[1][0]["precio"]))


def texto_whatsapp(alertas: list[dict], origen: str, max_por_destino: int = 3, max_destinos: int = 15) -> str:
    g = agrupar(alertas)
    partes = [f"✈️ *Vuelos baratos desde {origen}* ({len(alertas)} avisos)"]
    for i, (dest, lst) in enumerate(g.items()):
        if i >= max_destinos:
            partes.append(f"…y {len(g) - max_destinos} destinos más (ver correo)")
            break
        partes.append(f"\n*{origen}→{dest}* (umbral {lst[0]['umbral']:.0f}€)")
        partes += [linea(a) for a in lst[:max_por_destino]]
        if len(lst) > max_por_destino:
            partes.append(f"+{len(lst) - max_por_destino} fechas más")
    return "\n".join(partes)


def html_correo(alertas: list[dict], cfg: dict) -> str:
    g = agrupar(alertas)
    filas = []
    for dest, lst in g.items():
        filas.append(f"<h3 style='margin:18px 0 6px'>{cfg['origen']} → {dest} "
                     f"<small style='color:#777'>umbral {lst[0]['umbral']:.0f} €</small></h3><table cellpadding='4'>")
        for a in lst:
            url = enlace_google(cfg["origen"], dest, a["ida"], a["vuelta"], cfg["moneda"])
            motivo = "nuevo" if a["motivo"] == "nuevo" else f"bajada desde {a['anterior']:.0f} €"
            filas.append(f"<tr><td><b>{a['precio']:.0f} €</b></td><td>{fecha_corta(a['ida'])} → {fecha_corta(a['vuelta'])}</td>"
                         f"<td style='color:#777'>{motivo}</td><td><a href='{url}'>ver en Google Flights</a></td></tr>")
        filas.append("</table>")
    return (f"<div style='font-family:sans-serif'><p>{len(alertas)} avisos de precio "
            f"(ida y vuelta, 1 adulto, todas las aerolíneas).</p>{''.join(filas)}</div>")


# ─────────────────────────── envío ───────────────────────────
def enviar_correo(asunto: str, html: str, texto: str) -> bool:
    usuario, pwd, dest = os.getenv("SMTP_USUARIO"), os.getenv("SMTP_PASSWORD"), os.getenv("EMAIL_DESTINO")
    if not (usuario and pwd and dest):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, dest
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(os.getenv("SMTP_SERVIDOR", "smtp.gmail.com"), int(os.getenv("SMTP_PUERTO", "465"))) as s:
        s.login(usuario, pwd)
        s.send_message(msg)
    return True


def enviar_whatsapp(texto: str) -> bool:
    tel, key = os.getenv("WHATSAPP_TELEFONO"), os.getenv("WHATSAPP_APIKEY")
    if not (tel and key):
        return False
    # CallMeBot admite mensajes largos, pero se trocea por seguridad.
    trozos, actual = [], ""
    for ln in texto.split("\n"):
        if len(actual) + len(ln) > 1500:
            trozos.append(actual)
            actual = ""
        actual += ln + "\n"
    trozos.append(actual)
    for t in trozos:
        url = ("https://api.callmebot.com/whatsapp.php?"
               + urllib.parse.urlencode({"phone": tel, "text": t, "apikey": key}))
        with urllib.request.urlopen(url, timeout=30) as r:
            r.read()
        time.sleep(3)
    return True


def notificar(alertas: list[dict], cfg: dict, enviar: bool) -> None:
    mejor = min(alertas, key=lambda a: a["precio"])
    asunto = (f"✈️ {len(alertas)} vuelos baratos desde {cfg['origen']} — "
              f"desde {mejor['precio']:.0f}€ a {mejor['destino']}")
    wa = texto_whatsapp(alertas, cfg["origen"])
    if not enviar:
        print(asunto, "\n", wa, sep="")
        return
    canales = []
    try:
        if enviar_correo(asunto, html_correo(alertas, cfg), wa):
            canales.append("correo")
    except Exception as exc:
        print(f"Error enviando correo: {exc}", file=sys.stderr)
    try:
        if enviar_whatsapp(wa):
            canales.append("WhatsApp")
    except Exception as exc:
        print(f"Error enviando WhatsApp: {exc}", file=sys.stderr)
    print(f"Avisos enviados por: {', '.join(canales) or 'ningún canal (revisa los secrets)'}")


# ─────────────────────────── main ───────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-enviar", action="store_true")
    ap.add_argument("--prueba-aviso", action="store_true")
    args = ap.parse_args()
    cfg = cargar_config()
    hoy = date.today()

    if args.prueba_aviso:
        prueba = [{"destino": "LIS", "ida": (hoy + timedelta(days=30)).isoformat(),
                   "vuelta": (hoy + timedelta(days=33)).isoformat(), "precio": 39.0,
                   "motivo": "nuevo", "umbral": 60.0, "anterior": None}]
        notificar(prueba, cfg, enviar=not args.sin_enviar)
        return 0

    print(f"Consultando {len(cfg['umbrales'])} destinos × {len(cfg['duraciones'])} duraciones…")
    precios, ok, ko = consultar_precios(cfg, hoy)
    print(f"Peticiones OK: {ok}  fallidas: {ko}  precios leídos: {len(precios)}")
    if ok == 0:
        print("Ninguna petición funcionó: probablemente Google ha cambiado algo o nos ha bloqueado.", file=sys.stderr)
        return 1   # GitHub Actions marca el run en rojo y te avisa por correo

    estado = cargar_estado()
    alertas = evaluar(precios, estado, cfg["umbrales"], cfg["bajada_minima_eur"], hoy)
    print(f"Alertas nuevas: {len(alertas)}")
    if alertas:
        notificar(alertas, cfg, enviar=not args.sin_enviar)
    guardar_estado(estado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
