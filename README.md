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
- Jobicy: API pública, consulta Azure, hasta dos páginas de 100 entradas con cursor; conservar atribución y URL Jobicy.
- Sofka: feed RSS oficial de empleo sobre Teamtailor, hasta 100 anuncios por consulta diaria; enlace al anuncio de Sofka.

El perfil v3 aplica las preferencias actualizadas de Keny: los cuatro cargos del CV, remoto, **solo Azure y anuncios en español**. Se exige una mención positiva de Azure y se excluye AWS/Amazon Web Services, también en ofertas mixtas Azure+AWS. El CV conserva AWS como experiencia histórica, separado de preferencias.

El idioma del anuncio se toma de metadata explícita o de una heurística de texto. Se excluyen idioma inglés/otro e idioma desconocido; un título técnico inglés puede acompañar una descripción en español. Se rechazan menciones de inglés exigido detectadas; inglés claramente opcional/no requerido no cuenta como obligación. Esta detección no sustituye revisar requisitos en el anuncio original. No hay un filtro previo que exija inglés.

Requiere un cargo elegido en el título y descarta modalidad híbrida/presencial y restricciones regionales explícitas incompatibles con Perú. Modalidad y elegibilidad geográfica ausentes siguen visibles con dudas. Salario mínimo y disponibilidad siguen pendientes. No se añadieron SRE/Platform como cargos independientes ni un score mínimo.

Empleo y proyectos/contratos están aceptados cuando las fuentes los proporcionan; aún no hay un marketplace freelance dedicado. Cada reporte muestra evaluadas, compatibles, ya notificadas/reservadas, nuevas y razones de descarte por fuente. Una fuente consultada puede tener cero candidatas. No hay cobertura universal ni garantía de ofertas recientes fuera de las páginas configuradas.

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
