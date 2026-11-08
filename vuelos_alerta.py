#!/usr/bin/env python3
"""
Alertas de vuelos baratos desde Sevilla (+ alojamiento barato y bien valorado + coche).

Para cada destino y duración consulta el calendario de precios de Google Flights
(todas las aerolíneas) y avisa por Telegram (y/o correo) cuando:
  1) un precio baja del umbral (entra en zona barata), o
  2) estando ya bajo el umbral, vuelve a bajar respecto al último precio visto.
Si el precio sube por encima del umbral, la alerta se "rearma" para la próxima bajada.
Para los mejores chollos busca además alojamiento para esas mismas fechas (hoteles.py) y solo
avisa de los destinos donde vuelo y alojamiento están bajo el umbral, con los coches más
baratos (coches.py).

Uso:
  python vuelos_alerta.py                # ejecución normal
  python vuelos_alerta.py --sin-enviar   # imprime los avisos sin mandarlos
  python vuelos_alerta.py --prueba-aviso # manda un mensaje de prueba y sale

Variables de entorno (opcionales; sin ellas esa función se desactiva):
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
  SERPAPI_KEY                                   (búsqueda de alojamiento)
  RAPIDAPI_KEY                                  (precios de alquiler de coche)
  SMTP_USUARIO, SMTP_PASSWORD, EMAIL_DESTINO, [SMTP_SERVIDOR=smtp.gmail.com, SMTP_PUERTO=465]
"""
from __future__ import annotations

import argparse
import html
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

import ciudades
import coches
import hoteles

BASE = Path(__file__).resolve().parent
RUTA_CONFIG = BASE / "config.toml"
RUTA_ESTADO = BASE / "estado.json"


# ─────────────────────────── configuración ───────────────────────────
def cargar_config(ruta: Path = RUTA_CONFIG) -> dict:
    with open(ruta, "rb") as f:
        cfg = tomllib.load(f)
    umbrales: dict[str, float] = {}
    umbral_noche: dict[str, float] = {}
    for grupo in cfg.get("grupos", {}).values():
        for d in grupo["destinos"]:
            umbrales[d] = float(grupo["umbral"])
            if "umbral_hotel_noche" in grupo:
                umbral_noche[d] = float(grupo["umbral_hotel_noche"])
    for d, u in cfg.get("umbral_destino", {}).items():
        umbrales[d] = float(u)
    cfg["umbrales"] = umbrales
    cfg["umbral_noche"] = umbral_noche
    return cfg


# ─────────────────────────── estado ───────────────────────────
def cargar_estado(ruta: Path = RUTA_ESTADO) -> dict:
    if ruta.exists():
        est = json.loads(ruta.read_text(encoding="utf-8"))
        if "vuelos" not in est:          # formato antiguo: todo eran vuelos
            est = {"vuelos": est}
    else:
        est = {"vuelos": {}}
    est.setdefault("hoteles", {})
    est.setdefault("coches", {})
    return est


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

    hoy_s = hoy.isoformat()
    for k in [k for k in estado if k.split("|")[1] < hoy_s]:
        del estado[k]
    return alertas


# ─────────────────────────── Google Flights ───────────────────────────
def enlace_google_flights(origen: str, destino: str, ida: str, vuelta: str, moneda: str = "EUR") -> str:
    try:
        from fast_flights import FlightQuery, Passengers, create_query
        q = create_query(
            flights=[FlightQuery(date=ida, from_airport=origen, to_airport=destino),
                     FlightQuery(date=vuelta, from_airport=destino, to_airport=origen)],
            trip="round-trip", passengers=Passengers(adults=1), currency=moneda, language="es",
        )
        return q.url() + "&hl=es"
    except Exception:
        texto = f"Vuelos de {origen} a {destino} el {ida} con vuelta el {vuelta}"
        return "https://www.google.com/travel/flights?hl=es&curr=EUR&q=" + urllib.parse.quote(texto)


def enlace_skyscanner(origen: str, destino: str, ida: str, vuelta: str) -> str:
    f = lambda s: date.fromisoformat(s).strftime("%y%m%d")
    return (f"https://www.skyscanner.es/transporte/vuelos/{origen.lower()}/{destino.lower()}/"
            f"{f(ida)}/{f(vuelta)}/?adultsv2=1&cabinclass=economy&rtn=1")


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


# ─────────────────────────── selección de destinos ───────────────────────────
def seleccionar(alertas: list[dict], con_hoteles: bool) -> tuple[list[dict], list[str]]:
    """
    Agrupa las alertas por destino y decide qué se avisa.
    Con búsqueda de alojamiento: solo destinos cuyo mejor vuelo tiene alojamiento que cumple.
    Devuelve (paquetes, claves_pendientes). Las pendientes son de destinos cuyo alojamiento
    no se llegó a buscar (límite, presupuesto o error): se reintentan en la siguiente pasada.
    paquete = {"destino", "principal": alerta, "otras": [alertas]}
    """
    paquetes, pendientes = [], []
    for dest, lst in agrupar(alertas).items():
        if not con_hoteles:
            paquetes.append({"destino": dest, "principal": lst[0], "otras": lst[1:]})
            continue
        princ = next((a for a in lst if "hoteles" in a), None)
        if princ is None:
            pendientes += [clave(a["destino"], a["ida"], a["vuelta"]) for a in lst]
        elif princ["hoteles"]:
            paquetes.append({"destino": dest, "principal": princ, "otras": [a for a in lst if a is not princ]})
    paquetes.sort(key=lambda p: p["principal"]["precio"])
    return paquetes, pendientes


# ─────────────────────────── mensajes ───────────────────────────
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_larga(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}"


def noches(a: dict) -> int:
    return (date.fromisoformat(a["vuelta"]) - date.fromisoformat(a["ida"])).days


def eur(x: float) -> str:
    return f"{x:.0f} €"


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def agrupar(alertas: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for a in sorted(alertas, key=lambda x: (x["destino"], x["precio"], x["ida"])):
        g.setdefault(a["destino"], []).append(a)
    return dict(sorted(g.items(), key=lambda kv: kv[1][0]["precio"]))


def enlace(url: str, texto: str) -> str:
    return f'<a href="{html.escape(url)}">{html.escape(texto)}</a>'


def bloque_paquete(paq: dict, origen: str, cfg: dict) -> list[str]:
    a = paq["principal"]
    dest = a["destino"]
    pais = ciudades.pais(dest)
    motivo = "🆕 nuevo" if a["motivo"] == "nuevo" else f"⬇️ antes {eur(a['anterior'])}"
    L = [
        "",
        f"📍 <b>{html.escape(ciudades.nombre(dest))}</b>{' (' + pais + ')' if pais else ''} · {dest}",
        f"📅 {fecha_larga(a['ida'])} → {fecha_larga(a['vuelta'])} ({noches(a)} noches)",
        f"✈️ <b>{eur(a['precio'])}</b> ida y vuelta · {motivo}",
        f"   🔗 {enlace(enlace_google_flights(origen, dest, a['ida'], a['vuelta']), 'Google Flights')}"
        f" · {enlace(enlace_skyscanner(origen, dest, a['ida'], a['vuelta']), 'Skyscanner')}",
    ]
    total_viaje = a["precio"]

    hs = a.get("hoteles")
    if hs:
        umbral = cfg["umbral_noche"].get(dest)
        tope = cfg.get("hoteles", {}).get("max_mostrados", 0) or len(hs)
        L.append(f"🏨 <b>{len(hs)} alojamientos</b> de menos de {eur(umbral)}/noche, "
                 f"por ubicación, precio e instalaciones:")
        for i, h in enumerate(hs[:tope], 1):
            ub = f"{h['ubicacion']:.1f}" if h.get("ubicacion") is not None else "–"
            L.append(f" {i}. {enlace(h['booking'], h['nombre'])}{' 🆕' if h.get('nuevo') else ''}"
                     f" · <b>{eur(h['noche'])}</b>/noche · ⭐{h['nota']:.1f} ({miles(h['opiniones'])})"
                     f" · 📍{ub} · 🛎{h['instalaciones']} · {enlace(h['google'], 'comparar')}")
        if len(hs) > tope:
            L.append(f"    …y {len(hs) - tope} más en los enlaces de abajo")
        e = a.get("hoteles_enlaces") or {}
        if e:
            L.append(f"   🔎 Ver más, ya filtrados: {enlace(e['booking_centricos'], 'Booking · más céntricos')}"
                     f" · {enlace(e['booking_valorados'], 'Booking · mejor nota y precio')}"
                     f" · {enlace(e['google'], 'Google Hotels')}")
        total_viaje += min(h["total"] for h in hs)

    coches_lst = paq.get("coches")
    if coches_lst:
        L.append(f"🚗 Coches más baratos (aeropuerto, {noches(a)} días):")
        for c in coches_lst:
            detalles = " · ".join(x for x in (c["categoria"], c["cambio"]) if x)
            L.append(f" • {html.escape(c['modelo'])} o similar{' (' + html.escape(detalles) + ')' if detalles else ''}"
                     f"{' · ' + html.escape(c['empresa']) if c['empresa'] else ''}"
                     f" — <b>{eur(c['total'])}</b> ({eur(c['dia'])}/día)")
    if paq.get("coches_enlace"):
        L.append(f"   🔎 {enlace(paq['coches_enlace'], 'Todos los coches por precio (Kayak)')}")

    if hs:
        extra = f" · {eur(total_viaje + coches_lst[0]['total'])} con coche" if coches_lst else ""
        L.append(f"💰 <b>Vuelo + alojamiento desde {eur(total_viaje)}</b>{extra}")

    otras = paq.get("otras") or []
    if otras:
        txt = ", ".join(f"{fecha_larga(o['ida'])}→{fecha_larga(o['vuelta'])} {eur(o['precio'])}" for o in otras[:5])
        nota = " (alojamiento sin comprobar)" if hs is not None else ""
        L.append(f"   ✈️ Otras fechas con vuelo barato{nota}: {txt}{'…' if len(otras) > 5 else ''}")
    return L


def texto_mensaje(paquetes: list[dict], origen: str, cfg: dict) -> str:
    """Mensaje en HTML de Telegram. Cada línea es autocontenida (se puede trocear por líneas)."""
    cfg_h = cfg.get("hoteles", {})
    n = len(paquetes)
    partes = [f"<b>✈️ Chollos desde Sevilla</b> · {n} destino{'s' if n != 1 else ''}"]
    if any(p["principal"].get("hoteles") for p in paquetes):
        partes.append(f"<i>Alojamientos: ⭐ nota ≥{cfg_h.get('valoracion_minima', 4.3)} con "
                      f"{cfg_h.get('opiniones_minimas', 300)}+ opiniones, o ≥{cfg_h.get('valoracion_minima_nuevo', 4.6)} "
                      f"si son nuevos (🆕). 📍 nota de ubicación · 🛎 nº de servicios.</i>")
    for paq in paquetes:
        partes += bloque_paquete(paq, origen, cfg)
    return "\n".join(partes)


# ─────────────────────────── envío ───────────────────────────
def trocear(texto: str, maximo: int = 3500) -> list[str]:
    trozos, actual = [], ""
    for ln in texto.split("\n"):
        if actual and len(actual) + len(ln) > maximo:
            trozos.append(actual)
            actual = ""
        actual += ln + "\n"
    trozos.append(actual)
    return trozos


def enviar_telegram(texto: str) -> bool:
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    for t in trocear(texto):
        datos = urllib.parse.urlencode({"chat_id": chat, "text": t, "parse_mode": "HTML",
                                        "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        time.sleep(1)
    return True


def enviar_correo(asunto: str, cuerpo_html: str) -> bool:
    usuario, pwd, dest = os.getenv("SMTP_USUARIO"), os.getenv("SMTP_PASSWORD"), os.getenv("EMAIL_DESTINO")
    if not (usuario and pwd and dest):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, dest
    msg.set_content("Abre este correo en un cliente que muestre HTML.")
    msg.add_alternative(f"<div style='font-family:sans-serif'>{cuerpo_html.replace(chr(10), '<br>')}</div>",
                        subtype="html")
    with smtplib.SMTP_SSL(os.getenv("SMTP_SERVIDOR", "smtp.gmail.com"), int(os.getenv("SMTP_PUERTO", "465"))) as s:
        s.login(usuario, pwd)
        s.send_message(msg)
    return True


def notificar(paquetes: list[dict], cfg: dict, enviar: bool) -> None:
    mejor = paquetes[0]["principal"]
    asunto = (f"✈️ {len(paquetes)} chollos desde Sevilla — "
              f"desde {eur(mejor['precio'])} a {ciudades.nombre(mejor['destino'])}")
    texto = texto_mensaje(paquetes, cfg["origen"], cfg)
    if not enviar:
        print(asunto, "\n", texto, sep="")
        return
    canales = []
    for nombre, fn in (("Telegram", lambda: enviar_telegram(texto)),
                       ("correo", lambda: enviar_correo(asunto, texto))):
        try:
            if fn():
                canales.append(nombre)
        except Exception as exc:
            print(f"Error enviando por {nombre}: {exc}", file=sys.stderr)
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
        # Vuelo ficticio a Lisboa, con búsqueda REAL de alojamiento y coches si hay claves
        # (gasta 1 búsqueda de SerpApi y hasta 2 de RapidAPI).
        ida = hoy + timedelta(days=30)
        prueba = [{"destino": "LIS", "ida": ida.isoformat(), "vuelta": (ida + timedelta(days=3)).isoformat(),
                   "precio": 39.0, "motivo": "nuevo", "umbral": 60.0, "anterior": None}]
        hoteles.completar_alertas(prueba, cfg, {}, hoy)
        paquetes = [{"destino": "LIS", "principal": prueba[0], "otras": []}]
        coches.completar(paquetes, cfg, {}, hoy)
        notificar(paquetes, cfg, enviar=not args.sin_enviar)
        return 0

    print(f"Consultando {len(cfg['umbrales'])} destinos × {len(cfg['duraciones'])} duraciones…")
    precios, ok, ko = consultar_precios(cfg, hoy)
    print(f"Peticiones OK: {ok}  fallidas: {ko}  precios leídos: {len(precios)}")
    if ok == 0:
        print("Ninguna petición funcionó: probablemente Google ha cambiado algo o nos ha bloqueado.", file=sys.stderr)
        return 1

    estado = cargar_estado()
    antes = dict(estado["vuelos"])
    alertas = evaluar(precios, estado["vuelos"], cfg["umbrales"], cfg["bajada_minima_eur"], hoy)
    print(f"Vuelos bajo el umbral (nuevos o más baratos): {len(alertas)}")

    con_hoteles = hoteles.activo(cfg) and not args.sin_enviar
    errores = False
    if alertas and con_hoteles:
        errores |= hoteles.completar_alertas(alertas, cfg, estado["hoteles"], hoy)
    paquetes, pendientes = seleccionar(alertas, con_hoteles)
    for k in pendientes:                       # se reconsideran en la siguiente pasada
        if k in antes:
            estado["vuelos"][k] = antes[k]
        else:
            estado["vuelos"].pop(k, None)
    if con_hoteles:
        print(f"Destinos con vuelo y alojamiento bajo el umbral: {len(paquetes)}"
              f"  (pendientes para la próxima pasada: {len({k.split('|')[0] for k in pendientes})})")
    if paquetes and not args.sin_enviar:
        errores |= coches.completar(paquetes, cfg, estado["coches"], hoy)
    if paquetes:
        notificar(paquetes, cfg, enviar=not args.sin_enviar)
    guardar_estado(estado)
    if errores:
        print("Hubo errores en la búsqueda de alojamiento o coches (ver arriba).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
