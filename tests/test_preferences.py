import json
import unittest
import urllib.error
from xml.etree import ElementTree
from unittest.mock import patch, MagicMock

from src import main, notifications
from src.evaluation import evaluate, positive_terms


PROFILE = {
    'skills_from_cv': ['Azure', 'AWS', 'Terraform'],
    'historical_roles_from_cv': ['DevOps Engineer', 'Cloud Engineer'],
    'preferences': {'target_roles': ['DevOps Engineer', 'Cloud Engineer'],
                    'work_modes': ['remote'], 'geographic_scope': 'worldwide',
                    'cloud_priority': ['Azure', 'AWS']},
    'matching': {'role_aliases': {'DevOps Engineer': ['DevOps']}, 'minimum_profile_terms': 1}}


def job(**changes):
    return {'id': '1', 'title': 'DevOps Engineer', 'text': 'DevOps Engineer with Azure',
            'company': 'Acme', 'work_mode': 'remote', 'location': 'Worldwide',
            'source': 'remotive', 'url': 'https://example.com/1', **changes}


class PreferenceTests(unittest.TestCase):
    def test_qa_mentioning_azure_is_not_a_selected_role(self):
        result = evaluate(job(title='QA Analyst', text='QA with Azure DevOps'), PROFILE)
        self.assertIn('cargo_fuera_del_objetivo', result['rejected_by'])

    def test_azure_first_aws_accepted_and_generic_cloud_not_dropped(self):
        azure = evaluate(job(), PROFILE)
        aws = evaluate(job(text='DevOps Engineer with AWS'), PROFILE)
        generic = evaluate(job(text='DevOps Engineer with Terraform'), PROFILE)
        self.assertTrue(all(x['accepted'] for x in [azure, aws, generic]))
        self.assertLess(azure['cloud_priority'], aws['cloud_priority'])
        self.assertLess(aws['cloud_priority'], generic['cloud_priority'])

    def test_hybrid_excluded_unknown_mode_visible(self):
        self.assertFalse(evaluate(job(work_mode='hybrid'), PROFILE)['accepted'])
        result = evaluate(job(work_mode='unknown'), PROFILE)
        self.assertTrue(result['accepted'])
        self.assertIn('Modalidad remota por confirmar', result['uncertainties'])

    def test_remote_is_not_equivalent_to_worldwide_or_work_authorization(self):
        self.assertFalse(evaluate(job(location='United States only'), PROFILE)['accepted'])
        self.assertTrue(evaluate(job(location='LATAM'), PROFILE)['accepted'])
        self.assertTrue(evaluate(job(location='Worldwide'), PROFILE)['uncertainties'])
        self.assertTrue(evaluate(job(location='Ubicación no indicada'), PROFILE)['uncertainties'])
        self.assertFalse(evaluate(job(location='Worldwide except Peru'), PROFILE)['accepted'])

    def test_no_unselected_role_expansion(self):
        self.assertFalse(evaluate(job(title='SRE', text='SRE with Azure'), PROFILE)['accepted'])

    def test_negation_is_local_to_the_skill(self):
        self.assertEqual(positive_terms('AWS not required; Azure is required', ['AWS', 'Azure']), ['Azure'])
        self.assertEqual(positive_terms('not only Azure but also AWS', ['Azure', 'AWS']), ['Azure', 'AWS'])

    def test_remoteok_missing_location_does_not_invent_worldwide(self):
        result = main.normalize('remoteok', {'id': 7, 'position': 'DevOps', 'url': 'https://example.com/7'})
        self.assertEqual(result['location'], 'Ubicación no indicada')
        self.assertEqual(result['work_mode'], 'remote')

    def test_getonbrd_uses_structured_mode_country_and_timestamp(self):
        result = main.normalize('getonbrd', {'id': 'g', 'attributes': {
            'title': 'DevOps', 'url': '/job/g', 'remote': False, 'remote_modality': 'hybrid',
            'countries': ['Chile'], 'published_at': 1700000000}})
        self.assertEqual(result['work_mode'], 'hybrid')
        self.assertIn('Chile', result['location'])
        self.assertIn('T', result['published_at'])


class NotificationTests(unittest.TestCase):
    def test_chunks_keep_html_valid_even_for_long_escaped_fields(self):
        jobs = [job(id=str(n), title='😀<&' * 500, company='&' * 500,
                    matches=['<Azure>'], evaluation={'uncertainties': ['&' * 500]}) for n in range(12)]
        chunks = notifications.render_chunks(jobs, 'today', '&' * 500)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(sum((ids for _, ids in chunks), []), [str(n) for n in range(12)])
        for text, _ in chunks:
            self.assertLessEqual(notifications.units(text), 3800)
            ElementTree.fromstring('<root>' + text + '</root>')

    @patch.object(notifications.time, 'sleep')
    @patch.object(notifications.urllib.request, 'urlopen')
    def test_response_receipt_checkpoints_once(self, open_url, _sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'ok': True, 'result': {'message_id': 19}}).encode()
        open_url.return_value = response
        callback = MagicMock()
        result = notifications.telegram_send('fake', '1', [job(matches=['Azure'])], 'today', 'ok', callback)
        callback.assert_called_once_with(['1'], 19)
        self.assertEqual(result['message_ids'], [19])

    @patch.object(notifications.urllib.request, 'urlopen', side_effect=urllib.error.URLError('https://api.telegram.org/botSECRET/sendMessage'))
    def test_network_error_does_not_leak_token(self, _open):
        with self.assertRaises(notifications.DeliveryError) as error:
            notifications.telegram_send('SECRET', '1', [job(matches=[])], 'today', 'ok')
        self.assertNotIn('SECRET', str(error.exception))
        self.assertEqual(error.exception.attempted_ids, ['1'])


class SourceTests(unittest.TestCase):
    @patch.object(main.time, 'sleep')
    @patch.object(main.urllib.request, 'urlopen')
    def test_transient_fetch_failure_retries_boundedly(self, open_url, sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        open_url.side_effect = [urllib.error.URLError('offline'), urllib.error.URLError('offline'), response]
        self.assertEqual(main.fetch_json('https://example.com'), {})
        self.assertEqual(open_url.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(main, 'fetch_json')
    def test_failed_second_page_preserves_first_and_company_metadata(self, fetch):
        rows = [{'id': str(i), 'attributes': {'title': 'DevOps', 'url': f'/job/{i}', 'company': {'data': {'id': 'c'}}}} for i in range(100)]
        fetch.side_effect = [{'data': rows, 'included': [{'id': 'c', 'type': 'company', 'attributes': {'name': 'Acme'}}]}, TimeoutError()]
        stats = {}
        jobs, errors = main.collect({'getonbrd': {'enabled': True, 'url': 'https://example.com', 'max_pages': 3}}, stats)
        self.assertEqual(len(jobs), 100)
        self.assertEqual(jobs[0]['company'], 'Acme')
        self.assertEqual(stats['getonbrd']['pages'], 1)
        self.assertIn('getonbrd', errors)


if __name__ == '__main__':
    unittest.main()
