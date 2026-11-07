# Alertas de vuelos baratos desde Sevilla (SVQ)

El programa vigila los **87 destinos** que salen de Sevilla según Aena, con todas las aerolíneas y escalas permitidas. Usa el calendario de precios de Google Flights para cada fecha de salida de los próximos 180 días, en viajes de ida y vuelta de 3 y 7 noches.

Te avisa por **correo** y/o **WhatsApp** en dos casos:
1. Un precio **baja del umbral** de su destino.
2. Estando ya por debajo, **vuelve a bajar** al menos 2 € respecto al último precio visto.

Si un precio sube por encima del umbral, ese viaje se rearma y vuelve a avisarte cuando baje otra vez. Se ejecuta solo en GitHub Actions 4 veces al día, así que no necesitas tener ningún ordenador encendido.

## Puesta en marcha (≈15 min)

### 1. Crear el repositorio
- Crea un repositorio en GitHub y sube esta carpeta tal cual, incluida `.github/`.
- **Hazlo público si puedes.** Una pasada completa tarda unos 25 minutos. Los repos privados gratuitos tienen 2.000 min/mes de Actions, y no llegan para 4 pasadas diarias. En los públicos es ilimitado. El repo no contiene nada privado: tus claves van en *secrets*, que nunca se ven. Si lo prefieres privado, deja 2 ejecuciones al día en `alertas.yml` o una sola duración en `config.toml`.

### 2. Correo (Gmail)
1. Activa la verificación en dos pasos de tu cuenta de Google.
2. Crea una **contraseña de aplicación** en <https://myaccount.google.com/apppasswords>.
3. En el repo, ve a *Settings → Secrets and variables → Actions → New repository secret* y crea estos tres secrets:
   - `SMTP_USUARIO`: tu dirección de Gmail
   - `SMTP_PASSWORD`: la contraseña de aplicación (16 letras)
   - `EMAIL_DESTINO`: el correo donde quieres recibir los avisos (puede ser el mismo)

### 3. WhatsApp (CallMeBot, gratis)
1. Añade a tus contactos el número que indica <https://www.callmebot.com/blog/free-api-whatsapp-messages/>. Comprueba el número en esa web, porque a veces cambia.
2. Envíale por WhatsApp el mensaje `I allow callmebot to send me messages`.
3. Te responderá con tu **apikey**. Crea estos dos secrets:
   - `WHATSAPP_TELEFONO`: `+34XXXXXXXXX`
   - `WHATSAPP_APIKEY`: la clave recibida

Si solo configuras uno de los dos canales, el otro se ignora.

### 4. Probar
En la pestaña *Actions*, abre **Alertas vuelos SVQ** y pulsa *Run workflow*. El campo `modo` admite tres valores:
- `prueba-aviso`: manda un aviso falso para comprobar el correo y el WhatsApp.
- `sin-enviar`: hace una pasada real, guarda los precios y no te notifica. Así **evitas la avalancha de avisos de la primera vez**, porque al empezar todo lo que esté bajo el umbral cuenta como nuevo.
- `normal`: el funcionamiento automático.

## Ajustes (`config.toml`)
- **Umbrales**: hay uno por grupo de destinos (nacional 30 €, Europa 35–50 €, Turquía 80 €…). Para un destino concreto, usa `[umbral_destino]`, por ejemplo `MAD = 40`. Los valores iniciales son orientativos; ajústalos.
- `duraciones`: las noches de viaje que se comprueban. Cada valor añade unas 260 consultas por pasada.
- `max_escalas`: `-1` permite cualquier número de escalas y `0` deja solo los directos.
- `horizonte_dias`: hasta cuántos días vista se busca.

Para probarlo en local:
```
pip install -r requirements.txt
python vuelos_alerta.py --sin-enviar
python -m unittest -v
```

## Limitaciones
- Google Flights no tiene API oficial. La librería `fast-flights` lee los datos que muestra su web, así que **puede dejar de funcionar** si Google cambia algo. Si ninguna petición funciona, el run sale en rojo y GitHub te manda un correo.
- Los precios son los de Google Flights, que incluye prácticamente todas las aerolíneas, Ryanair incluida. Aun así, el precio final en la web de la aerolínea puede variar algo por equipaje o tasas de pago.
- Solo se buscan viajes de ida y vuelta con duración fija, porque es lo que ofrece el calendario de precios de la librería.
