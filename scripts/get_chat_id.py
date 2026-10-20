"""Obtain this bot's private chat IDs without saving or printing its token."""

from getpass import getpass
import json
import time
import urllib.error
import urllib.request

token = getpass("Pega el token de BotFather (no se mostrará): ").strip()
if not token:
    raise SystemExit("Token vacío")
def telegram_get_updates() -> dict:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates?timeout=5",
        headers={"User-Agent": "KenyJobHunter/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Telegram returns HTTP 409 when a webhook is configured or another
        # getUpdates client is already polling. Do not print the request URL.
        if exc.code == 409:
            raise SystemExit(
                "Telegram no permite getUpdates: hay un webhook configurado o "
                "otra instancia del bot consultando. Desactiva el webhook o "
                "detén el otro proceso y vuelve a intentar."
            ) from None
        raise SystemExit(
            f"Telegram respondió HTTP {exc.code}. Revisa el token; no se imprimió ni guardó."
        ) from None
    except Exception:
        raise SystemExit(
            "No se pudo consultar Telegram. Revisa tu conexión y el token; no se imprimió ni guardó."
        ) from None
    if not payload.get("ok"):
        raise SystemExit("Telegram rechazó la consulta; revisa el token en BotFather.")
    return payload


# The user may have sent /start just before running this script. Poll briefly
# so a pending Telegram update can arrive; each request is read-only here.
chat_ids: set[str] = set()
for attempt in range(3):
    payload = telegram_get_updates()
    for update in payload.get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {})
        if chat.get("type") == "private" and chat.get("id") is not None:
            chat_ids.add(str(chat["id"]))
    if chat_ids or attempt == 2:
        break
    time.sleep(2)

if not chat_ids:
    raise SystemExit(
        "Telegram no devolvió mensajes privados pendientes. Confirma que enviaste "
        "/start al mismo bot cuyo token estás usando. Si el bot usa webhook, "
        "desactívalo antes de ejecutar este script."
    )
print("Chat ID privado (guárdalo como secret TELEGRAM_CHAT_ID):")
print("\n".join(sorted(chat_ids)))
