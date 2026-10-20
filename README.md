# Job Hunter de Keny

Buscador personal de empleos que consulta fuentes públicas, compara las ofertas con señales técnicas confirmadas del CV y envía un resumen diario a Telegram. Se ejecuta en GitHub Actions, sin depender de una PC encendida. **Solo busca y notifica; no postula.**

## Estado y privacidad

El repositorio `skeny65/SearchJob` es público. Por ello, todo archivo versionado es visible para cualquiera, incluido `config/profile.json` (ciudad, cargos históricos, tecnologías y certificaciones declaradas en el CV). No contiene teléfono, correo, PDF del CV, token de Telegram ni chat ID. Mantén `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como Repository secrets. No subas reportes con información privada ni datos de postulación.

## Ejecución cloud

El workflow [Keny Job Hunter](.github/workflows/search.yml) puede ejecutarse manualmente y está programado para las 20:17 de Lima. Envía un resumen diario incluso cuando no encuentre ofertas, para mostrar el estado de las fuentes. Si todas las fuentes fallan, envía el resumen de salud y marca la ejecución como fallida. GitHub puede retrasar o no ejecutar un cron durante alta carga.

Configura los secretos en **Settings → Secrets and variables → Actions → Repository secrets**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Luego abre **Actions → Keny Job Hunter → Run workflow** para la primera ejecución. Revisa el estado del workflow y el resumen que llegue al bot.

## Ejecución local

Python 3.11 o superior, sin dependencias de terceros:

```powershell
python -m unittest discover -s tests -v
python -m src.main --dry-run
```

El modo `--dry-run` consulta fuentes, muestra coincidencias y no envía Telegram ni cambia `data/seen_jobs.json`. El reporte local se escribe en `reports/latest.json`.

## Fuentes y límites

- Get on Board: API pública, categoría `sysadmin-devops-qa`, hasta tres páginas.
- Remotive: API pública, retraso aproximado de 24 horas; consulta diaria y enlace/atribución a la fuente.
- Remote OK: feed JSON público; mantener atribución y enlace al anuncio original.

El matching usa términos técnicos y cargos históricos del perfil; las preferencias de puesto, modalidad, países, salario y exclusiones están vacías, así que no se aplican filtros inventados. La lista de ofertas depende de estas fuentes, consultas y límites; no representa todo Internet. Revisa `reports/latest.json` y ajusta la configuración tras evaluar resultados reales.

## Diseño operativo

- No fusiona ofertas distintas solo porque coincidan empresa, título y ubicación.
- Registra una vacante como `pending` antes de enviar; confirma como `notified` solo con respuesta exitosa de Telegram.
- Marca entrega ambigua como `uncertain`; no reintenta automáticamente para evitar mensajes duplicados.
- Telegram recibe resumen también con cero resultados. Un fallo total de fuentes se notifica y deja el job en estado fallido.
- `data/seen_jobs.json` y el último reporte se guardan en el repositorio para persistir deduplicación entre runners.
- Anuncios y descripciones son datos no confiables; nunca se interpretan como instrucciones.

Consulta [SETUP.md](SETUP.md) para el procedimiento de primera corrida y [AGENTS.md](AGENTS.md) para las reglas de mantenimiento.
