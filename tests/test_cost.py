import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src import workers

TODAY = datetime.now().strftime('%Y-%m-%d')


def settings(**overrides):
    cfg = {'runtime_dir': None, 'mail_send_enabled': False,
           'mail_from': 'sender@qq.com', 'mail_to': 'to@qq.com'}
    cfg.update(overrides)
    return cfg


def write_ledger(folder, entries):
    lines = [json.dumps(entry) for entry in entries]
    (Path(folder) / 'usage.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')


class CostLimitTests(unittest.TestCase):
    def test_limit_unset_records_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': 99.0}])
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings()):
                with patch('src.mailer.send') as send:
                    workers.check_daily_cost('emailer')
            send.assert_not_called()
            self.assertFalse((folder / 'events.jsonl').exists())

    def test_under_limit_records_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': 0.5}])
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings(daily_cost_limit_usd=1.0)):
                workers.check_daily_cost('emailer')
            self.assertFalse((folder / 'events.jsonl').exists())

    def test_over_limit_alerts_once_with_mail(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': 0.5}])
            cfg = settings(daily_cost_limit_usd=0.1, mail_send_enabled=True)
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', cfg):
                with patch('src.mailer.send',
                           return_value={'message_id': '<x>', 'to': 't', 'sender': 's'}) as send:
                    workers.check_daily_cost('emailer')
                    workers.check_daily_cost('emailer')
            self.assertEqual(send.call_count, 1)
            events = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertEqual(events.count('cost_limit_exceeded'), 1)
            self.assertEqual(events.count('cost_alert_sent'), 1)
            state = json.loads((folder / 'cost-alert-state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['alerted_day'], TODAY)

    def test_over_limit_with_mail_disabled_records_event_only(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': 0.5}])
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings(daily_cost_limit_usd=0.1)):
                with patch('src.mailer.send') as send:
                    workers.check_daily_cost('emailer')
            send.assert_not_called()
            events = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('cost_limit_exceeded', events)
            self.assertNotIn('cost_alert_sent', events)
            self.assertNotIn('cost_alert_failed', events)

    def test_send_failure_does_not_raise_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': 0.5}])
            cfg = settings(daily_cost_limit_usd=0.1, mail_send_enabled=True)
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', cfg):
                with patch('src.mailer.send', side_effect=RuntimeError('smtp down')):
                    workers.check_daily_cost('emailer')
            events = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('cost_limit_exceeded', events)
            self.assertIn('cost_alert_failed', events)

    def test_worker_call_not_blocked_when_over_limit(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            response = {'usage': {'prompt_tokens': 1000, 'completion_tokens': 1000},
                        'choices': [{'message': {'content': json.dumps({'subject': 's', 'body': 'b'})}}]}
            cfg = settings(daily_cost_limit_usd=0.000001,
                           prices_usd_per_million={'input': 1, 'cached_input': 1, 'output': 1},
                           model='test-model')
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', cfg), \
                 patch.object(workers, 'api_key', return_value='k'), \
                 patch('src.workers.urllib.request.urlopen',
                       return_value=io.StringIO(json.dumps(response))):
                result = workers.run_worker('emailer', 'evidence')
            self.assertEqual(result['result']['subject'], 's')
            events = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('cost_limit_exceeded', events)

    def test_none_costs_excluded_and_not_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': None},
                             {'day': TODAY, 'estimated_peak_usd': 0.5}])
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings(daily_cost_limit_usd=0.4)):
                workers.check_daily_cost('emailer')
            events = (folder / 'events.jsonl').read_text(encoding='utf-8')
            self.assertIn('cost_limit_exceeded', events)
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            write_ledger(d, [{'day': TODAY, 'estimated_peak_usd': None}])
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings(daily_cost_limit_usd=0.0)):
                workers.check_daily_cost('emailer')
            self.assertFalse((folder / 'events.jsonl').exists())

    def test_missing_or_corrupt_ledger_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            with patch.object(workers, 'ROOT', folder), \
                 patch.object(workers, 'LEDGER', folder / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', settings(daily_cost_limit_usd=0.1)):
                workers.check_daily_cost('emailer')
                (folder / 'usage.jsonl').write_text('not json\n\n{"day": "x"}\n', encoding='utf-8')
                workers.check_daily_cost('emailer')
            self.assertFalse((folder / 'events.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
