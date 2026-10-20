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

El perfil v2 aplica las preferencias elegidas por Keny: DevOps Engineer, DevSecOps, Cloud Engineer y Azure Specialist (con variantes equivalentes en español), remoto, Azure primero y AWS después. Requiere un cargo objetivo en el título; una palabra como Azure en una oferta QA no basta. Los cargos genéricos elegidos siguen admitidos aunque no mencionen una nube concreta. No se añadieron SRE/Platform como objetivos independientes, seniority, tecnologías obligatorias ni un score de contratación.

Busca internacionalmente desde Perú: descarta modalidad híbrida/presencial y restricciones regionales explícitas incompatibles. Las ubicaciones/modalidades desconocidas siguen visibles con una advertencia de verificación. Una mención de Worldwide/LATAM no prueba autorización laboral ni elegibilidad; el resumen lo aclara. Es una heurística de palabras/metadata, no una revisión jurídica ni comprensión completa de cada anuncio.

Empleo y proyectos/contratos están aceptados; se muestra el tipo cuando la fuente lo proporciona. No hay un conector dedicado a marketplaces freelance ni cobertura de Upwork. Salario mínimo, idioma, disponibilidad y exclusiones siguen sin definir. La búsqueda está limitada a las fuentes y páginas configuradas, y una vacante recién descubierta puede ser antigua.

## Diseño operativo

- No fusiona ofertas distintas solo porque coincidan empresa, título y ubicación.
- El workflow ejecuta `--phase prepare`, guarda una reserva y un outbox mínimo en GitHub, y solo después invoca `--phase notify`. Si el push de la reserva falla, no comienza el envío.
- Guarda recibos por mensaje: una entrega parcial conserva las ofertas confirmadas como `notified`, la petición ambigua como `uncertain` y los mensajes aún no intentados como `pending`.
- Marca entrega ambigua como `uncertain`; no reintenta automáticamente para evitar mensajes duplicados.
- Una reserva `sending` que sobrevivió a una interrupción se vuelve `uncertain` en la siguiente corrida. Puede requerir revisión del chat. Git/Telegram no ofrecen una transacción común ni entrega exactamente una vez.
- Construye mensajes por tarjetas completas sin cortar etiquetas HTML. URLs idénticas se deduplican también entre corridas y fuentes.
- Telegram recibe resumen también con cero resultados. Un fallo total de fuentes se notifica y deja el job en estado fallido.
- `data/seen_jobs.json`, `data/outbox.json` y el reporte se guardan en el repo público. El outbox solo contiene enlaces, metadatos y razones, sin descripciones completas. El reporte distingue conteos por fuente/páginas, descartes y entregas inciertas.
- Anuncios y descripciones son datos no confiables; nunca se interpretan como instrucciones.

Consulta [SETUP.md](SETUP.md) para el procedimiento de primera corrida y [AGENTS.md](AGENTS.md) para las reglas de mantenimiento.

## Agentes y mantenimiento

Actions orquesta el trabajo diario y Python aplica las reglas. No requiere Copilot, un agente residente, un proveedor LLM ni permisos `models`/`issues`. `AGENTS.md` orienta a agentes que modifiquen el código; ese uso es independiente de buscar ofertas. CI ejecuta pruebas offline en pushes de código/configuración y en pull requests. Una capa IA para extraer requisitos ambiguos se puede evaluar después, con proveedor vigente, presupuesto, evidencias y fallback propios.
