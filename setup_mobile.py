"""Set up private mobile viewing after signing in to Tailscale."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
TARGET = 'http://127.0.0.1:8765'
PORT = 8443


def executable():
    found = shutil.which('tailscale')
    if found:
        return found
    path = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe'
    if path.exists():
        return str(path)
    raise ValueError('Install Tailscale on this PC and phone: https://tailscale.com/download . Sign in with the same account, then run this command again.')


def command(binary, *args):
    result = subprocess.run([binary, *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError(result.stdout + result.stderr)
    return result.stdout


def ready():
    try:
        with urlopen(TARGET, timeout=2) as response:
            return b'<title>Limit Desk' in response.read(4096)
    except Exception:
        return False


def main(stop=False):
    binary = executable()
    config_path = ROOT / '.local/mobile.json'
    if stop:
        command(binary, 'serve', '--https=8443', 'off')
        config_path.unlink(missing_ok=True)
        print('Mobile access disabled.')
        return
    status = json.loads(command(binary, 'status', '--json'))
    if status.get('BackendState') != 'Running':
        raise ValueError('Open Tailscale on this PC, sign in, and connect. Then run this command again.')
    device = status.get('Self') or {}
    name = (device.get('DNSName') or '').rstrip('.')
    user = (status.get('User') or {}).get(str(device.get('UserID')), {})
    login = user.get('LoginName')
    if not name or not login:
        raise ValueError('Could not identify your Tailscale login. Use your personal, untagged PC.')
    host = name + ':' + str(PORT)
    settings = json.loads(command(binary, 'serve', 'status', '--json') or '{}')
    existing = (settings.get('Web') or {}).get(host)
    if existing and ((existing.get('Handlers') or {}).get('/') or {}).get('Proxy') != TARGET:
        raise ValueError('Port 8443 already serves another app. Its settings were preserved.')
    if (settings.get('AllowFunnel') or {}).get(host):
        raise ValueError('Public Funnel is enabled on port 8443. Disable it before using private viewing.')
    if not ready():
        (ROOT / '.local').mkdir(exist_ok=True)
        with (ROOT / '.local/mobile-server.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            if ready():
                break
            time.sleep(.25)
        if not ready():
            raise ValueError('Limit Desk did not start. Check .local/mobile-server.log.')
    config_path.parent.mkdir(exist_ok=True)
    temporary = config_path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'host':host, 'login':login}), encoding='utf-8')
    temporary.replace(config_path)
    print(command(binary, 'serve', '--bg', '--https=8443', TARGET))
    print('With Tailscale connected on your phone, open: https://' + host)
    print('Keep this PC on and awake. Stop access: start-mobile.ps1 -Stop')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    try:
        main(args.stop)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error))
        sys.exit(1)
