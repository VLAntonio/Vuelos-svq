# Alertas de vuelos baratos desde Sevilla (SVQ) + alojamiento + coche

El programa vigila los **87 destinos** que salen de Sevilla según Aena. Busca con todas las aerolíneas y escalas permitidas, usando el calendario de precios de Google Flights para los próximos 180 días, en viajes de ida y vuelta de 3 y 7 noches.

Te avisa por **Telegram** en dos casos:
1. Un vuelo **baja del umbral** de su destino.
2. Un vuelo que ya estaba bajo el umbral **vuelve a bajar** al menos 2 €.

Para el vuelo más barato de cada destino busca **alojamiento para las mismas fechas** en Google Hotels, que agrupa Booking, Expedia, Hotels.com, la web del propio hotel y otras. **Solo te avisa de los destinos donde el vuelo y el alojamiento están por debajo de su umbral.** Un alojamiento cuenta si cumple una de estas dos condiciones:
- Tiene una nota de al menos **4,3/5** con **300 opiniones o más**.
- Es **nuevo**, con entre 20 y 299 opiniones, y tiene una nota de al menos **4,6/5**.

Te llegan **todos** los alojamientos que cumplen, ordenados por nota de **ubicación**, **precio** e **instalaciones** (número de servicios). También tienes enlaces a Booking y a Google Hotels con la búsqueda ya filtrada para ver más opciones.

Para esos mismos destinos se muestran los **coches de alquiler más baratos**, con recogida y devolución en el aeropuerto. Los coches no tienen umbral. El aviso incluye siempre un enlace a Kayak ordenado por precio, y el precio concreto de los 3 más baratos si tienes `RAPIDAPI_KEY`.

## Archivos
| Archivo | Para qué |
|---|---|
| `vuelos_alerta.py` | Programa principal: vuelos, avisos y mensajes |
| `hoteles.py` | Búsqueda de alojamiento (SerpApi, Google Hotels) |
| `coches.py` | Alquiler de coche (Kayak + RapidAPI opcional) |
| `ciudades.py` | Traducción de los códigos de aeropuerto a ciudad y país |
| `config.toml` | Umbrales y ajustes |
| `.github/workflows/alertas.yml` | Programación en GitHub Actions |
| `test_logica.py` | Pruebas |
| `estado.json` | Memoria de precios; se crea solo |

## Secrets necesarios
Se configuran en *Settings → Secrets and variables → Actions → Repository secrets*:

| Name | Qué es |
|---|---|
| `TELEGRAM_TOKEN` | Token del bot (@BotFather) |
| `TELEGRAM_CHAT_ID` | Tu Id (@userinfobot) |
| `SERPAPI_KEY` | Clave de <https://serpapi.com> (plan gratuito, 250 búsquedas al mes). Si falta, el programa solo vigila vuelos. |
| `RAPIDAPI_KEY` | Opcional. Clave de RapidAPI suscrita a la API "Booking COM" de DataCrawler, para ver los precios de los coches. Sin ella, solo aparece el enlace a Kayak. |

## Ajustes (`config.toml`)
- En cada grupo de destinos:
  - `umbral`: precio máximo del vuelo de ida y vuelta.
  - `umbral_hotel_noche`: precio máximo por noche del alojamiento.
- `[umbral_destino]`: sirve para fijar un umbral de vuelo a un destino concreto, por ejemplo `MAD = 25`.
- `[hoteles]`, con estos valores:
  - `opiniones_minimas` y `valoracion_minima`: los alojamientos con trayectoria.
  - `opiniones_minimas_nuevo` y `valoracion_minima_nuevo`: los alojamientos nuevos.
  - `max_mostrados`: `0` muestra todos.
  - `orden_busqueda`
  - `max_busquedas_por_ejecucion`
  - `presupuesto_mensual`: no lo subas de 250 con el plan gratuito.
  - `activado = false`: desactiva la búsqueda de alojamiento y vuelve a avisar solo de vuelos.
- `[hoteles.prioridad]`: el peso de la ubicación, el precio y las instalaciones en el orden de los alojamientos.
- `[coches]`, con estos valores:
  - `edad_conductor`
  - `hora_recogida` y `hora_devolucion`
  - `max_mostrados`
  - `presupuesto_mensual`: ajústalo al límite de tu plan de RapidAPI.
- `duraciones`, `max_escalas` y `horizonte_dias`, como antes.

## Modos (Actions → Run workflow → `modo`)
- `prueba-aviso`: envía un aviso ficticio a Lisboa. Si tienes `SERPAPI_KEY`, hace una búsqueda **real** de alojamiento, que cuenta como 1 de las 250 del mes.
- `sin-enviar`: hace una pasada real, guarda los precios y no te avisa.
- `normal`: el funcionamiento automático.

## Limitaciones
- Google Flights no tiene API oficial y `fast-flights` lee los datos de su web, así que puede dejar de funcionar si Google cambia algo.
- El enlace de Booking abre la búsqueda de ese alojamiento para tus fechas. Es posible que en Booking el precio sea algo distinto, o que ese alojamiento no esté en Booking. En ese caso, el enlace de Google Hotels muestra todas las webs con su precio.
- Se busca alojamiento solo para la fecha más barata de cada destino y para un máximo de 5 destinos por pasada, para no gastar las 250 búsquedas gratuitas. Los destinos que quedan sin buscar se miran en la pasada siguiente.
- La API de coches de RapidAPI no es oficial y la he programado sin poder probarla con datos reales. Si falla, el log muestra `✗ coches` y el enlace a Kayak sigue funcionando.
- No se conocen las horas de los vuelos, así que el coche se busca con recogida a las 12:00 del día de llegada y devolución a las 10:00 del día de vuelta. Puedes cambiar las horas en `config.toml`.
