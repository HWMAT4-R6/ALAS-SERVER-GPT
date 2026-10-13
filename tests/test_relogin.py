import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import runtime, workers


def settings(folder, **overrides):
    cfg = {'runtime_dir': str(folder), 'poll_seconds': 60, 'image_seconds': 3600,
           'vision_enabled': True, 'mail_send_enabled': True,
           'mail_from': 'sender@qq.com', 'mail_to': 'to@qq.com'}
    cfg.update(overrides)
    return cfg


DELIVERY = {'message_id': '<test@qq.com>', 'to': 'to@qq.com', 'sender': 'sender@qq.com'}

OBSERVATION = {'role': 'imager', 'at': '2026-10-13T16:05:00', 'source': 'screen-1.png',
               'observation_only': True, 'supervisor_review_required': True,
               'result': {'page': 'login', 'pt_balance': None, 'reward_pt': None,
                          'resources': {'oil': None, 'coins': None, 'gems': None},
                          'tasks': [], 'uncertain_fields': []},
               'usage': {}, 'estimated_peak_usd': None, 'id': 'test'}


class ReloginAlertTests(unittest.TestCase):
    def test_login_detection_pauses_once_and_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cfg = settings(folder)
            with patch('src.mailer.send', return_value=DELIVERY) as send:
                first = runtime.relogin_alert(cfg, folder, 'screen-a.png')
                second = runtime.relogin_alert(cfg, folder, 'screen-b.png')
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue((folder / 'PAUSE').exists())
            self.assertEqual(send.call_count, 1)
            self.assertIn('登录页', send.call_args[0][1])
            log = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertEqual(log.count('relogin_detected'), 1)
            self.assertIn('relogin_alert_sent', log)

    def test_existing_pause_suppresses_alert(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / 'PAUSE').touch()
            cfg = settings(folder)
            with patch('src.mailer.send') as send:
                self.assertFalse(runtime.relogin_alert(cfg, folder, 'screen.png'))
            send.assert_not_called()
            self.assertFalse((folder / 'events.jsonl').exists())

    def test_disabled_mail_still_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cfg = settings(folder, mail_send_enabled=False)
            with patch('src.mailer.send') as send:
                self.assertTrue(runtime.relogin_alert(cfg, folder, 'screen.png'))
            send.assert_not_called()
            self.assertTrue((folder / 'PAUSE').exists())
            log = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('relogin_detected', log)
            self.assertIn('relogin_alert_skipped', log)

    def test_alert_failure_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cfg = settings(folder)
            with patch('src.mailer.send', side_effect=RuntimeError('smtp down')):
                self.assertTrue(runtime.relogin_alert(cfg, folder, 'screen.png'))
            log = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('relogin_detected', log)
            self.assertIn('relogin_alert_failed', log)


class ObserveIntegrationTests(unittest.TestCase):
    def test_observer_detects_login_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cfg = settings(folder)
            failures = []

            def launch():
                try:
                    runtime.observe(cfg)
                except Exception as error:
                    failures.append(error)

            with patch.object(runtime, 'online', return_value=True), \
                 patch.object(runtime, 'capture', return_value='digest-1'), \
                 patch.object(workers, 'configure'), \
                 patch.object(workers, 'run_worker', return_value=OBSERVATION), \
                 patch('src.mailer.send', return_value=DELIVERY) as send:
                thread = threading.Thread(target=launch)
                thread.start()
                deadline = time.monotonic() + 15
                pause = folder / 'PAUSE'
                while not pause.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                thread.join(timeout=15)
            self.assertEqual(failures, [])
            self.assertFalse(thread.is_alive())
            self.assertTrue(pause.exists())
            self.assertEqual(send.call_count, 1)
            log = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('relogin_detected', log)
            self.assertIn('relogin_alert_sent', log)

    def test_imager_accepts_login_page_and_rejects_unknown(self):
        value = {'page': 'login', 'pt_balance': None, 'reward_pt': None,
                 'tasks': [], 'uncertain_fields': []}
        workers.validate(value, 'imager')
        with self.assertRaises(ValueError):
            workers.validate({'page': 'hacked', 'pt_balance': None, 'reward_pt': None,
                              'tasks': [], 'uncertain_fields': []}, 'imager')


if __name__ == '__main__':
    unittest.main()
