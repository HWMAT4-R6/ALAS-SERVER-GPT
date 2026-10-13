import contextlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src import mailer, reporter


def settings(folder, **overrides):
    cfg = {'runtime_dir': str(folder), 'mail_send_enabled': True, 'mail_interval_hours': 2,
           'mail_catchup_minutes': 30, 'mail_from': 'sender@qq.com', 'mail_to': 'to@qq.com',
           'request_timeout': 5, 'vision_enabled': False}
    cfg.update(overrides)
    return cfg


DELIVERY = {'message_id': '<test@qq.com>', 'to': 'to@qq.com', 'sender': 'sender@qq.com'}


class SlotTests(unittest.TestCase):
    def test_slots_align_to_fixed_hours(self):
        self.assertEqual(reporter.slot_start(datetime(2026, 10, 13, 16, 59), 2),
                         datetime(2026, 10, 13, 16, 0))
        self.assertEqual(reporter.slot_start(datetime(2026, 10, 13, 17, 0), 2),
                         datetime(2026, 10, 13, 16, 0))
        self.assertEqual(reporter.slot_start(datetime(2026, 10, 13, 0, 30), 2),
                         datetime(2026, 10, 13, 0, 0))
        self.assertEqual(reporter.slot_start(datetime(2026, 10, 13, 23, 59), 3),
                         datetime(2026, 10, 13, 21, 0))


class ReportTests(unittest.TestCase):
    def test_disabled_mail_sends_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d, mail_send_enabled=False)
            with patch('src.reporter.send') as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5)),
                                 'disabled')
            send.assert_not_called()
            self.assertFalse((Path(d) / 'mail-receipts.jsonl').exists())

    def test_window_missed_once_without_send(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d)
            with patch('src.reporter.send') as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 45)),
                                 'window_missed')
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 46)),
                                 'already_processed')
            send.assert_not_called()
            self.assertIn('report_window_missed', (Path(d) / 'events.jsonl').read_text(encoding='utf-8'))

    def test_sent_once_then_no_resend_same_slot(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d)
            with patch('src.reporter.send', return_value=DELIVERY) as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5)),
                                 'sent')
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 6)),
                                 'already_processed')
            self.assertEqual(send.call_count, 1)
            records = mailer.receipts(d)
            self.assertEqual(records[-1]['status'], 'SENT')
            self.assertEqual(records[-1]['slot'], '2026-10-13 16:00')
            self.assertIsNotNone(mailer.sent_slot(d, '2026-10-13 16:00'))

    def test_failed_slot_recorded_and_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d)
            with patch('src.reporter.send', side_effect=RuntimeError('smtp down')) as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5)),
                                 'failed')
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 40)),
                                 'already_processed')
            self.assertEqual(send.call_count, 1)
            records = mailer.receipts(d)
            self.assertEqual([record['status'] for record in records], ['FAILED'])
            self.assertIsNone(mailer.sent_slot(d, '2026-10-13 16:00'))

    def test_dry_run_writes_preview_without_sending(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d)
            with patch('src.reporter.send') as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5),
                                                   dry_run=True), 'dry_run')
            send.assert_not_called()
            self.assertFalse((Path(d) / 'mail-receipts.jsonl').exists())
            self.assertIn('Subject:', (Path(d) / 'report-preview.txt').read_text(encoding='utf-8'))

    def test_dry_run_preview_available_while_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d, mail_send_enabled=False)
            with patch('src.reporter.send') as send:
                self.assertEqual(reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5),
                                                   dry_run=True), 'dry_run')
            send.assert_not_called()
            self.assertTrue((Path(d) / 'report-preview.txt').exists())
            self.assertEqual(reporter.load_state(d), {})

    def test_dry_run_does_not_consume_event_delta(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / 'events.jsonl').write_text('{"event": "alpha"}\n', encoding='utf-8')
            cfg = settings(d)
            with patch('src.reporter.send', return_value=DELIVERY):
                reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5), dry_run=True)
            self.assertNotIn('events_reported', reporter.load_state(d))
            with patch('src.reporter.send', return_value=DELIVERY):
                reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 6))
            last = json.loads((folder / 'last-report.json').read_text(encoding='utf-8'))
            self.assertIn('alpha', last['body'])

    def test_evidence_reports_only_new_events(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / 'events.jsonl').write_text('{"event": "first"}\n', encoding='utf-8')
            cfg = settings(d)
            with patch('src.reporter.send', return_value=DELIVERY):
                reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5))
            with (folder / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write('{"event": "second"}\n')
            with patch('src.reporter.send', return_value=DELIVERY):
                reporter.run_once(cfg, now=datetime(2026, 10, 13, 18, 5))
            self.assertEqual(len(mailer.receipts(d)), 2)
            last = json.loads((folder / 'last-report.json').read_text(encoding='utf-8'))
            self.assertIn('second', last['body'])
            self.assertNotIn('first', last['body'])

    def test_force_sends_manual_slot_even_when_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = settings(d, mail_send_enabled=False)
            with patch('src.reporter.send', return_value=DELIVERY) as send:
                outcome = reporter.run_once(cfg, now=datetime(2026, 10, 13, 16, 5), force=True)
            self.assertEqual(outcome, 'sent')
            self.assertEqual(send.call_count, 1)
            self.assertTrue(mailer.receipts(d)[-1]['slot'].startswith('manual-'))


class MailerTests(unittest.TestCase):
    def test_auth_env_wins_and_missing_is_rejected(self):
        with patch.dict(os.environ, {'QQ_SMTP_AUTH_UNIT': 'unit-value'}):
            self.assertEqual(mailer.auth_code({'mail_auth_env': 'QQ_SMTP_AUTH_UNIT'}), 'unit-value')
        winreg_guard = (patch('winreg.OpenKey', side_effect=FileNotFoundError)
                        if os.name == 'nt' else contextlib.nullcontext())
        with patch.dict(os.environ, {}, clear=True), winreg_guard:
            with self.assertRaises(RuntimeError):
                mailer.auth_code({'mail_auth_env': 'QQ_SMTP_AUTH_MISSING_FOR_TEST'})

    def test_auth_file_used_when_env_absent(self):
        with tempfile.TemporaryDirectory() as d:
            secret = Path(d) / 'secret.txt'
            secret.write_text('file-value\n', encoding='utf-8')
            winreg_guard = (patch('winreg.OpenKey', side_effect=FileNotFoundError)
                            if os.name == 'nt' else contextlib.nullcontext())
            with patch.dict(os.environ, {}, clear=True), winreg_guard:
                self.assertEqual(mailer.auth_code({'mail_auth_env': 'QQ_SMTP_AUTH_MISSING_FOR_TEST',
                                                   'mail_auth_file': str(secret)}), 'file-value')

    def test_send_uses_ssl_and_returns_delivery_facts(self):
        recorded = {}

        class FakeSMTP:
            def __init__(self, host, port, context=None, timeout=None):
                recorded['host'], recorded['port'] = host, port

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def login(self, user, code):
                recorded['login'] = (user, code)

            def sendmail(self, sender, recipients, text):
                recorded['mail'] = (sender, recipients, text)
                return {}

        with patch('src.mailer.smtplib.SMTP_SSL', FakeSMTP), \
             patch('src.mailer.auth_code', return_value='code-placeholder'):
            facts = mailer.send(settings('.'), '主题', '正文')
        self.assertEqual((recorded['host'], recorded['port']), ('smtp.qq.com', 465))
        self.assertEqual(recorded['login'], ('sender@qq.com', 'code-placeholder'))
        self.assertEqual(recorded['mail'][0], 'sender@qq.com')
        self.assertEqual(recorded['mail'][1], ['to@qq.com'])
        self.assertIn('Subject', recorded['mail'][2])
        self.assertTrue(facts['message_id'].startswith('<'))

    def test_refused_recipient_raises(self):
        class RefusingSMTP:
            def __init__(self, host, port, context=None, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def login(self, user, code):
                pass

            def sendmail(self, sender, recipients, text):
                return {'to@qq.com': (550, b'refused')}

        with patch('src.mailer.smtplib.SMTP_SSL', RefusingSMTP), \
             patch('src.mailer.auth_code', return_value='code-placeholder'):
            with self.assertRaises(RuntimeError):
                mailer.send(settings('.'), '主题', '正文')

    def test_oversized_report_rejected_before_smtp(self):
        with self.assertRaises(ValueError):
            mailer.send(settings('.'), 'x' * 201, 'body')


if __name__ == '__main__':
    unittest.main()
