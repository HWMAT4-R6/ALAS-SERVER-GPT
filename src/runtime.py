import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
PROJECT = Path(__file__).resolve().parents[1]


def remove_if_present(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def load(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    for name in ('adb', 'alas_root', 'alas_python', 'runtime_dir'):
        value = Path(cfg[name])
        cfg[name] = str(value if value.is_absolute() else (path.parent / value).resolve())
    cfg['config_path'] = str(path)
    return cfg


def record(folder, **values):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(at=datetime.now().isoformat(), **values), ensure_ascii=False) + '\n')


def write_status(folder, **values):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / 'status.tmp'
    tmp.write_text(json.dumps(dict(at=datetime.now().isoformat(), **values), indent=2), encoding='utf-8')
    tmp.replace(folder / 'monitor-status.json')


@contextmanager
def single_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def adb(cfg, *args):
    return subprocess.run([cfg['adb'], *args], capture_output=True, timeout=15, creationflags=FLAGS)


def online(cfg):
    adb(cfg, 'connect', cfg['serial'])
    r = adb(cfg, '-s', cfg['serial'], 'get-state')
    return r.returncode == 0 and r.stdout.strip() == b'device'


def capture(cfg, out):
    r = adb(cfg, '-s', cfg['serial'], 'exec-out', 'screencap', '-p')
    if r.returncode or not r.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Screenshot unavailable or not PNG')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.stdout)
    return hashlib.sha256(r.stdout).hexdigest()


def existing_alas():
    if os.name != 'nt':
        raise RuntimeError('Supervisor supports Windows only')
    script = "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -match 'AzurLaneAutoScript|from alas import' } | Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress"
    r = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True,
                       timeout=20, creationflags=FLAGS)
    if r.returncode:
        raise RuntimeError('Cannot verify existing ALAS processes')
    raw = r.stdout.decode('utf-8-sig').strip()
    return bool(json.loads(raw)) if raw else False


def stop_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=15)


def supervise(cfg):
    folder = Path(cfg['runtime_dir'])
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'PAUSE').exists():
        record(folder, event='start_refused_pause')
        return
    with single_lock(folder / 'supervisor.lock'):
        if existing_alas():
            raise RuntimeError('Existing ALAS detected; close it before starting')
        if not online(cfg):
            raise RuntimeError('ADB offline; emulator was not started')
        deadline = time.monotonic() + float(cfg.get('run_hours', 10)) * 3600
        child = None
        try:
            for attempt in range(int(cfg.get('max_starts', 3))):
                if time.monotonic() >= deadline or (folder / 'PAUSE').exists():
                    break
                if not online(cfg):
                    record(folder, event='offline_stop')
                    break
                # New subprocess imports ALAS from its configured working directory.
                code = "from alas import AzurLaneAutoScript; AzurLaneAutoScript(" + repr(cfg['profile']) + ").loop()"
                with (folder / 'alas.log').open('a', encoding='utf-8') as output:
                    child = subprocess.Popen([cfg['alas_python'], '-u', '-c', code],
                                             cwd=cfg['alas_root'], stdout=output,
                                             stderr=subprocess.STDOUT, creationflags=FLAGS)
                    (folder / 'process.json').write_text(json.dumps({'supervisor': os.getpid(),
                        'child': child.pid, 'started': datetime.now().isoformat()}), encoding='utf-8')
                    record(folder, event='alas_started', child=child.pid, attempt=attempt + 1)
                    while child.poll() is None and time.monotonic() < deadline and not (folder / 'PAUSE').exists():
                        time.sleep(1)
                    if child.poll() is None:
                        stop_child(child)
                        break
                    record(folder, event='alas_exit', code=child.returncode)
                # Interruption is checked during retry delay, never a blind sleep/restart.
                for _ in range(60):
                    if (folder / 'PAUSE').exists() or time.monotonic() >= deadline:
                        break
                    time.sleep(1)
        finally:
            if child is not None:
                stop_child(child)
            remove_if_present(folder / 'process.json')
            record(folder, event='supervisor_stopped')


def observe(cfg):
    folder = Path(cfg['runtime_dir'])
    interval = max(60, int(cfg.get('poll_seconds', 60)))
    image_interval = max(interval, int(cfg.get('image_seconds', 3600)))
    last_image = 0
    last_hash = None
    with single_lock(folder / 'observer.lock'):
        while not (folder / 'PAUSE').exists():
            try:
                connected = online(cfg)
                write_status(folder, adb_online=connected, observation_only=True)
                if connected and time.monotonic() - last_image >= image_interval:
                    last_image = time.monotonic()
                    out = folder / ('screen-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.png')
                    digest = capture(cfg, out)
                    record(folder, event='screenshot', filename=out.name, sha256=digest)
                    if digest != last_hash and cfg.get('vision_enabled', False):
                        from . import workers
                        workers.configure(cfg)
                        result = workers.run_worker('imager', image_path=str(out))
                        (folder / 'latest-observation.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
                    last_hash = digest
            except Exception as error:
                record(folder, event='observer_error', error_type=type(error).__name__)
            for _ in range(interval):
                if (folder / 'PAUSE').exists():
                    return
                time.sleep(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['doctor', 'capture', 'supervisor', 'observer', 'pause', 'resume'])
    p.add_argument('--config', default=str(PROJECT / 'config/settings.json'))
    p.add_argument('--out')
    p.add_argument('--home-verified', action='store_true')
    args = p.parse_args()
    cfg = load(args.config)
    folder = Path(cfg['runtime_dir'])
    folder.mkdir(parents=True, exist_ok=True)
    if args.command == 'pause':
        (folder / 'PAUSE').touch()
        record(folder, event='pause_requested')
    elif args.command == 'resume':
        if not args.home_verified:
            p.error('Resume requires fresh supported-home verification and --home-verified')
        remove_if_present(folder / 'PAUSE')
        record(folder, event='resume_acknowledged')
    elif args.command == 'supervisor':
        if not args.home_verified:
            p.error('Start requires fresh supported-home verification and --home-verified')
        supervise(cfg)
    elif args.command == 'observer':
        observe(cfg)
    elif args.command == 'capture':
        if not online(cfg):
            raise RuntimeError('ADB offline')
        print(capture(cfg, args.out or folder / 'check.png'))
    else:
        checks = {key: Path(cfg[key]).exists() for key in ('adb', 'alas_python', 'alas_root')}
        checks['pause'] = (folder / 'PAUSE').exists()
        checks['adb_online'] = online(cfg) if checks['adb'] else False
        checks['existing_alas'] = existing_alas()
        print(json.dumps(checks, indent=2))
        if not all(checks[k] for k in ('adb', 'alas_python', 'alas_root', 'adb_online')):
            sys.exit(2)


if __name__ == '__main__':
    main()
