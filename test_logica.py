"""Tests de la lógica de alertas (no necesitan red ni fast-flights). Ejecuta: python -m unittest -v"""
import unittest
from datetime import date

import vuelos_alerta as va

HOY = date(2026, 11, 7)
U = {"LIS": 60.0, "MAD": 50.0}


def p(dest, precio, ida="2026-12-01", vuelta="2026-12-04"):
    return {"destino": dest, "ida": ida, "vuelta": vuelta, "precio": precio}


class Logica(unittest.TestCase):
    def test_entra_bajo_umbral(self):
        est = {}
        a = va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        self.assertEqual([x["motivo"] for x in a], ["nuevo"])

    def test_por_encima_no_avisa(self):
        self.assertEqual(va.evaluar([p("LIS", 75)], {}, U, 2, HOY), [])

    def test_igual_al_umbral_no_avisa(self):
        self.assertEqual(va.evaluar([p("LIS", 60)], {}, U, 2, HOY), [])

    def test_sigue_bajando(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        a = va.evaluar([p("LIS", 40)], est, U, 2, HOY)
        self.assertEqual(a[0]["motivo"], "bajada")
        self.assertEqual(a[0]["anterior"], 45)

    def test_bajada_insignificante_no_avisa(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        self.assertEqual(va.evaluar([p("LIS", 44)], est, U, 2, HOY), [])

    def test_igual_o_sube_no_avisa(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        self.assertEqual(va.evaluar([p("LIS", 45)], est, U, 2, HOY), [])
        self.assertEqual(va.evaluar([p("LIS", 52)], est, U, 2, HOY), [])

    def test_bajada_tras_subida_dentro_de_zona(self):
        # 45 -> 52 (sin aviso) -> 48: baja respecto al que tenía (52)
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        va.evaluar([p("LIS", 52)], est, U, 2, HOY)
        a = va.evaluar([p("LIS", 48)], est, U, 2, HOY)
        self.assertEqual(a[0]["motivo"], "bajada")

    def test_rearme_al_salir_y_volver(self):
        est = {}
        va.evaluar([p("LIS", 45)], est, U, 2, HOY)
        self.assertEqual(va.evaluar([p("LIS", 70)], est, U, 2, HOY), [])
        a = va.evaluar([p("LIS", 58)], est, U, 2, HOY)
        self.assertEqual(a[0]["motivo"], "nuevo")

    def test_fechas_independientes(self):
        a = va.evaluar([p("LIS", 45, "2026-12-01"), p("LIS", 45, "2026-12-02")], {}, U, 2, HOY)
        self.assertEqual(len(a), 2)

    def test_limpia_fechas_pasadas(self):
        est = {va.clave("LIS", "2026-11-01", "2026-11-04"): {"precio": 30, "bajo_umbral": True}}
        va.evaluar([], est, U, 2, HOY)
        self.assertEqual(est, {})

    def test_config_real(self):
        cfg = va.cargar_config()
        self.assertEqual(len(cfg["umbrales"]), 87)
        self.assertEqual(cfg["umbrales"]["IST"], 80)

    def test_mensajes(self):
        est = {}
        alertas = va.evaluar([p("LIS", 39), p("MAD", 30), p("LIS", 41, "2026-12-05", "2026-12-08")], est, U, 2, HOY)
        wa = va.texto_whatsapp(alertas, "SVQ")
        self.assertLess(wa.index("SVQ→MAD"), wa.index("SVQ→LIS"))  # ordenado por mejor precio
        self.assertIn("39€", wa)
        html = va.html_correo(alertas, {"origen": "SVQ", "moneda": "EUR"})
        self.assertIn("google.com/travel/flights", html)


if __name__ == "__main__":
    unittest.main()
