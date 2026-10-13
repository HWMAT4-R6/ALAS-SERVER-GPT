"""Bounded DeepSeek workers. No game clicks, process changes or email sends."""
import argparse
import base64
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

SETTINGS = {}
ROOT = Path(__file__).resolve().parents[1] / 'runtime'
ROOT.mkdir(parents=True, exist_ok=True)
LEDGER = ROOT / 'usage.jsonl'
PROMPTS = {
    'imager': '''Read only visible screenshot evidence. Return JSON:
{"page":"shop|daily_tasks|home|reward|commission|dorm|battle|login|unknown",
"pt_balance":null,"reward_pt":null,"resources":{"oil":null,"coins":null,"gems":null},
"tasks":[{"name":"exact visible task text","progress":"x/y","pt":null,
"status":"completed|claimable|incomplete|unknown"}],"uncertain_fields":[]}.
Tasks top-to-bottom; exact icon digits, distinguish 3 from 5; illegible=null.
Read resources only on home; tasks may be daily or history but history page=unknown.
Balance only when on shop page. For a cropped PT reward icon, set page=reward and
reward_pt to the exact visible integer; other fields null/empty. page=login only for
an account login or re-login screen (credential input or relogin prompt), never for
loading screens. Do not infer hidden data or suggest clicks.''',
    'emailer': '''Prepare a short Chinese progress email from supplied evidence only.
Return JSON {"subject":"...","body":"..."}. Distinguish verified receipts from
estimates and pending actions. Missing evidence means unknown. Never claim sent.
Only report given facts. No fabricated completion or numeric values.''',
    'assembler': '''Diagnose supplied ALAS/ADB evidence. Return JSON
{"diagnosis":"...","suggestions":["..."],"needs_supervisor":true}.
Do not execute anything. Distinguish observations from hypotheses. Avoid source,
fleet or configuration changes unless proposing review by the supervisor.'''
}


def validate(value, role):
    if not isinstance(value, dict):
        raise ValueError('Worker result must be an object')
    if role == 'imager':
        if value.get('page') not in {'shop', 'daily_tasks', 'home', 'reward',
                                      'commission', 'dorm', 'battle', 'login', 'unknown'}:
            raise ValueError('Unknown page enum')
        balance = value.get('pt_balance')
        if balance is not None and (type(balance) is not int or not 0 <= balance <= 1000000):
            raise ValueError('Invalid PT balance')
        if balance is not None and value['page'] != 'shop':
            raise ValueError('Balance lacks shop evidence')
        reward = value.get('reward_pt')
        if reward is not None and (value['page'] != 'reward' or type(reward) is not int or not 0 <= reward <= 100000):
            raise ValueError('Invalid reward observation')
        if not isinstance(value.get('tasks'), list) or not isinstance(value.get('uncertain_fields'), list):
            raise ValueError('Missing task or uncertainty arrays')
        for task in value['tasks']:
            if not isinstance(task, dict) or not isinstance(task.get('progress'), str):
                raise ValueError('Invalid progress')
            if not re.fullmatch(r'\d+/\d+', task['progress']):
                raise ValueError('Malformed progress')
            if task.get('status') not in {'completed', 'claimable', 'incomplete', 'unknown'}:
                raise ValueError('Invalid status')
            if task.get('pt') is not None and type(task['pt']) is not int:
                raise ValueError('Invalid reward')
        # Even valid structure is an observation, not proof of reward receipt.
    elif role == 'emailer':
        if not all(isinstance(value.get(k), str) and value[k].strip() for k in ('subject', 'body')):
            raise ValueError('Invalid email draft')
    elif role == 'assembler':
        if not isinstance(value.get('diagnosis'), str) or not isinstance(value.get('suggestions'), list):
            raise ValueError('Invalid diagnostic result')
        if value.get('needs_supervisor') is not True:
            raise ValueError('Assembler must defer execution')
    return value


def configure(settings):
    global SETTINGS, ROOT, LEDGER
    SETTINGS = settings
    ROOT = Path(settings['runtime_dir'])
    ROOT.mkdir(parents=True, exist_ok=True)
    LEDGER = ROOT / 'usage.jsonl'


def usage_cost(usage):
    prices = SETTINGS.get('prices_usd_per_million')
    if not prices:
        return None
    total = usage.get('prompt_tokens', 0)
    cached = usage.get('prompt_cache_hit_tokens', usage.get('prompt_tokens_details', {}).get('cached_tokens', 0))
    return ((total - cached) * prices['input'] + cached * prices['cached_input'] + usage.get('completion_tokens', 0) * prices['output']) / 1000000

def append(path, value):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')


def api_key():
    key = os.getenv(SETTINGS.get('api_key_env', 'DEEPSEEK_API_KEY'))
    if not key and os.name == 'nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as env:
            key = winreg.QueryValueEx(env, SETTINGS.get('api_key_env', 'DEEPSEEK_API_KEY'))[0]
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY not configured')
    return key


def check_daily_cost(role):
    """Daily cost alert: record + optional mail, never block the caller.

    Runs after a successful worker call and after the usage entry is written.
    Unknown costs (None) are excluded from the sum and never treated as zero.
    At most one alert per day; this function must never raise.
    """
    limit = SETTINGS.get('daily_cost_limit_usd')
    if limit is None:
        return
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        total = 0.0
        if LEDGER.exists():
            for line in LEDGER.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get('day') != today:
                    continue
                cost = entry.get('estimated_peak_usd')
                if isinstance(cost, (int, float)):
                    total += cost
        if total <= float(limit):
            return
        state_path = ROOT / 'cost-alert-state.json'
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
        if state.get('alerted_day') == today:
            return
        state['alerted_day'] = today
        tmp = state_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(state_path)
        from .runtime import record
        record(ROOT, event='cost_limit_exceeded', day=today, role=role,
               total_usd=round(total, 4), limit_usd=limit)
        if SETTINGS.get('mail_send_enabled', False):
            try:
                from .mailer import send
                send(SETTINGS, '[碧蓝挂机] 当日模型费用已达上限（仅提醒，不阻断）',
                     f'当日（{today}）估算费用合计约 {total:.4f} USD，已达到上限 {limit} USD。\n'
                     '说明：估算基于 token 用量与价格表，不是账单；ALAS 与观察/报告流程不因此中断。\n'
                     '如需调整，请编辑 config/settings.json 的 daily_cost_limit_usd。')
                record(ROOT, event='cost_alert_sent', day=today)
            except Exception as error:
                record(ROOT, event='cost_alert_failed', day=today,
                       error_type=type(error).__name__)
    except Exception:
        # Cost accounting must never break a worker call.
        return


def _run_worker(role, text='', image_path=None, crop=None):
    if SETTINGS.get('model', 'UNCONFIGURED') in ('UNCONFIGURED', 'SET_TO_A_VERIFIED_VISION_MODEL'):
        raise RuntimeError('Configure a verified model before API use')
    if len(text) > 16000:
        raise ValueError('Evidence exceeds bounded worker context')
    blocks = [{'type': 'text', 'text': PROMPTS[role] +
               '\nCurrent report time (not reference day): ' + datetime.now().isoformat() +
               '\nEvidence:\n' + text}]
    if image_path:
        from PIL import Image
        picture = Image.open(image_path).convert('RGB')
        if crop:
            x1, y1, x2, y2 = crop
            if not (0 <= x1 < x2 <= picture.width and 0 <= y1 < y2 <= picture.height):
                raise ValueError('Crop out of bounds')
            picture = picture.crop(crop)
            picture = picture.resize((picture.width * 3, picture.height * 3))
        buffer = io.BytesIO()
        picture.save(buffer, format='PNG')
        if buffer.tell() > 4 * 1024 * 1024:
            raise ValueError('Image exceeds pilot request budget')
        blocks.append({'type': 'image_url', 'image_url': {
            'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
            'detail': 'original'}})
    payload = {'model': SETTINGS.get('model', 'UNCONFIGURED'), 'thinking': {'type': 'disabled'},
               'max_tokens': SETTINGS.get('max_tokens', 800), 'response_format': {'type': 'json_object'},
               'messages': [{'role': 'user', 'content': blocks}]}
    body = json.dumps(payload).encode()
    if len(body) > 6 * 1024 * 1024:
        raise ValueError('Request too large')
    key = api_key()
    day = datetime.now().strftime('%Y-%m-%d')
    for attempt in range(3):
        call_id = uuid.uuid4().hex
        append(LEDGER, {'day': day, 'at': datetime.now().isoformat(), 'id': call_id,
                        'role': role, 'event': 'request_started'})
        started = time.monotonic()
        try:
            request = urllib.request.Request(SETTINGS.get('api_base', 'https://api.deepseek.com').rstrip('/') + '/chat/completions', data=body,
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=SETTINGS.get('request_timeout', 30)) as response:
                raw = json.load(response)
            usage = raw.get('usage')
            append(LEDGER, {'day': day, 'at': datetime.now().isoformat(), 'id': call_id,
                'role': role, 'usage': usage, 'estimated_peak_usd': usage_cost(usage) if usage else None,
                'elapsed_s': round(time.monotonic() - started, 3)})
            if not usage:
                raise ValueError('Missing billable usage')
            value = validate(json.loads(raw['choices'][0]['message']['content']), role)
            result = {'role': role, 'at': datetime.now().isoformat(), 'source': str(image_path) if image_path else None,
                      'observation_only': True, 'supervisor_review_required': True,
                      'result': value, 'usage': usage,
                      'estimated_peak_usd': usage_cost(usage), 'id': call_id}
            append(ROOT / 'results.jsonl', result)
            check_daily_cost(role)
            return result
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            code = getattr(error, 'code', None)
            append(LEDGER, {'day': day, 'id': call_id, 'role': role,
                            'error_type': type(error).__name__, 'http_status': code,
                            'usage_unknown': True})
            if attempt == 2 or (code is not None and code not in (429, 500, 502, 503, 504)):
                raise RuntimeError('API failed; see sanitized ledger') from None
            time.sleep(2 ** attempt)
        except (ValueError, KeyError, TypeError):
            append(LEDGER, {'day': day, 'id': call_id, 'role': role,
                            'error_type': 'invalid_worker_result'})
            raise ValueError('Worker result rejected; preserve screenshot and escalate') from None


def run_worker(role, text='', image_path=None, crop=None):
    # OS lock is released on process exit, including crashes. Serialize worker calls.
    with (ROOT / 'worker.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            return _run_worker(role, text, image_path, crop)
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=PROMPTS)
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'config/settings.json'))
    parser.add_argument('--image')
    parser.add_argument('--evidence')
    parser.add_argument('--crop', nargs=4, type=int)
    args = parser.parse_args()
    from .runtime import load
    configure(load(args.config))
    evidence = Path(args.evidence).read_text(encoding='utf-8') if args.evidence else ''
    print(json.dumps(run_worker(args.role, evidence, args.image, args.crop), ensure_ascii=True))
