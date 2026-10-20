"""Conservative posting-language and explicit English-requirement checks."""
import re
import unicodedata


def folded(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


SPANISH = set('de la el los las en con para por que del una un se y como experiencia conocimientos trabajo equipo buscamos nuestro nuestra nosotros tienes ofrecemos requisitos funciones responsabilidades remoto habilidades desarrollo realizar contar tienes tener manejo nivel capacidad ser tus tu sera buscamos estamos'.split())
ENGLISH = set('the and with for you your our we are is to of in experience skills work team requirements responsibilities required looking this that have will as an a be from must ability knowledge role about join at'.split())


def posting_language(description: str, hint: str = '') -> dict:
    hint = hint.casefold()
    if hint in {'es', 'spanish', 'lang_spanish', 'espanol', 'español'}:
        return {'language': 'es', 'basis': 'source'}
    if hint in {'en', 'english', 'lang_english'}:
        return {'language': 'en', 'basis': 'source'}
    tokens = re.findall(r'\b[a-z]+\b', folded(description))
    unique = set(tokens)
    es = sum(token in SPANISH for token in tokens)
    en = sum(token in ENGLISH for token in tokens)
    if len(unique & SPANISH) >= 5 and es >= max(6, en * 1.25):
        return {'language': 'es', 'basis': 'text_heuristic'}
    if len(unique & ENGLISH) >= 5 and en >= max(6, es * 1.25):
        return {'language': 'en', 'basis': 'text_heuristic'}
    return {'language': 'unknown', 'basis': 'insufficient_or_mixed_text'}


def required_english(text: str) -> bool:
    for clause in re.split(r'[.;!?\n]+', folded(text)):
        for occurrence in re.finditer(r'\b(ingles|english|bilingue|bilingual)\b', clause):
            nearby = clause[max(0, occurrence.start() - 65):occurrence.end() + 75]
            if re.search(r'(?:no se requiere|no es necesario|sin necesidad de|not required|not necessary|no requiere)', nearby):
                continue
            optional = re.search(r'\b(deseable|opcional|valorable|preferred|optional|plus)\b|nice to have|no excluyente', nearby)
            mandatory = re.search(r'(?<!no )\b(obligatorio|indispensable|excluyente|required|must)\b', nearby)
            if optional and not mandatory:
                continue
            return True
    return False
