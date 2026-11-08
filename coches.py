"""
Alquiler de coche: los más baratos con recogida y devolución en el aeropuerto de destino.

- Siempre se genera un enlace a Kayak (comparador: Rentalcars, DiscoverCars, Europcar,
  Goldcar, Sixt…) con la búsqueda ya hecha y ordenada por precio.
- Si hay RAPIDAPI_KEY, se consultan además los precios concretos con la API no oficial
  "Booking COM" (DataCrawler, booking-com15) de RapidAPI, que devuelve los coches de
  Booking Cars (antes Rentalcars).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

HOST = "booking-com15.p.rapidapi.com"


def activo(cfg: dict) -> bool:
    return bool(cfg.get("coches", {}).get("activado", False))


def clave_api() -> str:
    return (os.getenv("RAPIDAPI_KEY") or "").strip()


def con_precios() -> bool:
    return bool(clave_api())


def enlace_kayak(aeropuerto: str, ida: str, vuelta: str, cfg_c: dict) -> str:
    hr = int(cfg_c.get("hora_recogida", "12:00").split(":")[0])
    hd = int(cfg_c.get("hora_devolucion", "10:00").split(":")[0])
    return f"https://www.kayak.es/cars/{aeropuerto}/{ida}-{hr}h/{vuelta}-{hd}h?sort=price_a"


def _get(path: str, params: dict) -> dict:
    url = f"https://{HOST}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-rapidapi-key": clave_api(), "x-rapidapi-host": HOST})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detalle = json.loads(exc.read().decode("utf-8")).get("message", "")
        except Exception:
            detalle = ""
        raise RuntimeError(f"HTTP {exc.code} de RapidAPI: {detalle or exc.reason}") from None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def elegir_ubicacion(respuesta: dict, aeropuerto: str) -> tuple[float, float] | None:
    """De la respuesta de searchDestination elige el aeropuerto (o lo primero con coordenadas)."""
    datos = respuesta.get("data") or []
    if isinstance(datos, dict):
        datos = [datos]
    candidatos = []
    for d in datos:
        c = d.get("coordinates") or {}
        lat, lon = _num(c.get("latitude")), _num(c.get("longitude"))
        if lat is None or lon is None:
            continue
        texto = json.dumps(d, ensure_ascii=False).upper()
        es_aeropuerto = str(d.get("type", "")).lower() == "airport" or "AIRPORT" in texto or "AEROPUERTO" in texto
        prioridad = (0 if aeropuerto.upper() in texto and es_aeropuerto else 1 if es_aeropuerto else 2)
        candidatos.append((prioridad, lat, lon))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: x[0])
    return candidatos[0][1], candidatos[0][2]


def extraer_coches(respuesta: dict, dias: int, maximo: int) -> list[dict]:
    """Extrae los coches más baratos de la respuesta de searchCarRentals."""
    datos = respuesta.get("data") or {}
    lista = datos.get("search_results") if isinstance(datos, dict) else datos
    coches = []
    for r in lista or []:
        v = r.get("vehicle_info") or {}
        p = r.get("pricing_info") or {}
        s = r.get("supplier_info") or {}
        precio = next((x for x in (_num(p.get("drive_away_price")), _num(p.get("price")),
                                   _num(p.get("base_price"))) if x), None)
        if not precio:
            continue
        moneda = p.get("currency") or "EUR"
        coches.append({
            "modelo": v.get("v_name") or v.get("name") or "Coche",
            "categoria": v.get("group") or v.get("label") or "",
            "cambio": v.get("transmission") or "",
            "empresa": s.get("name") or "",
            "total": precio, "dia": precio / max(dias, 1), "moneda": moneda,
        })
    coches.sort(key=lambda c: c["total"])
    # sin repetir el mismo modelo con la misma empresa
    vistos, res = set(), []
    for c in coches:
        k = (c["modelo"], c["empresa"])
        if k in vistos:
            continue
        vistos.add(k)
        res.append(c)
        if len(res) >= maximo:
            break
    return res


def completar(paquetes: list[dict], cfg: dict, estado_c: dict, hoy: date, get=_get) -> bool:
    """
    Añade a cada paquete "coches_enlace" (siempre) y "coches" (lista) si hay RAPIDAPI_KEY.
    estado_c = {"mes", "usadas", "coords": {IATA: [lat, lon]}, "cache": {clave: {"dia", "res"}}}
    Devuelve True si hubo algún error.
    """
    if not activo(cfg):
        return False
    cfg_c = cfg["coches"]
    for paq in paquetes:
        a = paq["principal"]
        paq["coches_enlace"] = enlace_kayak(a["destino"], a["ida"], a["vuelta"], cfg_c)
    if not con_precios():
        return False

    mes = hoy.strftime("%Y-%m")
    if estado_c.get("mes") != mes:
        estado_c["mes"], estado_c["usadas"] = mes, 0
    estado_c.setdefault("usadas", 0)
    coords = estado_c.setdefault("coords", {})
    cache = estado_c.setdefault("cache", {})
    for k in [k for k, v in cache.items()
              if (hoy - date.fromisoformat(v["dia"])).days > cfg_c.get("cache_dias", 2)]:
        del cache[k]
    presupuesto = cfg_c.get("presupuesto_mensual", 40)

    for paq in paquetes:
        a = paq["principal"]
        k = f"{a['destino']}|{a['ida']}|{a['vuelta']}"
        if k in cache:
            paq["coches"] = cache[k]["res"]
            continue
        try:
            if a["destino"] not in coords:
                if estado_c["usadas"] >= presupuesto:
                    break
                estado_c["usadas"] += 1
                ub = elegir_ubicacion(get("/api/v1/cars/searchDestination", {"query": a["destino"]}),
                                      a["destino"])
                if ub is None:
                    print(f"  ✗ coches {a['destino']}: no se encontró el aeropuerto")
                    continue
                coords[a["destino"]] = list(ub)
            if estado_c["usadas"] >= presupuesto:
                print("Presupuesto mensual de búsquedas de coches agotado.")
                break
            lat, lon = coords[a["destino"]]
            estado_c["usadas"] += 1
            resp = get("/api/v1/cars/searchCarRentals", {
                "pick_up_latitude": lat, "pick_up_longitude": lon,
                "drop_off_latitude": lat, "drop_off_longitude": lon,
                "pick_up_date": a["ida"], "drop_off_date": a["vuelta"],
                "pick_up_time": cfg_c.get("hora_recogida", "12:00"),
                "drop_off_time": cfg_c.get("hora_devolucion", "10:00"),
                "driver_age": cfg_c.get("edad_conductor", 30),
                "currency_code": "EUR", "languagecode": "es",
            })
            if resp.get("status") is False:
                raise RuntimeError(resp.get("message") or "respuesta con status false")
            dias = (date.fromisoformat(a["vuelta"]) - date.fromisoformat(a["ida"])).days
            res = extraer_coches(resp, dias, cfg_c.get("max_mostrados", 3))
        except Exception as exc:
            print(f"  ✗ coches {a['destino']}: {exc}")
            return True
        cache[k] = {"dia": hoy.isoformat(), "res": res}
        paq["coches"] = res
        print(f"  coches {a['destino']}: {len(res)} opciones")
    print(f"Búsquedas de coches este mes: {estado_c['usadas']}/{presupuesto}")
    return False
