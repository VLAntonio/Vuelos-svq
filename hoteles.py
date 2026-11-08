"""
Búsqueda de alojamiento barato y bien valorado mediante la API de Google Hotels de SerpApi.
Google Hotels agrega Booking, Expedia, Hotels.com, Trip.com, la web del propio hotel, etc.

Plan gratuito de SerpApi: 250 búsquedas/mes. Este módulo lleva la cuenta en el estado
y no pasa del presupuesto configurado.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import ciudades

URL_API = "https://serpapi.com/search.json"
ORDEN_SERPAPI = {"relevancia": None, "precio": 3, "valoracion": 8, "opiniones": 13}


def activo(cfg: dict) -> bool:
    return bool(cfg.get("hoteles", {}).get("activado", False) and clave_api())


# ─────────────────────────── enlaces ───────────────────────────
def enlace_booking_hotel(nombre_hotel: str, ciudad: str, entrada: str, salida: str, adultos: int) -> str:
    q = {"ss": f"{nombre_hotel}, {ciudad}", "checkin": entrada, "checkout": salida,
         "group_adults": adultos, "no_rooms": 1, "group_children": 0, "lang": "es",
         "selected_currency": "EUR"}
    return "https://www.booking.com/searchresults.es.html?" + urllib.parse.urlencode(q)


def enlace_booking_filtrado(ciudad: str, entrada: str, salida: str, adultos: int,
                            max_noche: float, orden: str) -> str:
    """Búsqueda de Booking ya filtrada: nota 8+ y precio por noche máximo, con el orden indicado."""
    filtros = f"review_score=80;price=EUR-min-{int(max_noche)}-1"
    q = {"ss": ciudad, "checkin": entrada, "checkout": salida, "group_adults": adultos,
         "no_rooms": 1, "group_children": 0, "lang": "es", "selected_currency": "EUR",
         "nflt": filtros, "order": orden}
    return "https://www.booking.com/searchresults.es.html?" + urllib.parse.urlencode(q)


def enlace_google_hotel(nombre_hotel: str, ciudad: str, entrada: str, salida: str) -> str:
    texto = f"{nombre_hotel} {ciudad} del {entrada} al {salida}"
    return "https://www.google.com/travel/search?hl=es&curr=EUR&q=" + urllib.parse.quote(texto)


def enlace_google_filtrado(respuesta: dict, ciudad: str, entrada: str, salida: str, max_noche: float) -> str:
    url = (respuesta.get("search_metadata") or {}).get("google_hotels_url")
    if url and url.startswith("https://"):
        return url
    texto = f"alojamiento en {ciudad} del {entrada} al {salida} menos de {int(max_noche)} € la noche"
    return "https://www.google.com/travel/search?hl=es&curr=EUR&q=" + urllib.parse.quote(texto)


# ─────────────────────────── filtrado y orden ───────────────────────────
def _normalizar(vals: list[float]) -> list[float]:
    lo, hi = min(vals), max(vals)
    return [1.0 if hi == lo else (v - lo) / (hi - lo) for v in vals]


def filtrar(respuesta: dict, noches: int, umbral_noche: float, cfg_h: dict) -> list[dict]:
    """
    Devuelve TODOS los alojamientos de la respuesta que cumplen los criterios, ordenados por
    prioridad (ubicación, precio, instalaciones). Reglas de valoración:
      - con >= opiniones_minimas opiniones: nota >= valoracion_minima
      - "nuevos" (entre opiniones_minimas_nuevo y opiniones_minimas): nota >= valoracion_minima_nuevo
    """
    op_min = cfg_h.get("opiniones_minimas", 300)
    val_min = cfg_h.get("valoracion_minima", 4.3)
    op_nuevo = cfg_h.get("opiniones_minimas_nuevo", 20)
    val_nuevo = cfg_h.get("valoracion_minima_nuevo", 4.6)

    res = []
    vistos = set()
    for p in respuesta.get("properties", []):
        nombre = p.get("name", "?")
        if nombre in vistos:
            continue
        nota, opiniones = p.get("overall_rating"), int(p.get("reviews") or 0)
        if nota is None:
            continue
        if opiniones >= op_min:
            if nota < val_min:
                continue
            nuevo = False
        elif opiniones >= op_nuevo:
            if nota < val_nuevo:
                continue
            nuevo = True
        else:
            continue
        noche = (p.get("rate_per_night") or {}).get("extracted_lowest")
        total = (p.get("total_rate") or {}).get("extracted_lowest")
        if noche is None and total is not None:
            noche = total / noches
        if total is None and noche is not None:
            total = noche * noches
        if noche is None or noche <= 0 or noche > umbral_noche:
            continue
        vistos.add(nombre)
        res.append({"nombre": nombre, "nota": float(nota), "opiniones": opiniones, "nuevo": nuevo,
                    "noche": float(noche), "total": float(total),
                    "ubicacion": p.get("location_rating"),
                    "instalaciones": len(p.get("amenities") or []),
                    "tipo": p.get("type", "")})
    if not res:
        return res

    pesos = {"ubicacion": 0.45, "precio": 0.35, "instalaciones": 0.20, **cfg_h.get("prioridad", {})}
    ub = _normalizar([h["ubicacion"] if h["ubicacion"] is not None else 3.0 for h in res])
    pr = _normalizar([-h["noche"] for h in res])
    ins = _normalizar([min(h["instalaciones"], 25) for h in res])
    for h, a, b, c in zip(res, ub, pr, ins):
        h["puntuacion"] = pesos["ubicacion"] * a + pesos["precio"] * b + pesos["instalaciones"] * c
    res.sort(key=lambda h: (-h["puntuacion"], h["noche"]))
    return res


# ─────────────────────────── consulta ───────────────────────────
def clave_api() -> str:
    return (os.getenv("SERPAPI_KEY") or "").strip()


def _pedir(params: dict) -> dict:
    url = URL_API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # SerpApi explica el motivo en el cuerpo de la respuesta (clave inválida, cuenta sin verificar…)
        try:
            detalle = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            detalle = ""
        raise RuntimeError(f"HTTP {exc.code} de SerpApi: {detalle or exc.reason}") from None


def buscar(destino: str, entrada: str, salida: str, cfg_h: dict, umbral_noche: float,
           pedir=_pedir) -> tuple[list[dict], dict]:
    """Devuelve (alojamientos_que_cumplen, enlaces_filtrados)."""
    clave = clave_api()
    if not clave:
        raise RuntimeError("falta SERPAPI_KEY")
    ciudad = ciudades.ciudad_hotel(destino)
    noches = (date.fromisoformat(salida) - date.fromisoformat(entrada)).days
    adultos = cfg_h.get("adultos", 1)
    params = {
        "engine": "google_hotels", "q": f"alojamiento en {ciudad}",
        "check_in_date": entrada, "check_out_date": salida,
        "adults": adultos, "currency": "EUR", "gl": "es", "hl": "es",
        "rating": 8,                       # 4,0+ (luego se aplican los criterios finos)
        "max_price": int(umbral_noche) + 1,
        "api_key": clave,
    }
    orden = ORDEN_SERPAPI.get(cfg_h.get("orden_busqueda", "relevancia"))
    if orden:
        params["sort_by"] = orden
    resp = pedir(params)
    if "error" in resp and not resp.get("properties"):
        # "Google hasn't returned any results" no es un fallo: no hay nada bajo el umbral.
        if "results" not in str(resp["error"]).lower():
            raise RuntimeError(resp["error"])
        resp = {}
    hs = filtrar(resp, noches, umbral_noche, cfg_h)
    for h in hs:
        h["booking"] = enlace_booking_hotel(h["nombre"], ciudad, entrada, salida, adultos)
        h["google"] = enlace_google_hotel(h["nombre"], ciudad, entrada, salida)
    enlaces = {
        "booking_centricos": enlace_booking_filtrado(ciudad, entrada, salida, adultos, umbral_noche,
                                                     "distance_from_search"),
        "booking_valorados": enlace_booking_filtrado(ciudad, entrada, salida, adultos, umbral_noche,
                                                     "bayesian_review_score_and_price"),
        "google": enlace_google_filtrado(resp, ciudad, entrada, salida, umbral_noche),
    }
    return hs, enlaces


def completar_alertas(alertas: list[dict], cfg: dict, estado_h: dict, hoy: date, pedir=_pedir) -> bool:
    """
    Para la alerta más barata de cada destino añade "hoteles" (lista, quizá vacía) y
    "hoteles_enlaces". Las que no se buscan (límite por pasada, presupuesto o error) quedan
    sin la clave "hoteles". Devuelve True si hubo algún error.
    estado_h = {"mes": "2026-11", "usadas": n, "cache": {clave: {"dia", "res", "enlaces"}}}
    """
    if not activo(cfg):
        return False
    cfg_h = cfg["hoteles"]
    mes = hoy.strftime("%Y-%m")
    if estado_h.get("mes") != mes:
        estado_h["mes"], estado_h["usadas"] = mes, 0
    estado_h.setdefault("usadas", 0)
    cache = estado_h.setdefault("cache", {})
    for k in [k for k, v in cache.items()
              if (hoy - date.fromisoformat(v["dia"])).days > cfg_h.get("cache_dias", 3)]:
        del cache[k]

    mejores: dict[str, dict] = {}
    for a in sorted(alertas, key=lambda x: x["precio"]):
        mejores.setdefault(a["destino"], a)

    hechas, error = 0, False
    for a in sorted(mejores.values(), key=lambda x: x["precio"]):
        k = f"{a['destino']}|{a['ida']}|{a['vuelta']}"
        if k in cache and "enlaces" in cache[k]:
            a["hoteles"], a["hoteles_enlaces"] = cache[k]["res"], cache[k]["enlaces"]
            continue
        if hechas >= cfg_h.get("max_busquedas_por_ejecucion", 5):
            continue
        if estado_h["usadas"] >= cfg_h.get("presupuesto_mensual", 240):
            print("Presupuesto mensual de búsquedas de alojamiento agotado.")
            break
        umbral = cfg["umbral_noche"].get(a["destino"])
        if umbral is None:
            continue
        try:
            res, enlaces = buscar(a["destino"], a["ida"], a["vuelta"], cfg_h, umbral, pedir=pedir)
        except Exception as exc:
            # Probablemente clave inválida o servicio caído: se para aquí y se reintenta en la siguiente pasada.
            print(f"  ✗ alojamiento {a['destino']}: {exc}")
            error = True
            break
        estado_h["usadas"] += 1
        hechas += 1
        cache[k] = {"dia": hoy.isoformat(), "res": res, "enlaces": enlaces}
        a["hoteles"], a["hoteles_enlaces"] = res, enlaces
        print(f"  alojamiento {a['destino']}: {len(res)} cumplen los criterios")
    print(f"Búsquedas de alojamiento este mes: {estado_h['usadas']}/{cfg_h.get('presupuesto_mensual', 240)}")
    return error
