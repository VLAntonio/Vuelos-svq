"""Tests sin red (no necesitan fast-flights ni claves). Ejecuta: python -m unittest -v"""
import json
import os
import pathlib
import tempfile
import unittest
from datetime import date

import ciudades
import coches
import hoteles
import vuelos_alerta as va

HOY = date(2026, 11, 7)
U = {"LIS": 60.0, "MAD": 50.0}


def p(dest, precio, ida="2026-12-01", vuelta="2026-12-04"):
    return {"destino": dest, "ida": ida, "vuelta": vuelta, "precio": precio}


# ─────────────────────────── vuelos ───────────────────────────
class Vuelos(unittest.TestCase):
    def test_entra_bajo_umbral(self):
        a = va.evaluar([p("LIS", 45)], {}, U, 2, HOY)
        self.assertEqual([x["motivo"] for x in a], ["nuevo"])

    def test_por_encima_o_igual_no_avisa(self):
        self.assertEqual(va.evaluar([p("LIS", 75), p("LIS", 60, "2026-12-02")], {}, U, 2, HOY), [])

    def test_sigue_bajando(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        a = va.evaluar([p("LIS", 40)], est, U, 2, HOY)
        self.assertEqual((a[0]["motivo"], a[0]["anterior"]), ("bajada", 45))

    def test_bajada_insignificante_igual_o_sube_no_avisa(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        for precio in (44, 44, 52):
            self.assertEqual(va.evaluar([p("LIS", precio)], est, U, 2, HOY), [])

    def test_rearme_al_salir_y_volver(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        va.evaluar([p("LIS", 70)], est, U, 2, HOY)
        self.assertEqual(va.evaluar([p("LIS", 58)], est, U, 2, HOY)[0]["motivo"], "nuevo")

    def test_limpia_fechas_pasadas(self):
        est = {va.clave("LIS", "2026-11-01", "2026-11-04"): {"precio": 30, "bajo_umbral": True}}
        va.evaluar([], est, U, 2, HOY)
        self.assertEqual(est, {})

    def test_config_real(self):
        cfg = va.cargar_config()
        self.assertEqual(len(cfg["umbrales"]), 87)
        self.assertEqual(set(cfg["umbrales"]) - set(ciudades.AEROPUERTOS), set())
        self.assertEqual(set(cfg["umbrales"]), set(cfg["umbral_noche"]))

    def test_estado_formato_antiguo(self):
        with tempfile.TemporaryDirectory() as d:
            r = pathlib.Path(d) / "e.json"
            r.write_text(json.dumps({"LIS|2026-12-01|2026-12-04": {"precio": 40, "bajo_umbral": True}}))
            e = va.cargar_estado(r)
            self.assertIn("LIS|2026-12-01|2026-12-04", e["vuelos"])
            self.assertEqual((e["hoteles"], e["coches"]), ({}, {}))


# ─────────────────────────── alojamiento ───────────────────────────
def prop(nombre, nota, opiniones, noche, ubic=None, servicios=0):
    return {"name": nombre, "overall_rating": nota, "reviews": opiniones,
            "rate_per_night": {"extracted_lowest": noche}, "total_rate": {"extracted_lowest": noche * 3},
            "location_rating": ubic, "amenities": ["x"] * servicios}


RESP = {"search_metadata": {"google_hotels_url": "https://www.google.com/travel/search?q=lisboa"},
        "properties": [
            prop("Caro", 4.8, 900, 80, 4.9, 20),             # fuera: precio
            prop("Nota baja", 4.1, 900, 20, 4.9, 20),        # fuera: nota
            prop("Pocas opiniones", 4.9, 12, 25, 4.9, 20),   # fuera: < 20 opiniones
            prop("Nuevo flojo", 4.5, 150, 25, 4.9, 20),      # fuera: nuevo con 4,5 (hace falta más)
            prop("Nuevo top", 4.7, 150, 40, 4.0, 10),        # dentro (nuevo)
            prop("Céntrico & bueno", 4.4, 1234, 45, 4.9, 15),  # dentro
            prop("Barato lejos", 4.3, 400, 25, 3.2, 5),       # dentro
            prop("Céntrico & bueno", 4.4, 1234, 45, 4.9, 15),  # duplicado
        ]}


class Alojamiento(unittest.TestCase):
    def setUp(self):
        os.environ["SERPAPI_KEY"] = "x"
        os.environ.pop("RAPIDAPI_KEY", None)
        self.cfg = va.cargar_config()
        self.llamadas = []

    def pedir(self, params):
        self.llamadas.append(params)
        return RESP

    def test_reglas_de_valoracion_y_orden(self):
        hs = hoteles.filtrar(RESP, 3, 50, self.cfg["hoteles"])
        # ubicación pesa más que precio: el barato pero mal situado queda el último
        self.assertEqual([h["nombre"] for h in hs], ["Céntrico & bueno", "Nuevo top", "Barato lejos"])
        self.assertTrue(hs[1]["nuevo"])
        self.assertFalse(hs[0]["nuevo"])

    def test_prioridad_configurable(self):
        solo_precio = {**self.cfg["hoteles"], "prioridad": {"ubicacion": 0, "precio": 1, "instalaciones": 0}}
        hs = hoteles.filtrar(RESP, 3, 50, solo_precio)
        self.assertEqual(hs[0]["nombre"], "Barato lejos")

    def test_enlaces_filtrados(self):
        _, e = hoteles.buscar("LIS", "2026-12-01", "2026-12-04", self.cfg["hoteles"], 50, pedir=self.pedir)
        self.assertIn("nflt=review_score%3D80%3Bprice%3DEUR-min-50-1", e["booking_centricos"])
        self.assertIn("order=distance_from_search", e["booking_centricos"])
        self.assertIn("order=bayesian_review_score_and_price", e["booking_valorados"])
        self.assertEqual(e["google"], "https://www.google.com/travel/search?q=lisboa")
        self.assertEqual(self.llamadas[0]["max_price"], 51)
        self.assertNotIn("sort_by", self.llamadas[0])

    def test_solo_destinos_con_alojamiento(self):
        alertas = va.evaluar([p("LIS", 30), p("LIS", 33, "2026-12-02", "2026-12-05"), p("MAD", 25)], {}, U, 2, HOY)
        vacio = lambda params: {"properties": []} if "Madrid" in params["q"] else RESP
        hoteles.completar_alertas(alertas, self.cfg, {}, HOY, pedir=vacio)
        paquetes, pendientes = va.seleccionar(alertas, True)
        self.assertEqual([x["destino"] for x in paquetes], ["LIS"])   # MAD sin alojamiento: no se avisa
        self.assertEqual(len(paquetes[0]["otras"]), 1)
        self.assertEqual(pendientes, [])

    def test_pendientes_si_no_se_busca(self):
        cfg = {**self.cfg, "hoteles": {**self.cfg["hoteles"], "max_busquedas_por_ejecucion": 1}}
        alertas = va.evaluar([p("LIS", 30), p("MAD", 25)], {}, U, 2, HOY)
        hoteles.completar_alertas(alertas, cfg, {}, HOY, pedir=self.pedir)
        paquetes, pendientes = va.seleccionar(alertas, True)
        self.assertEqual([x["destino"] for x in paquetes], ["MAD"])   # el más barato se busca primero
        self.assertEqual(pendientes, ["LIS|2026-12-01|2026-12-04"])

    def test_error_para_y_no_gasta(self):
        alertas = va.evaluar([p("LIS", 30), p("MAD", 25)], {}, U, 2, HOY)
        est = {}

        def falla(params):
            raise RuntimeError("Invalid API key")
        self.assertTrue(hoteles.completar_alertas(alertas, self.cfg, est, HOY, pedir=falla))
        self.assertEqual(est["usadas"], 0)
        self.assertEqual(len(va.seleccionar(alertas, True)[1]), 2)

    def test_cache_y_presupuesto(self):
        est = {}
        a1 = va.evaluar([p("LIS", 30)], {}, U, 2, HOY)
        hoteles.completar_alertas(a1, self.cfg, est, HOY, pedir=self.pedir)
        a2 = va.evaluar([p("LIS", 30)], {}, U, 2, HOY)
        hoteles.completar_alertas(a2, self.cfg, est, HOY, pedir=self.pedir)
        self.assertEqual((len(self.llamadas), est["usadas"]), (1, 1))
        est2 = {"mes": HOY.strftime("%Y-%m"), "usadas": 240}
        a3 = va.evaluar([p("MAD", 30)], {}, U, 2, HOY)
        hoteles.completar_alertas(a3, self.cfg, est2, HOY, pedir=self.pedir)
        self.assertNotIn("hoteles", a3[0])

    def test_sin_resultados_no_es_error(self):
        alertas = va.evaluar([p("LIS", 30)], {}, U, 2, HOY)
        err = hoteles.completar_alertas(alertas, self.cfg, {}, HOY,
                                        pedir=lambda q: {"error": "Google hasn't returned any results for this query."})
        self.assertFalse(err)
        self.assertEqual(alertas[0]["hoteles"], [])


# ─────────────────────────── coches ───────────────────────────
DEST = {"status": True, "data": [
    {"name": "Lisboa", "type": "city", "coordinates": {"latitude": 38.72, "longitude": -9.14}},
    {"name": "Aeropuerto de Lisboa (LIS)", "type": "airport", "iata_code": "LIS",
     "coordinates": {"latitude": 38.7742, "longitude": -9.1342}},
]}
CARS = {"status": True, "data": {"search_results": [
    {"vehicle_info": {"v_name": "Fiat 500", "group": "Mini", "transmission": "Manual"},
     "pricing_info": {"price": 45.6, "currency": "EUR"}, "supplier_info": {"name": "Goldcar"}},
    {"vehicle_info": {"v_name": "Seat Ibiza", "group": "Económico", "transmission": "Manual"},
     "pricing_info": {"drive_away_price": 38.1, "price": 38.1, "currency": "EUR"}, "supplier_info": {"name": "Centauro"}},
    {"vehicle_info": {"v_name": "Fiat 500", "group": "Mini"}, "pricing_info": {"price": 50}, "supplier_info": {"name": "Goldcar"}},
    {"vehicle_info": {"v_name": "VW Polo"}, "pricing_info": {"price": 61}, "supplier_info": {"name": "Sixt"}},
    {"vehicle_info": {"v_name": "Opel Corsa"}, "pricing_info": {"price": 70}, "supplier_info": {"name": "Europcar"}},
]}}


class Coches(unittest.TestCase):
    def setUp(self):
        self.cfg = va.cargar_config()
        self.llamadas = []

    def get(self, path, params):
        self.llamadas.append((path, params))
        return DEST if "searchDestination" in path else CARS

    def paquete(self):
        return [{"destino": "LIS", "principal": {**p("LIS", 30), "motivo": "nuevo", "anterior": None}, "otras": []}]

    def test_kayak_sin_clave(self):
        os.environ.pop("RAPIDAPI_KEY", None)
        paq = self.paquete()
        coches.completar(paq, self.cfg, {}, HOY, get=self.get)
        self.assertEqual(paq[0]["coches_enlace"],
                         "https://www.kayak.es/cars/LIS/2026-12-01-12h/2026-12-04-10h?sort=price_a")
        self.assertNotIn("coches", paq[0])
        self.assertEqual(self.llamadas, [])

    def test_mas_baratos_con_clave(self):
        os.environ["RAPIDAPI_KEY"] = "x"
        paq, est = self.paquete(), {}
        self.assertFalse(coches.completar(paq, self.cfg, est, HOY, get=self.get))
        cs = paq[0]["coches"]
        self.assertEqual([(c["modelo"], c["empresa"], round(c["total"])) for c in cs],
                         [("Seat Ibiza", "Centauro", 38), ("Fiat 500", "Goldcar", 46), ("VW Polo", "Sixt", 61)])
        self.assertEqual(round(cs[0]["dia"], 1), 12.7)
        self.assertEqual(est["coords"]["LIS"], [38.7742, -9.1342])   # elige el aeropuerto, no la ciudad
        busqueda = self.llamadas[1][1]
        self.assertEqual((busqueda["pick_up_date"], busqueda["drop_off_date"]), ("2026-12-01", "2026-12-04"))
        # segunda vez: caché, sin llamadas
        n = len(self.llamadas)
        paq2 = self.paquete()
        coches.completar(paq2, self.cfg, est, HOY, get=self.get)
        self.assertEqual(len(self.llamadas), n)
        self.assertEqual(paq2[0]["coches"], cs)
        os.environ.pop("RAPIDAPI_KEY")


# ─────────────────────────── mensaje completo ───────────────────────────
class Mensaje(unittest.TestCase):
    def test_mensaje_completo(self):
        os.environ["SERPAPI_KEY"] = "x"
        os.environ["RAPIDAPI_KEY"] = "x"
        cfg = va.cargar_config()
        alertas = va.evaluar([p("LIS", 30), p("LIS", 33, "2026-12-08", "2026-12-11")], {}, U, 2, HOY)
        hoteles.completar_alertas(alertas, cfg, {}, HOY, pedir=lambda q: RESP)
        paquetes, _ = va.seleccionar(alertas, True)
        coches.completar(paquetes, cfg, {}, HOY, get=lambda path, q: DEST if "Destination" in path else CARS)
        txt = va.texto_mensaje(paquetes, "SVQ", cfg)
        self.assertIn("Lisboa</b> (Portugal) · LIS", txt)
        self.assertIn("mar 1 dic → vie 4 dic (3 noches)", txt)
        self.assertIn("3 alojamientos</b> de menos de 50 €/noche", txt)
        self.assertIn("Céntrico &amp; bueno</a> · <b>45 €</b>/noche · ⭐4.4 (1.234) · 📍4.9 · 🛎15", txt)
        self.assertIn("Nuevo top</a> 🆕", txt)
        self.assertIn("Booking · más céntricos", txt)
        self.assertIn("Seat Ibiza o similar (Económico · Manual) · Centauro — <b>38 €</b> (13 €/día)", txt)
        self.assertIn("kayak.es/cars/LIS", txt)
        self.assertIn("Vuelo + alojamiento desde 105 €</b> · 143 € con coche", txt)  # 30 + 25*3 (+38)
        self.assertIn("Otras fechas con vuelo barato (alojamiento sin comprobar): mar 8 dic→vie 11 dic 33 €", txt)
        for t in va.trocear(txt):
            self.assertLessEqual(len(t), 4096)
        os.environ.pop("RAPIDAPI_KEY")


if __name__ == "__main__":
    unittest.main()
