import unittest
from unittest.mock import patch, MagicMock

from src import main, feeds
from src.evaluation import evaluate
from src.languages import posting_language, required_english


SPANISH = 'Buscamos una persona con experiencia en Azure para trabajar con nuestro equipo. Ofrecemos trabajo remoto y desarrollo profesional. Las responsabilidades incluyen el manejo de la plataforma y los servicios de nuestra empresa.'
ENGLISH = 'We are looking for a Cloud Engineer with Azure experience. You will work with our team and have the ability to build the platform. This role requires knowledge of the services and the tools.'
PROFILE = {'skills_from_cv': ['Azure', 'AWS'], 'historical_roles_from_cv': ['DevOps Engineer'],
           'preferences': {'target_roles': ['DevOps Engineer'], 'required_clouds': ['Azure'],
                           'excluded_clouds': ['AWS'], 'posting_languages': ['es'], 'exclude_required_english': True}}


def job(description=SPANISH):
    return {'title': 'DevOps Engineer', 'description': description,
            'text': 'DevOps Engineer. ' + description, 'location': 'Worldwide', 'work_mode': 'remote'}


class SpanishAzureTests(unittest.TestCase):
    def test_technical_title_in_english_does_not_make_spanish_post_english(self):
        result = evaluate(job(), PROFILE)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['posting_language']['language'], 'es')

    def test_english_post_excluded(self):
        self.assertIn('idioma_anuncio_no_elegido', evaluate(job(ENGLISH), PROFILE)['rejected_by'])

    def test_spanish_post_with_mandatory_english_excluded(self):
        self.assertIn('ingles_requerido', evaluate(job(SPANISH + ' Inglés B2 obligatorio.'), PROFILE)['rejected_by'])

    def test_optional_or_not_required_english_is_not_mandatory(self):
        for phrase in ['Inglés deseable, no excluyente.', 'No se requiere inglés.', 'English is not required.']:
            with self.subTest(phrase=phrase):
                self.assertTrue(evaluate(job(SPANISH + ' ' + phrase), PROFILE)['accepted'])

    def test_azure_required_and_aws_excluded_without_altering_cv_facts(self):
        self.assertIn('nube_excluida', evaluate(job(SPANISH + ' Experiencia en AWS.'), PROFILE)['rejected_by'])
        result = evaluate(job(SPANISH.replace('Azure', 'Terraform')), PROFILE)
        self.assertIn('sin_nube_objetivo', result['rejected_by'])
        self.assertIn('AWS', PROFILE['skills_from_cv'])

    def test_unknown_language_not_claimed_as_spanish(self):
        self.assertEqual(posting_language('Azure AKS Docker CI/CD')['language'], 'unknown')
        self.assertIn('idioma_anuncio_no_confirmado', evaluate(job('Azure AKS CI/CD'), PROFILE)['rejected_by'])

    def test_explicit_language_hint_is_used(self):
        self.assertEqual(posting_language('Azure', 'lang_spanish'), {'language': 'es', 'basis': 'source'})
        self.assertTrue(required_english('Fluent English required'))


class ExtraFeedTests(unittest.TestCase):
    def test_jobicy_normalizes_public_url_and_job_type(self):
        result = main.normalize('jobicy', {'id': 1, 'url': 'https://jobicy.com/jobs/1', 'jobTitle': 'DevOps Engineer',
                                         'companyName': 'Acme', 'jobGeo': 'Anywhere', 'jobType': ['contract'], 'jobDescription': SPANISH})
        self.assertEqual(result['source'], 'jobicy')
        self.assertEqual(result['opportunity_type'], 'contract')
        self.assertEqual(result['work_mode'], 'remote')

    @patch.object(feeds.urllib.request, 'urlopen')
    def test_teamtailor_rss_preserves_structured_country_and_mode(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'''<rss xmlns:tt="https://teamtailor.com/locations"><channel><item><title>DevOps Azure</title><description>Trabajo remoto con Azure</description><link>https://example.com/job</link><guid>123</guid><remoteStatus>fully</remoteStatus><tt:locations><tt:location><tt:name>Lima</tt:name><tt:country>Peru</tt:country></tt:location></tt:locations></item></channel></rss>'''
        open_url.return_value = response
        row = feeds.teamtailor_rows('https://example.com/jobs.rss', 'Acme')[0]
        normalized = main.normalize('acme', row)
        self.assertEqual(normalized['company'], 'Acme')
        self.assertEqual(normalized['work_mode'], 'remote')
        self.assertIn('Peru', normalized['location'])

    @patch.object(main, 'fetch_json')
    def test_jobicy_cursor_pagination_is_bounded(self, fetch):
        row = {'id': 1, 'url': 'https://jobicy.com/jobs/1', 'jobTitle': 'DevOps', 'jobDescription': 'Azure'}
        fetch.side_effect = [{'jobs': [row], 'nextCursor': 'cursor-one'}, {'jobs': [{**row, 'id': 2, 'url': 'https://jobicy.com/jobs/2'}], 'nextCursor': 'another'}]
        stats = {}
        jobs, errors = main.collect({'jobicy': {'enabled': True, 'url': 'https://jobicy.com/api/v2/remote-jobs', 'max_pages': 2}}, stats)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('cursor=cursor-one', fetch.call_args.args[0])
        self.assertFalse(errors)


if __name__ == '__main__':
    unittest.main()
