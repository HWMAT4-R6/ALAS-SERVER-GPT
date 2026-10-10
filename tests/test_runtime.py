import io
import json
import tempfile
import sys
import threading
import time
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from src import runtime, workers


class RuntimeTests(unittest.TestCase):
    def test_png_failure_is_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'x.png'
            with patch('src.runtime.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = b'error not png'
                with self.assertRaises(RuntimeError):
                    runtime.capture({'adb': 'adb', 'serial': 'local'}, out)
            self.assertFalse(out.exists())

    def test_empty_process_inventory_is_not_existing_alas(self):
        with patch.object(runtime.os, 'name', 'nt'), patch('src.runtime.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'[]'
            self.assertFalse(runtime.existing_alas())
            run.return_value.stdout = b'[123]'
            self.assertTrue(runtime.existing_alas())

    def test_pause_stops_real_owned_child(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'alas.py').write_text('import time\nclass AzurLaneAutoScript:\n def __init__(self, name): pass\n def loop(self): time.sleep(120)\n')
            cfg = {'runtime_dir': str(root / 'runtime'), 'alas_root': d,
                   'alas_python': sys.executable, 'profile': 'alas', 'max_starts': 1}
            failures = []
            def launch():
                try:
                    runtime.supervise(cfg)
                except Exception as error:
                    failures.append(error)
            with patch.object(runtime, 'existing_alas', return_value=False), patch.object(runtime, 'online', return_value=True):
                thread = threading.Thread(target=launch)
                thread.start()
                deadline = time.monotonic() + 10
                state = root / 'runtime/process.json'
                while not state.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(state.exists())
                (root / 'runtime/PAUSE').touch()
                thread.join(timeout=20)
                self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertFalse(state.exists())
            self.assertIn('supervisor_stopped', (root / 'runtime/events.jsonl').read_text())

    def test_auth_failure_not_retried_or_secret_logged(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(workers, 'ROOT', Path(d)), patch.object(workers, 'LEDGER', Path(d) / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', {'model': 'test'}), patch.object(workers, 'api_key', return_value='test-placeholder'), \
                 patch('src.workers.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 401, 'private-response', {}, None)) as call:
                with self.assertRaises(RuntimeError):
                    workers.run_worker('emailer', 'verified')
            self.assertEqual(call.call_count, 1)
            log = (Path(d) / 'usage.jsonl').read_text()
            self.assertNotIn('test-placeholder', log)
            self.assertNotIn('private-response', log)
            self.assertIn('usage_unknown', log)

    def test_duplicate_lock_rejected_and_released(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'lock'
            with runtime.single_lock(p):
                with self.assertRaises((OSError, RuntimeError)):
                    with runtime.single_lock(p):
                        pass
            with runtime.single_lock(p):
                pass

    def test_pause_prevents_child_launch(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'PAUSE').touch()
            with patch('src.runtime.subprocess.Popen') as spawn:
                runtime.supervise({'runtime_dir': d, 'alas_root': d,
                                   'alas_python': 'missing', 'profile': 'alas'})
            spawn.assert_not_called()

    def test_disabled_prices_are_unknown_not_zero(self):
        with patch.object(workers, 'SETTINGS', {}):
            self.assertIsNone(workers.usage_cost({'prompt_tokens': 100}))

    def test_model_is_configured_and_billable_usage_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            response = {'usage': {'prompt_tokens': 10, 'completion_tokens': 2},
                        'choices': [{'message': {'content': json.dumps({'subject': 'test', 'body': 'test'})}}]}
            with patch.object(workers, 'ROOT', Path(d)), \
                 patch.object(workers, 'LEDGER', Path(d) / 'usage.jsonl'), \
                 patch.object(workers, 'SETTINGS', {'model': 'test-model'}), \
                 patch.object(workers, 'api_key', return_value='test-placeholder'), \
                 patch('src.workers.urllib.request.urlopen', return_value=io.StringIO(json.dumps(response))) as call:
                result = workers.run_worker('emailer', 'verified')
            payload = json.loads(call.call_args[0][0].data)
            self.assertEqual(payload['model'], 'test-model')
            self.assertEqual(result['usage']['prompt_tokens'], 10)
            self.assertIsNone(result['estimated_peak_usd'])

    def test_current_tasks_not_restricted_to_old_pt_event(self):
        value = {'page': 'daily_tasks', 'pt_balance': None, 'reward_pt': None,
                 'tasks': [{'progress': '3/3', 'pt': 300, 'status': 'claimable'}], 'uncertain_fields': []}
        workers.validate(value, 'imager')

    def test_balance_requires_shop_and_nonnegative_value(self):
        for page, balance in [('home', 500), ('shop', -1)]:
            with self.assertRaises(ValueError):
                workers.validate({'page': page, 'pt_balance': balance, 'tasks': [], 'uncertain_fields': []}, 'imager')


if __name__ == '__main__':
    unittest.main()
