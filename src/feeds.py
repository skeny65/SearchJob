"""Public syndication feed for employer careers pages, never browser scraping."""
import urllib.request
from xml.etree import ElementTree


def teamtailor_rows(url: str, company: str) -> list[dict]:
    request = urllib.request.Request(url, headers={'User-Agent': 'KenyJobHunter/0.3 (personal job discovery)'})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported or oversized feed')
    root = ElementTree.fromstring(raw)
    ns = {'tt': 'https://teamtailor.com/locations'}
    rows = []
    for item in root.findall('./channel/item'):
        places = []
        for location in item.findall('tt:locations/tt:location', ns):
            places.extend(filter(None, [location.findtext('tt:name', namespaces=ns), location.findtext('tt:country', namespaces=ns)]))
        rows.append({'_source_kind': 'teamtailor_rss', 'id': item.findtext('guid'),
                     'title': item.findtext('title'), 'description': item.findtext('description') or '',
                     'company': company, 'url': item.findtext('link'), 'published_at': item.findtext('pubDate'),
                     'location': ', '.join(dict.fromkeys(places)), 'remote_status': item.findtext('remoteStatus')})
    return rows
