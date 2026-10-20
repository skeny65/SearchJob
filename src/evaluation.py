"""Explainable preference checks; no invented probability of getting hired."""
from __future__ import annotations

import re
from typing import Any
from src.languages import folded, posting_language, required_english


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
    cloud_aliases = {'Azure': ['Azure', 'Microsoft Azure'], 'AWS': ['AWS', 'Amazon Web Services']}
    required_clouds = prefs.get('required_clouds', [])
    if required_clouds and not any(positive_terms(job['text'], cloud_aliases.get(c, [c])) for c in required_clouds):
        reasons.append('sin_nube_objetivo')
    if any(positive_terms(job['text'], cloud_aliases.get(c, [c])) for c in prefs.get('excluded_clouds', [])):
        reasons.append('nube_excluida')
    language = posting_language(job.get('description', job['text']), job.get('language_hint', ''))
    if prefs.get('posting_languages') and language['language'] not in prefs['posting_languages']:
        reasons.append('idioma_anuncio_no_confirmado' if language['language'] == 'unknown' else 'idioma_anuncio_no_elegido')
    english_required = required_english(job['text'])
    if prefs.get('exclude_required_english') and english_required:
        reasons.append('ingles_requerido')
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
        elif re.search(r'\b(usa|united states|us|canada|uk|united kingdom|europe|europa|european union|emea|apac|germany|france|spain|espana|panama|chile|mexico|colombia|argentina|brazil|brasil|australia|india)\b', location):
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
            'posting_language': language, 'english_required_detected': english_required,
            'clouds': clouds, 'cloud_priority': priority,
            'opportunity_type': job.get('opportunity_type', 'unknown')}
