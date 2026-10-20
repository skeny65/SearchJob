from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections import Counter
from uuid import uuid4

from src.evaluation import evaluate, positive_terms
from src.notifications import DeliveryError, telegram_send

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "KenyJobHunter/0.1 (personal job discovery)"

# Console encodings on Windows often cannot represent arbitrary employer data.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fetch_json(url: str, *, timeout: int = 25, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if attempt == 2 or (exc.code != 429 and exc.code < 500):
                raise
            delay = exc.headers.get('Retry-After', '2') if exc.headers else '2'
            if not delay.isdigit() or int(delay) > 10:
                raise
            time.sleep(max(1, int(delay)))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def normalize(source: str, item: dict[str, Any]) -> dict[str, Any] | None:
    if source == "getonbrd":
        attrs = item.get("attributes") or item
        title = attrs.get("title") or ""
        company_obj = attrs.get("company") or {}
        if isinstance(company_obj, dict) and isinstance(company_obj.get("data"), dict):
            company_obj = company_obj["data"].get("attributes") or {}
        company = (company_obj.get("name") if isinstance(company_obj, dict) else "") or attrs.get("company_name") or ""
        links = item.get("links") or {}
        url = attrs.get("url") or attrs.get("permalink") or links.get("public_url") or links.get("public_web") or links.get("self") or ""
        loc = attrs.get('location') or ''
        location = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        location = ', '.join(filter(None, [str(attrs.get('remote_zone') or ''), location, ', '.join(attrs.get('countries') or [])]))
        published = attrs.get("published_at") or attrs.get("created_at")
        external_id = str(item.get("id") or attrs.get("id") or "")
        description = ' '.join(str(attrs.get(key) or '') for key in ['description', 'functions', 'projects', 'desirable', 'benefits'])
        mode = str(attrs.get('remote_modality') or '').casefold()
        if mode in {'hybrid', 'onsite', 'on_site', 'on-site'}:
            work_mode = 'hybrid' if mode == 'hybrid' else 'onsite'
        else:
            work_mode = 'remote' if attrs.get('remote') is True or mode in {'remote', 'fully_remote'} else ('onsite' if attrs.get('remote') is False else 'unknown')
        opportunity_type = 'unknown'
    elif source == "remotive":
        title = item.get("title") or ""
        company = item.get("company_name") or ""
        url = item.get("url") or ""
        location = item.get("candidate_required_location") or ""
        published = item.get("publication_date")
        external_id = str(item.get("id") or "")
        description = re.sub(r"<[^>]+>", " ", item.get("description") or "")
        work_mode, opportunity_type = 'remote', item.get('job_type') or 'unknown'
    elif source == "remoteok":
        title = item.get("position") or ""
        company = item.get("company") or ""
        url = item.get("url") or item.get("apply_url") or ""
        location = item.get("location") or "Ubicación no indicada"
        published = item.get("date")
        external_id = str(item.get("id") or "")
        description = item.get("description") or ""
        work_mode, opportunity_type = 'remote', item.get('job_type') or 'unknown'
    else:
        return None
    mode_evidence = (title + ' ' + location).casefold()
    if re.search(r'\b(hybrid|h[ií]brido|h[ií]brida)\b', mode_evidence):
        work_mode = 'hybrid'
    elif re.search(r'\b(onsite|on-site|presencial)\b', mode_evidence):
        work_mode = 'onsite'
    if not title or not url:
        return None
    if source == "getonbrd":
        url = urllib.parse.urljoin("https://www.getonbrd.com", url)
    url = canonical_url(url)
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return None
    source_id = external_id or url
    # IDs are scoped to the source. A listing mirrored on another board remains
    # separate unless both boards expose the same canonical URL.
    key_material = f"{source}:{source_id}" if external_id else f"{source}:{url}"
    key = hashlib.sha256(key_material.encode()).hexdigest()
    clean_description = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description))).strip()
    if isinstance(published, (float, int)):
        published = datetime.fromtimestamp(published, timezone.utc).isoformat(timespec='seconds')
    return {
        "id": key,
        "source_id": source_id,
        "title": re.sub(r"\s+", " ", title).strip(),
        "company": re.sub(r"\s+", " ", company).strip() or "Empresa no indicada",
        "location": re.sub(r"\s+", " ", location).strip() or "Ubicación no indicada",
        "work_mode": work_mode,
        "opportunity_type": opportunity_type,
        "url": url,
        "source": source,
        "published_at": published,
        "text": (title + " " + clean_description + " " + " ".join(item.get("tags", []) if isinstance(item.get("tags"), list) else [])).casefold(),
    }


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if not k.casefold().startswith("utm_") and k.casefold() not in {"fbclid", "gclid"}]
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def collect(sources: dict[str, Any], stats: dict | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    jobs: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for name, spec in sources.items():
        if not spec.get("enabled"):
            continue
        detail = {'pages': 0, 'fetched': 0, 'normalized': 0, 'malformed': 0}
        if stats is not None:
            stats[name] = detail
        try:
            if name == "getonbrd":
                rows = []
                category = urllib.parse.quote(spec.get("category", "sysadmin-devops-qa"), safe="-")
                for page in range(1, int(spec.get("max_pages", 3)) + 1):
                    query = urllib.parse.urlencode({"page": page, "per_page": 100, "expand[]": "company"})
                    try:
                        payload = fetch_json(f"{spec['url'].rstrip('/')}/{category}/jobs?{query}")
                    except Exception as exc:
                        errors[name] = type(exc).__name__
                        print(f'source={name} page={page} partial_error={errors[name]}', file=sys.stderr)
                        break
                    page_rows = payload.get("data", [])
                    detail['pages'] += 1
                    companies = {str(obj['id']): obj.get('attributes', {}) for obj in payload.get('included', []) if obj.get('type') == 'company'}
                    for row in page_rows:
                        attrs = row.get('attributes', {})
                        company_id = str((attrs.get('company', {}).get('data') or {}).get('id', ''))
                        if company_id in companies:
                            attrs['company_name'] = companies[company_id].get('name', '')
                    rows.extend(page_rows)
                    if len(page_rows) < 100:
                        break
            else:
                payload = fetch_json(spec["url"])
                detail['pages'] = 1
            if name == "remotive":
                rows = payload.get("jobs", [])
            elif name == "remoteok":
                rows = payload if isinstance(payload, list) else []
                rows = [row for row in rows if isinstance(row, dict) and row.get("id")]
            normalized = []
            for row in rows:
                try:
                    job = normalize(name, row) if isinstance(row, dict) else None
                    if job:
                        normalized.append(job)
                    else:
                        detail['malformed'] += 1
                except (TypeError, ValueError, KeyError, AttributeError):
                    detail['malformed'] += 1
            detail.update(fetched=len(rows), normalized=len(normalized))
            if detail['malformed']:
                errors.setdefault(name, 'MalformedRecords')
            jobs.extend(normalized)
            print(f"source={name} fetched={len(rows)} normalized={len(normalized)}")
        except Exception as exc:  # one failing provider must not hide others
            errors[name] = f"{type(exc).__name__}"
            print(f"source={name} error={errors[name]}", file=sys.stderr)
    return deduplicate(jobs), errors


def deduplicate(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Deduplicate only by canonical URL or source-scoped provider ID. Matching
    # company/title/location alone can merge distinct requisitions.
    unique: dict[str, dict[str, Any]] = {}
    for job in jobs:
        fingerprint = "url:" + job["url"]
        identity = "source-id:" + job["source"] + ":" + job["source_id"]
        if fingerprint in unique or identity in unique:
            continue
        unique[fingerprint] = job
        unique[identity] = job
    return list({job["id"]: job for job in unique.values()}.values())


def match(job: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    return positive_terms(job['text'], profile.get('skills_from_cv', []) + profile.get('historical_roles_from_cv', []))


def prepare(dry_run: bool = False) -> int:
    profile = read_json(ROOT / 'config/profile.json')
    sources = read_json(ROOT / 'config/sources.json')
    state_path = ROOT / 'data/seen_jobs.json'
    state = read_json(state_path)
    if not dry_run and not (os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')):
        print('Telegram no configurado; no se cambio el estado.', file=sys.stderr)
        return 3
    source_stats = {}
    jobs, errors = collect(sources, stats=source_stats)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    run_id = uuid4().hex
    fresh, rejected = [], Counter()
    for record in state['jobs'].values():
        # A reservation left by an interrupted run might have reached Telegram.
        if record.get('status') == 'sending':
            record['status'] = 'uncertain'
    known_urls = {record.get('url'): job_id for job_id, record in state['jobs'].items() if record.get('url')}
    for job in jobs:
        result = evaluate(job, profile)
        if not result['accepted']:
            rejected.update(result['rejected_by'])
            continue
        existing_id = job['id'] if job['id'] in state['jobs'] else known_urls.get(job['url'])
        record = state['jobs'].get(existing_id)
        if record:
            record['last_seen_at'] = now
            if record.get('status') != 'pending':
                continue
            job['id'] = existing_id
        job['matches'], job['evaluation'] = result['matches'], result
        # Only metadata/reasons go into durable state, never complete descriptions.
        fresh.append({k: v for k, v in job.items() if k != 'text'})
    fresh.sort(key=lambda job: job['evaluation']['cloud_priority'])
    report = {'run_at': now, 'run_id': run_id, 'profile_version': profile.get('profile_version'),
              'sources_ok': [s for s, spec in sources.items() if spec.get('enabled') and s not in errors],
              'source_errors': errors, 'fetched': len(jobs), 'new_matches': len(fresh),
              'source_counts': source_stats,
              'rejected_by': dict(rejected),
              'uncertain_deliveries': sum(r.get('status') == 'uncertain' for r in state['jobs'].values())}
    atomic_json(ROOT / 'reports/latest.json', report)
    print(json.dumps({**report, 'mode': 'dry-run' if dry_run else 'prepare'}, ensure_ascii=False))
    for job in fresh[:20]:
        print(f"- {job['title']} | {job['company']} | {job['source']} | {job['url']} | coincidencias: {', '.join(job['matches'])}")
    if dry_run:
        return 0
    for job in fresh:
        previous = state['jobs'].get(job['id'], {})
        state['jobs'][job['id']] = {
            'status': 'sending', 'reservation': run_id,
            'first_seen_at': previous.get('first_seen_at', now), 'last_seen_at': now,
            **{k: job[k] for k in ['title', 'company', 'url', 'source']}}
    summary = (f"Fuentes consultadas: {', '.join(report['sources_ok']) or 'ninguna'}. "
               f"Fuentes con error o resultados parciales: {', '.join(errors) or 'ninguna'}. "
               f"Avisos inciertos pendientes de revision: {report['uncertain_deliveries']}. "
               'Orden: Azure, AWS, otros cargos elegidos. Elegibilidad laboral por verificar.')
    atomic_json(state_path, state)
    atomic_json(ROOT / 'data/outbox.json', {'run_id': run_id, 'run_at': now, 'status': 'ready',
                'jobs': fresh, 'summary': summary, 'exit_code': 2 if not jobs and errors and not report['sources_ok'] else 0})
    return 0


def notify() -> int:
    token, chat_id = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not (token and chat_id):
        print('Telegram no configurado.', file=sys.stderr)
        return 3
    state_path = ROOT / 'data/seen_jobs.json'
    outbox_path = ROOT / 'data/outbox.json'
    outbox, state = read_json(outbox_path), read_json(state_path)
    if outbox['status'] != 'ready':
        print('Outbox ya consumido; no se reenvia.', file=sys.stderr)
        return 0
    jobs = outbox['jobs']
    if any(state['jobs'].get(job['id'], {}).get('status') != 'sending' or
           state['jobs'][job['id']].get('reservation') != outbox['run_id'] for job in jobs):
        print('Reserva de envio inconsistente; no se envia.', file=sys.stderr)
        return 5
    def checkpoint(ids, message_id):
        for job_id in ids:
            state['jobs'][job_id].update(status='notified', message_ids=[message_id], notified_at=outbox['run_at'])
        atomic_json(state_path, state)
    try:
        receipt = telegram_send(token, chat_id, jobs, outbox['run_at'], outbox['summary'], checkpoint=checkpoint)
        for job in jobs:
            if state['jobs'][job['id']]['status'] == 'sending':
                state['jobs'][job['id']].update(status='notified', message_ids=receipt['message_ids'], notified_at=outbox['run_at'])
        outbox['status'] = 'sent'
    except Exception as exc:
        attempted = set(exc.attempted_ids) if isinstance(exc, DeliveryError) else {job['id'] for job in jobs}
        for job in jobs:
            record = state['jobs'][job['id']]
            if record['status'] == 'sending':
                record['status'] = 'uncertain' if job['id'] in attempted else 'pending'
        outbox['status'] = 'failed'
        atomic_json(state_path, state)
        atomic_json(outbox_path, outbox)
        print(str(exc) if isinstance(exc, DeliveryError) else 'Entrega fallo; detalle suprimido para proteger credenciales.', file=sys.stderr)
        return 4
    atomic_json(state_path, state)
    atomic_json(outbox_path, outbox)
    return int(outbox['exit_code'])


def run(dry_run: bool = False, phase: str = 'all') -> int:
    if phase == 'notify':
        if dry_run:
            raise ValueError('--dry-run no se combina con --phase notify')
        return notify()
    code = prepare(dry_run)
    if code or dry_run or phase == 'prepare':
        return code
    # The cloud workflow commits reservations before invoking the notify phase.
    return notify()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Buscar ofertas compatibles con el perfil profesional de Keny')
    parser.add_argument('--dry-run', action='store_true', help='consultar sin enviar ni modificar estado/outbox')
    parser.add_argument('--phase', choices=['all', 'prepare', 'notify'], default='all')
    args = parser.parse_args()
    sys.exit(run(args.dry_run, args.phase))
