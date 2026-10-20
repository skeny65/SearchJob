"""Telegram cards grouped without splitting HTML; receipts checkpoint each message."""
from __future__ import annotations

import html
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable


class DeliveryError(RuntimeError):
    def __init__(self, message: str, attempted_ids: list[str]):
        super().__init__(message)
        self.attempted_ids = attempted_ids


def units(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


def render_chunks(jobs: list[dict[str, Any]], run_time: str, summary: str) -> list[tuple[str, list[str]]]:
    def esc(value: Any, limit: int) -> str:
        output = ''
        for char in str(value):
            encoded = html.escape(char)
            if units(output + encoded) > limit:
                break
            output += encoded
        return output
    chunks = []
    current = f'<b>Buscador de empleo · {esc(run_time, 80)}</b>\nNuevas candidatas: {len(jobs)}\n{esc(summary, 700)}'
    ids: list[str] = []
    for job in jobs:
        evaluation = job.get('evaluation', {})
        doubts = '; '.join(evaluation.get('uncertainties', []))
        url = job['url']
        escaped_url = html.escape(url, quote=True)
        link = f'<a href="{escaped_url}">Abrir oferta</a>' if units(escaped_url) <= 1400 else 'URL extensa: consultar el estado del repositorio'
        card = (f"\n\n<b>{esc(job['title'], 120)}</b> · {esc(job['company'], 100)}"
                f"\n📍 {esc(job['location'], 140)} · {esc(job.get('work_mode', 'unknown'), 20)} · {esc(job.get('opportunity_type', 'unknown'), 25)}"
                f"\n🎯 {esc(', '.join(job.get('matches', [])[:6]), 180)}"
                f"\n❔ {esc(doubts or 'Revisar requisitos completos en la fuente', 250)}"
                f"\n🔎 {esc(job['source'], 40)} · {esc(job.get('published_at') or 'fecha sin dato', 60)}\n{link}")
        if units(current + card) > 3800:
            chunks.append((current, ids))
            current, ids = '', []
        current += card
        ids.append(job['id'])
    if current:
        chunks.append((current, ids))
    return chunks


def telegram_send(token: str, chat_id: str, jobs: list[dict[str, Any]], run_time: str,
                  summary: str, checkpoint: Callable | None = None) -> dict[str, Any]:
    receipts = []
    for chunk, ids in render_chunks(jobs, run_time, summary):
        body = json.dumps({'chat_id': chat_id, 'text': chunk, 'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=body,
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'KenyJobHunter/0.2'}, method='POST')
        result = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    result = json.loads(response.read().decode())
                if not result.get('ok') or not result.get('result', {}).get('message_id'):
                    raise ValueError('invalid receipt')
                break
            except urllib.error.HTTPError as exc:
                retry_after = 0
                try:
                    retry_after = int(json.loads(exc.read().decode()).get('parameters', {}).get('retry_after', 0))
                except Exception:
                    pass
                if exc.code == 429 and attempt == 0 and 0 < retry_after <= 30:
                    time.sleep(retry_after)
                    continue
                raise DeliveryError(f'Telegram: entrega incierta (HTTP {exc.code}); revisar antes de reintentar.', ids) from None
            except Exception:
                # Underlying exceptions may contain a URL with the token. Never expose them.
                raise DeliveryError('Telegram: entrega incierta; revisar el chat antes de reintentar.', ids) from None
        message_id = result['result']['message_id']
        receipts.append(message_id)
        if checkpoint:
            checkpoint(ids, message_id)
        time.sleep(1.1)
    return {'message_ids': receipts}
