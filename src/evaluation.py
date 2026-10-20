"""Explainable preference checks; no invented probability of getting hired."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def folded(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def positive_terms(text: str, terms: list[str]) -> list[str]:
    text = folded(text)
    found = []
    for term in terms:
        pattern = r'(?<!\w)' + re.escape(folded(term)) + r'(?!\w)'
        for occurrence in re.finditer(pattern, text):
            before = text[max(0, occurrence.start() - 55):occurrence.start()]
            after = text[occurrence.end():occurrence.end() + 55]
            neg_before = re.search(r'\b(?:no|not|without|sin)\s+(?:(?:experience|experiencia)\s+(?:with|in|en|con)\s+)?$', before)
            neg_after = re.match(r'\s*(?:(?:is|are|es)\s+)?(?:not (?:required|needed|necessary)|no (?:es necesario|se requiere|requerido|indispensable))\b', after)
            if not (neg_before or neg_after):
                found.append(term)
                break
    return list(dict.fromkeys(found))


def evaluate(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    prefs = profile.get('preferences', {})
    rules = profile.get('matching', {})
    matches = positive_terms(job['text'], profile.get('skills_from_cv', []) + profile.get('historical_roles_from_cv', []))
    reasons, unknowns = [], []
    roles = []
    aliases = rules.get('role_aliases', {})
    for role in prefs.get('target_roles', []):
        if positive_terms(job.get('title', ''), [role] + aliases.get(role, [])):
            roles.append(role)
    if prefs.get('target_roles') and not roles:
        reasons.append('cargo_fuera_del_objetivo')
    if len(matches) < int(rules.get('minimum_profile_terms', 1)) and not roles:
        reasons.append('sin_coincidencia_del_perfil')
    if prefs.get('work_modes'):
        mode = job.get('work_mode', 'unknown')
        if mode == 'unknown':
            unknowns.append('Modalidad remota por confirmar')
        elif mode not in prefs['work_modes']:
            reasons.append('modalidad_no_elegida')
    if prefs.get('geographic_scope') == 'worldwide':
        location = folded(job.get('location', ''))
        if re.search(r'\b(?:except|excluding|not available in|excepto)\s+peru\b', location):
            reasons.append('restriccion_geografica_sin_peru')
        elif re.search(r'\b(worldwide|world wide|global|anywhere|all countries|todo el mundo|mundial)\b', location):
            unknowns.append('Alcance mundial anunciado; verificar condiciones y autorizacion')
        elif re.search(r'\b(peru|latam|latin america|america latina|south america|sudamerica|americas)\b', location):
            unknowns.append('Region compatible con Peru; verificar autorizacion y horario')
        elif re.search(r'\b(usa|united states|us|canada|uk|united kingdom|europe|european union|emea|apac|germany|france|spain|chile|mexico|colombia|argentina|brazil|brasil|australia|india)\b', location):
            reasons.append('restriccion_geografica_sin_peru')
        else:
            unknowns.append('Elegibilidad desde Peru por confirmar')
    excluded = positive_terms(job['text'], prefs.get('excluded_terms', []))
    if excluded:
        reasons.append('termino_excluido')
    clouds = positive_terms(job['text'], prefs.get('cloud_priority', []))
    cloud_order = prefs.get('cloud_priority', [])
    priority = min((cloud_order.index(c) for c in clouds), default=len(cloud_order))
    return {'accepted': not reasons, 'matches': matches, 'roles': roles,
            'rejected_by': reasons, 'uncertainties': unknowns,
            'clouds': clouds, 'cloud_priority': priority,
            'opportunity_type': job.get('opportunity_type', 'unknown')}
