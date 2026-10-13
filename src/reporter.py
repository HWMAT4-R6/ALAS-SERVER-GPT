"""Two-hour report slots: local evidence, optional DeepSeek draft, QQ SMTP send.

Server timezone must be Asia/Shanghai; slots are aligned to fixed hours in
local time. Sending is opt-in (`mail_send_enabled`) and limited to one attempt
per slot: a SENT receipt is written only after SMTP confirms, a failed slot is
recorded and never retried. Evidence covers monitor status, event deltas and
the latest screenshot, bounded to keep the mail small.
"""
import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import time

from . import runtime
from .mailer import append_receipt, send, sent_slot

MAX_EVIDENCE_CHARS = 4000
MAX_DELTA_LINES = 200


def slot_start(moment, hours):
    """Floor local time to the fixed slot boundary of the given interval."""
    hours = max(1, int(hours))
    floored = moment.replace(minute=0, second=0, microsecond=0)
    return floored - timedelta(hours=moment.hour % hours)


def load_state(folder):
    path = Path(folder) / 'report-state.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_state(folder, state):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / 'report-state.tmp'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(folder / 'report-state.json')


def event_delta(folder, start):
    """Return (recent events, new count, absolute count) after line `start`."""
    path = Path(folder) / 'events.jsonl'
    lines = []
    if path.exists():
        lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    start = max(0, min(int(start), len(lines)))
    fresh = []
    for line in lines[start:][-MAX_DELTA_LINES:]:
        try:
            fresh.append(json.loads(line))
        except ValueError:
            continue
    return fresh, len(lines) - start, len(lines)


def latest_screenshot(folder):
    folder = Path(folder)
    shots = sorted(folder.glob('screen-*.png'), key=lambda p: p.stat().st_mtime)
    if not shots:
        return None
    newest = shots[-1]
    return {'name': newest.name, 'sha256': sha256(newest.read_bytes()).hexdigest(),
            'at': datetime.fromtimestamp(newest.stat().st_mtime).isoformat()}


def read_json(folder, name):
    try:
        return json.loads((Path(folder) / name).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def build_evidence(folder, state):
    """Compose bounded evidence text and the new absolute event count."""
    events, new_count, event_total = event_delta(folder, state.get('events_reported', 0))
    counts = {}
    for event in events:
        key = str(event.get('event', 'unknown'))
        counts[key] = counts.get(key, 0) + 1
    lines = ['monitor_status: ' + json.dumps(read_json(folder, 'monitor-status.json') or {},
                                             ensure_ascii=False),
             'events_since_last_report: ' + str(new_count),
             'event_counts: ' + json.dumps(counts, ensure_ascii=False)]
    for event in events[-15:]:
        lines.append('event: ' + json.dumps(event, ensure_ascii=False))
    screenshot = latest_screenshot(folder)
    if screenshot:
        lines.append('latest_screenshot: ' + json.dumps(screenshot, ensure_ascii=False))
    if (Path(folder) / 'PAUSE').exists():
        lines.append('pause_marker: true')
    verified = read_json(folder, 'verified-report.json')
    if verified:
        lines.append('verified_report: ' + json.dumps(verified, ensure_ascii=False)[:1500])
    return '\n'.join(lines)[:MAX_EVIDENCE_CHARS], event_total


def local_draft(slot, evidence):
    subject = f'[碧蓝挂机] {slot} 两小时报告'
    body = ('本报告由本地报告器生成（未调用模型）。\n\n'
            '本地证据摘要：\n' + evidence + '\n\n'
            '说明：仅代表本地证据，未核验的奖励/余额不视为已到账；'
            '完整记录见服务器 runtime 目录。')
    return {'subject': subject, 'body': body}


def draft(cfg, folder, slot, evidence):
    """Return (draft, source). The emailer worker runs only when vision is on."""
    if not cfg.get('vision_enabled', False):
        return local_draft(slot, evidence), 'local'
    from . import workers
    workers.configure(cfg)
    try:
        value = workers.run_worker('emailer', evidence)['result']
        subject = str(value['subject']).replace('\n', ' ').strip()
        return {'subject': f'[碧蓝挂机] {slot} {subject}', 'body': str(value['body'])}, 'emailer'
    except Exception as error:
        runtime.record(folder, event='report_draft_fallback', error_type=type(error).__name__)
        return local_draft(slot, evidence), 'local-fallback'


def run_once(cfg, folder=None, now=None, dry_run=False, force=False):
    """Process the current slot once; returns the outcome as a short string."""
    folder = Path(folder or cfg['runtime_dir'])
    folder.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()
    start = slot_start(now, cfg.get('mail_interval_hours', 2))
    slot = start.strftime('%Y-%m-%d %H:00')
    state = load_state(folder)
    if force:
        slot = 'manual-' + now.strftime('%Y-%m-%d %H:%M:%S')
    elif not dry_run:
        if state.get('last_slot') == slot:
            return 'already_processed'
        if not cfg.get('mail_send_enabled', False):
            return 'disabled'
        catchup = max(0, int(cfg.get('mail_catchup_minutes', 30)))
        if (now - start).total_seconds() > catchup * 60:
            state['last_slot'] = slot
            save_state(folder, state)
            runtime.record(folder, event='report_window_missed', slot=slot)
            return 'window_missed'
        if sent_slot(folder, slot):
            state['last_slot'] = slot
            save_state(folder, state)
            return 'already_sent'
    evidence, event_total = build_evidence(folder, state)
    content, source = draft(cfg, folder, slot, evidence)
    subject = str(content['subject']).replace('\n', ' ').strip()
    body = str(content['body']) + f'\n\n-- 报告槽位 {slot} · 本地报告器'
    if dry_run:
        (folder / 'report-preview.txt').write_text(f'Subject: {subject}\n\n{body}', encoding='utf-8')
        runtime.record(folder, event='report_dry_run', slot=slot)
        return 'dry_run'
    # At-most-once per slot: state commits before the attempt, so a crash can
    # skip a slot but can never send it twice.
    state['events_reported'] = event_total
    state['last_slot'] = slot
    save_state(folder, state)
    (folder / 'last-report.json').write_text(json.dumps(
        {'slot': slot, 'subject': subject, 'body': body, 'draft': source,
         'at': datetime.now().isoformat()}, ensure_ascii=False, indent=2), encoding='utf-8')
    runtime.record(folder, event='report_built', slot=slot, draft=source)
    try:
        facts = send(cfg, subject, body)
    except Exception as error:
        append_receipt(folder, slot=slot, status='FAILED', error_type=type(error).__name__)
        runtime.record(folder, event='report_failed', slot=slot, error_type=type(error).__name__)
        return 'failed'
    append_receipt(folder, slot=slot, status='SENT', message_id=facts['message_id'],
                   to=facts['to'], subject_sha256=sha256(subject.encode('utf-8')).hexdigest())
    runtime.record(folder, event='report_sent', slot=slot)
    return 'sent'


def loop(cfg):
    """Process the current slot every minute until PAUSE, like the observer."""
    folder = Path(cfg['runtime_dir'])
    with runtime.single_lock(folder / 'reporter.lock'):
        while not (folder / 'PAUSE').exists():
            try:
                run_once(cfg, folder)
            except Exception as error:
                runtime.record(folder, event='reporter_error', error_type=type(error).__name__)
            for _ in range(60):
                if (folder / 'PAUSE').exists():
                    return
                time.sleep(1)
