"""QQ Mail SMTP sender for report slots. Standard library only.

Secrets: the authorization code is read from the environment variable named by
`mail_auth_env` (default QQ_SMTP_AUTH), then the Windows user registry, then a
file outside the repository configured as `mail_auth_file`. The code is never
written to receipts, events or logs; receipts contain delivery facts only.
"""
import json
import os
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from pathlib import Path
import smtplib
import ssl

SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
RECEIPT_FILE = 'mail-receipts.jsonl'
MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 20000


def auth_code(cfg):
    """Read the SMTP authorization code (env, then HKCU, then configured file)."""
    name = cfg.get('mail_auth_env', 'QQ_SMTP_AUTH')
    value = os.environ.get(name)
    if not value and os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as env:
                value = winreg.QueryValueEx(env, name)[0]
        except OSError:
            value = None
    if not value and cfg.get('mail_auth_file'):
        path = Path(cfg['mail_auth_file'])
        if path.exists():
            value = path.read_text(encoding='utf-8').strip()
    if not value or not str(value).strip():
        raise RuntimeError('SMTP authorization code is not configured')
    return str(value).strip()


def receipts(folder):
    """Return receipt records, oldest first. Corrupt lines are skipped."""
    path = Path(folder) / RECEIPT_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def sent_slot(folder, slot):
    """Return the SENT receipt of a slot, or None. Used to prevent resends."""
    for record in receipts(folder):
        if record.get('slot') == slot and record.get('status') == 'SENT':
            return record
    return None


def append_receipt(folder, **values):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    record = dict(at=datetime.now().isoformat(), **values)
    with (folder / RECEIPT_FILE).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    return record


def send(cfg, subject, body):
    """Send one plain-text report. Returns delivery facts or raises."""
    sender = cfg.get('mail_from')
    recipient = cfg.get('mail_to')
    if not sender or not recipient:
        raise RuntimeError('mail_from/mail_to are not configured')
    if len(subject) > MAX_SUBJECT_CHARS or len(body) > MAX_BODY_CHARS:
        raise ValueError('Report exceeds size bounds')
    message_id = make_msgid(domain='qq.com')
    message = MIMEText(body, 'plain', 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = formataddr(('ALAS-SERVER', sender))
    message['To'] = recipient
    message['Message-ID'] = message_id
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context,
                          timeout=cfg.get('request_timeout', 30)) as server:
        server.login(sender, auth_code(cfg))
        refused = server.sendmail(sender, [recipient], message.as_string())
    if refused:
        raise RuntimeError('SMTP refused the recipient')
    return {'message_id': message_id, 'to': recipient, 'sender': sender}
