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
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


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
        loc = attrs.get("location") or attrs.get("remote") or ""
        location = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        published = attrs.get("published_at") or attrs.get("created_at")
        external_id = str(item.get("id") or attrs.get("id") or "")
        description = attrs.get("description") or ""
    elif source == "remotive":
        title = item.get("title") or ""
        company = item.get("company_name") or ""
        url = item.get("url") or ""
        location = item.get("candidate_required_location") or ""
        published = item.get("publication_date")
        external_id = str(item.get("id") or "")
        description = re.sub(r"<[^>]+>", " ", item.get("description") or "")
    elif source == "remoteok":
        title = item.get("position") or ""
        company = item.get("company") or ""
        url = item.get("url") or item.get("apply_url") or ""
        location = item.get("location") or "Worldwide/remote"
        published = item.get("date")
        external_id = str(item.get("id") or "")
        description = item.get("description") or ""
    else:
        return None
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
    clean_description = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", description)).strip()
    return {
        "id": key,
        "source_id": source_id,
        "title": re.sub(r"\s+", " ", title).strip(),
        "company": re.sub(r"\s+", " ", company).strip() or "Empresa no indicada",
        "location": re.sub(r"\s+", " ", location).strip() or "Ubicación no indicada",
        "url": url,
        "source": source,
        "published_at": published,
        "text": (title + " " + clean_description + " " + " ".join(item.get("tags", []) if isinstance(item.get("tags"), list) else [])).casefold(),
    }


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if not k.casefold().startswith("utm_") and k.casefold() not in {"fbclid", "gclid"}]
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def collect(sources: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    jobs: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for name, spec in sources.items():
        if not spec.get("enabled"):
            continue
        try:
            if name == "getonbrd":
                rows = []
                category = urllib.parse.quote(spec.get("category", "sysadmin-devops-qa"), safe="-")
                for page in range(1, int(spec.get("max_pages", 3)) + 1):
                    query = urllib.parse.urlencode({"page": page, "per_page": 100, "expand[]": "company"})
                    payload = fetch_json(f"{spec['url'].rstrip('/')}/{category}/jobs?{query}")
                    page_rows = payload.get("data", [])
                    rows.extend(page_rows)
                    if len(page_rows) < 100:
                        break
            else:
                payload = fetch_json(spec["url"])
            if name == "remotive":
                rows = payload.get("jobs", [])
            elif name == "remoteok":
                rows = payload if isinstance(payload, list) else []
                rows = [row for row in rows if isinstance(row, dict) and row.get("id")]
            normalized = [job for row in rows if isinstance(row, dict) if (job := normalize(name, row))]
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
    text = job["text"].casefold()
    terms = profile.get("skills_from_cv", []) + profile.get("historical_roles_from_cv", [])
    found = []
    for term in terms:
        pattern = r"(?<![a-z0-9])" + re.escape(term.casefold()) + r"(?![a-z0-9])"
        occurrences = list(re.finditer(pattern, text))
        if occurrences and not all(_is_negated(text, occurrence.start(), occurrence.end()) for occurrence in occurrences):
            found.append(term)
    return list(dict.fromkeys(found))


def _is_negated(text: str, start: int, end: int) -> bool:
    """Ignore clear local negations without treating every absence as a veto."""
    before = text[max(0, start - 60):start]
    after = text[end:min(len(text), end + 45)]
    before_words = before.split()[-6:]
    after_words = after.split()[:5]
    negative_before = {"not", "no", "without", "never", "neither", "sin", "no", "nunca", "ni"}
    if any(word.strip(".,:;()[]") in negative_before for word in before_words):
        return True
    negative_after_phrases = (
        "not required", "not needed", "not necessary", "no es necesario", "no requerido",
        "no se requiere", "no indispensable", "no es obligatorio",
    )
    return any(phrase in after for phrase in negative_after_phrases)


def telegram_send(token: str, chat_id: str, jobs: list[dict[str, Any]], run_time: str, summary: str) -> dict[str, Any]:
    lines = [f"<b>Buscador de empleo · {html.escape(run_time)}</b>", f"Nuevas ofertas con coincidencias técnicas: {len(jobs)}", html.escape(summary)]
    for job in jobs:
        tags = ", ".join(job["matches"][:6])
        lines.append(
            f"\n<b>{html.escape(job['title'])}</b> · {html.escape(job['company'])}"
            f"\n📍 {html.escape(job['location'])}"
            f"\n🎯 {html.escape(tags)}"
            f"\n🔎 {html.escape(job['source'])} · {html.escape(str(job.get('published_at') or 'fecha sin dato'))}"
            f"\n<a href=\"{html.escape(job['url'], quote=True)}\">Abrir oferta</a>"
        )
    text = "\n".join(lines)
    chunks = []
    while len(text) > 3800:
        split = text.rfind("\n", 0, 3800)
        if split < 1:
            split = 3800
        chunks.append(text[:split])
        text = text[split:].lstrip()
    if text:
        chunks.append(text)
    sent = []
    for chunk in chunks:
        body = json.dumps({"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}, method="POST")
        result = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    result = json.loads(response.read().decode())
                break
            except urllib.error.HTTPError as exc:
                # Telegram specifies retry_after for rate limits; never log the request URL/token.
                try:
                    detail = json.loads(exc.read().decode("utf-8"))
                    retry_after = int(detail.get("parameters", {}).get("retry_after", 0))
                except Exception:
                    retry_after = 0
                if exc.code == 429 and attempt == 0 and 0 < retry_after <= 30:
                    time.sleep(retry_after)
                    continue
                raise RuntimeError(f"Entrega incierta a Telegram (HTTP {exc.code}); revisar el chat antes de reintentar") from None
            except urllib.error.URLError:
                # Never echo the underlying URL or request, which could contain the bot token.
                raise RuntimeError("Entrega incierta a Telegram por error de red; revisar el chat antes de reintentar") from None
        if not result.get("ok"):
            raise RuntimeError(f"Telegram rechazó el mensaje: {result.get('description', 'error sin detalle')}")
        sent.append(result["result"].get("message_id"))
        time.sleep(1.1)
    return {"message_ids": sent}


def run(dry_run: bool = False) -> int:
    profile = read_json(ROOT / "config/profile.json")
    sources = read_json(ROOT / "config/sources.json")
    state_path = ROOT / "data/seen_jobs.json"
    state = read_json(state_path)
    jobs, errors = collect(sources)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fresh = []
    minimum = int(profile.get("matching", {}).get("minimum_profile_terms", 1))
    for job in jobs:
        matches = match(job, profile)
        if len(matches) < minimum:
            continue
        record = state["jobs"].get(job["id"])
        if record:
            record.update({"last_seen_at": now, "title": job["title"], "company": job["company"], "url": job["url"], "source": job["source"]})
            continue
        job["matches"] = matches
        fresh.append(job)
    report = {"run_at": now, "sources_ok": [s for s, spec in sources.items() if spec.get("enabled") and s not in errors], "source_errors": errors, "fetched": len(jobs), "new_matches": len(fresh)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "mode": "dry-run" if dry_run else "live"}, ensure_ascii=False))
    for job in fresh[:20]:
        print(f"- {job['title']} | {job['company']} | {job['source']} | {job['url']} | coincidencias: {', '.join(job['matches'])}")
    if dry_run:
        return 0

    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("Telegram no configurado; no se marcaron ofertas como avisadas.", file=sys.stderr)
        return 3
    # State records that a Telegram request was attempted. Network timeouts are ambiguous;
    # preserve an 'uncertain' status and never silently retry it on the next run.
    for job in fresh:
        state["jobs"][job["id"]] = {
            "status": "pending", "first_seen_at": now, "last_seen_at": now,
            "title": job["title"], "company": job["company"], "url": job["url"], "source": job["source"],
        }
    atomic_json(state_path, state)
    try:
        sources_ok = ", ".join(report["sources_ok"]) or "ninguna"
        source_failures = ", ".join(report["source_errors"]) or "ninguna"
        summary = f"Fuentes consultadas: {sources_ok}. Fuentes con error: {source_failures}."
        receipt = telegram_send(token, chat_id, fresh, now, summary)
        for job in fresh:
            state["jobs"][job["id"]]["status"] = "notified"
            state["jobs"][job["id"]]["message_ids"] = receipt["message_ids"]
            state["jobs"][job["id"]]["notified_at"] = now
    except Exception as exc:
        for job in fresh:
            state["jobs"][job["id"]]["status"] = "uncertain"
            state["jobs"][job["id"]]["delivery_error"] = str(exc)
        atomic_json(state_path, state)
        print(str(exc), file=sys.stderr)
        return 4
    atomic_json(state_path, state)
    if not jobs and errors:
        print("No hubo fuentes disponibles; se envió el resumen de salud y el estado quedó conservado.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Buscar ofertas compatibles con el perfil profesional de Keny")
    parser.add_argument("--dry-run", action="store_true", help="consultar fuentes e imprimir coincidencias sin modificar estado ni enviar mensajes")
    sys.exit(run(parser.parse_args().dry_run))
