# Puesta en marcha y operación

El repositorio público `skeny65/SearchJob` ya contiene el pipeline. La carpeta de trabajo local está en `cerebro\github\SearchJob` dentro del proyecto Keny.

## 1. Comprobar los secretos

En **Settings → Secrets and variables → Actions → Repository secrets**, deben existir:

- `TELEGRAM_BOT_TOKEN`: token de BotFather.
- `TELEGRAM_CHAT_ID`: ID privado que devolvió `scripts/get_chat_id.py`.

Ya confirmaste que ambos aparecen en GitHub. Nunca los agregues como variables, al código, a la URL del navegador ni al historial Git.

## 2. Habilitar Actions y correr la prueba inicial

1. Abre el repositorio y selecciona **Actions**. Si GitHub pregunta, habilita GitHub Actions para el repo.
2. Selecciona **Keny Job Hunter** en la lista de workflows.
3. Pulsa **Run workflow**, elige la rama `main` y confirma.
4. Abre la ejecución y revisa **Test**, **Collect and reserve notifications**, **Persist reservation before contacting Telegram**, **Deliver reserved summary** y **Persist delivery receipts**.
5. Revisa Telegram. Debes recibir un resumen aunque haya cero ofertas nuevas; el resumen indica qué fuentes respondieron y cuáles fallaron.
6. En GitHub, verifica el reporte `reports/latest.json` y que el estado mínimo se haya guardado en `data/seen_jobs.json` cuando hubo ofertas nuevas.

Un workflow verde confirma que los pasos terminaron, pero revisa también que las fuentes tengan conteos razonables y que el mensaje llegó al chat. Si una fuente falla, el aviso incluye su nombre. Si fallan todas, llega un reporte de salud y la ejecución queda marcada como fallida.

## 3. Horario diario

El evento `schedule` consulta cada día a las `01:17 UTC`, equivalente a las `20:17` de Lima. El horario se activa automáticamente cuando el workflow está en la rama predeterminada del repo. GitHub puede retrasar o descartar ejecuciones programadas durante alta carga; **Actions** muestra el historial real.

## 4. Ajustar búsquedas

Edita `config/profile.json` para actualizar hechos del CV y preferencias confirmadas, y `config/sources.json` para cambiar fuentes/paginación. Perfil v2: cuatro cargos del CV, remoto global desde Perú, prioridad Azure y luego AWS, empleo y freelance/contratos. Los aliases de cargos están en `matching.role_aliases`; son variantes de los cargos elegidos. No ampliar objetivos ni inventar salario mínimo, idioma, disponibilidad o exclusiones.

Las fuentes actuales son Get on Board (categoría SysAdmin/DevOps/QA, máximo tres páginas), Remotive y Remote OK. La búsqueda no cubre todo Internet. Remotive retrasa sus ofertas y recomienda no consultar con demasiada frecuencia; la programación diaria respeta esa guía.

## 5. Cambios futuros

Desde la carpeta `cerebro\github\SearchJob`, revisa lo que cambiarás antes de publicar:

```powershell
git status
git diff --check
git diff
python -m unittest discover -s tests -v
```

Después de revisar el diff, publica cambios en `main`:

```powershell
git add .
git commit -m "describe el cambio"
git push origin main
```

El workflow CI prueba cambios de código/configuración sin secretos ni acceso a Telegram. El buscador también prueba antes de cada corrida. Su job requiere `contents: write` para persistir reserva, outbox y recibos. No concede `models` ni `issues`.

## 6. Privacidad y alcance

El repositorio es público. `config/profile.json` contiene una versión mínima de tu ciudad, cargos históricos, tecnologías y certificaciones procedentes del CV, por lo que esa información es visible. El CV PDF, teléfono, correo, token del bot y chat ID no deben incluirse en commits. Los secretos se mantienen en GitHub Actions Secrets.

El pipeline solo busca y notifica; nunca completa formularios ni envía candidaturas o mensajes a reclutadores. La postulación automática necesita un plan y autorización separados.

## Entrega incierta

Si el estado marca una oferta como `uncertain`, comprueba primero el chat de Telegram. No borres ni reproceses la entrada hasta determinar si llegó. Los mensajes confirmados conservan `message_ids`; los aún no intentados quedan `pending` y pueden retomarse si la vacante reaparece. Una reserva interrumpida pasa de `sending` a `uncertain`, nunca se reenvía silenciosamente.

Para pruebas locales, usa `python -m src.main --dry-run`. El modo local sin esa bandera envía mensajes y no confirma reservas en GitHub por sí mismo; la secuencia durable corresponde al workflow en dos fases. Si falla **Persist delivery receipts**, la reserva previa sigue en GitHub y debe reconciliarse; no ejecutar otro envío a ciegas.
