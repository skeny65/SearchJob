import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import main
from src.notifications import DeliveryError


class NormalizeTests(unittest.TestCase):
    def test_canonical_url_removes_tracking_but_keeps_job_identifiers(self):
        url = main.canonical_url("HTTPS://EXAMPLE.COM/job/1/?utm_source=mail&source=board&ref=123#apply")
        self.assertEqual(url, "https://example.com/job/1?source=board&ref=123")

    def test_getonbrd_accepts_relative_public_url(self):
        job = main.normalize("getonbrd", {
            "id": "abc", "attributes": {"title": "DevOps Engineer", "url": "/jobs/devops-abc"}
        })
        self.assertIsNotNone(job)
        self.assertEqual(job["url"], "https://www.getonbrd.com/jobs/devops-abc")

    def test_same_company_and_title_do_not_merge_different_requisitions(self):
        base = {"source": "remotive", "company": "Acme", "title": "DevOps", "location": "Remote"}
        one = {**base, "id": "1", "source_id": "1", "url": "https://example.com/1"}
        two = {**base, "id": "2", "source_id": "2", "url": "https://example.com/2"}
        duplicate = {**one, "source": "mirror", "source_id": "x"}
        self.assertEqual(len(main.deduplicate([one, two])), 2)
        self.assertEqual(len(main.deduplicate([one, duplicate])), 1)


class MatchingTests(unittest.TestCase):
    def test_clear_negation_does_not_count_as_a_match(self):
        profile = {"skills_from_cv": ["Kubernetes"], "historical_roles_from_cv": []}
        self.assertEqual(main.match({"text": "Kubernetes is not required"}, profile), [])
        self.assertEqual(main.match({"text": "Experience with Kubernetes required"}, profile), ["Kubernetes"])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "data").mkdir()
        (self.root / "config/profile.json").write_text(json.dumps({
            "skills_from_cv": ["Azure"], "historical_roles_from_cv": [],
            "matching": {"minimum_profile_terms": 1},
        }), encoding="utf-8")
        (self.root / "config/sources.json").write_text(json.dumps({}), encoding="utf-8")
        (self.root / "data/seen_jobs.json").write_text(json.dumps({"schema_version": 1, "jobs": {}}), encoding="utf-8")
        self.root_patch = patch.object(main, "ROOT", self.root)
        self.root_patch.start()
        self.env_patch = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123"})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    @patch.object(main, "collect", return_value=([], {}))
    @patch.object(main, "telegram_send", return_value={"message_ids": [9]})
    def test_empty_daily_run_sends_health_summary(self, send, _collect):
        self.assertEqual(main.run(), 0)
        self.assertEqual(send.call_args.args[2], [])
        self.assertIn("Fuentes consultadas", send.call_args.args[4])

    @patch.object(main, "collect", return_value=([], {"source": "TimeoutError"}))
    @patch.object(main, "telegram_send", return_value={"message_ids": [9]})
    def test_total_source_failure_still_sends_health_summary_and_fails_run(self, send, _collect):
        self.assertEqual(main.run(), 2)
        self.assertEqual(send.call_args.args[2], [])
        self.assertIn("source", send.call_args.args[4])

    @patch.object(main, "collect", return_value=([], {}))
    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
    def test_live_run_requires_telegram_secrets_even_when_empty(self, _collect):
        self.assertEqual(main.run(), 3)

    @patch.object(main, "collect", return_value=([], {}))
    @patch.object(main, "telegram_send")
    def test_dry_run_does_not_send_or_change_dedup_state(self, send, _collect):
        state_path = self.root / "data/seen_jobs.json"
        before = state_path.read_bytes()
        self.assertEqual(main.run(dry_run=True), 0)
        self.assertFalse(send.called)
        self.assertEqual(state_path.read_bytes(), before)

    def jobs(self):
        return [{'id': str(i), 'title': 'DevOps Engineer', 'company': 'Acme',
                 'source': 'remotive', 'source_id': str(i), 'url': f'https://example.com/{i}',
                 'location': 'Worldwide', 'text': 'Azure', 'work_mode': 'remote'} for i in range(3)]

    @patch.object(main, 'telegram_send')
    def test_prepare_reserves_without_sending_and_notify_requires_reservation(self, send):
        with patch.object(main, 'collect', return_value=(self.jobs(), {})):
            self.assertEqual(main.run(phase='prepare'), 0)
        send.assert_not_called()
        state = main.read_json(self.root / 'data/seen_jobs.json')
        self.assertEqual(state['jobs']['0']['status'], 'sending')
        state['jobs']['0']['reservation'] = 'wrong'
        main.atomic_json(self.root / 'data/seen_jobs.json', state)
        self.assertEqual(main.notify(), 5)
        send.assert_not_called()

    def test_partial_delivery_keeps_receipts_uncertainty_and_unsent_pending(self):
        def partial(*args, checkpoint, **kwargs):
            checkpoint(['0'], 19)
            raise DeliveryError('uncertain', ['1'])
        with patch.object(main, 'collect', return_value=(self.jobs(), {})), patch.object(main, 'telegram_send', side_effect=partial):
            self.assertEqual(main.run(), 4)
        state = main.read_json(self.root / 'data/seen_jobs.json')['jobs']
        self.assertEqual([state[str(i)]['status'] for i in range(3)], ['notified', 'uncertain', 'pending'])
        self.assertEqual(state['0']['message_ids'], [19])
        with patch.object(main, 'collect', return_value=(self.jobs(), {})):
            self.assertEqual(main.run(phase='prepare'), 0)
        self.assertEqual([x['id'] for x in main.read_json(self.root / 'data/outbox.json')['jobs']], ['2'])

    def test_interrupted_reservation_is_not_automatically_retried(self):
        with patch.object(main, 'collect', return_value=(self.jobs(), {})):
            main.run(phase='prepare')
            main.run(phase='prepare')
        self.assertEqual(main.read_json(self.root / 'data/outbox.json')['jobs'], [])
        self.assertEqual(main.read_json(self.root / 'data/seen_jobs.json')['jobs']['0']['status'], 'uncertain')

    @patch.object(main, 'telegram_send', return_value={'message_ids': [19]})
    def test_cross_run_mirror_url_is_not_notified_twice(self, _send):
        jobs = self.jobs()[:1]
        with patch.object(main, 'collect', return_value=(jobs, {})):
            main.run()
        mirror = {**self.jobs()[0], 'id': 'mirror', 'source': 'remoteok'}
        with patch.object(main, 'collect', return_value=([mirror], {})):
            main.run(phase='prepare')
        self.assertEqual(main.read_json(self.root / 'data/outbox.json')['jobs'], [])


if __name__ == "__main__":
    unittest.main()
