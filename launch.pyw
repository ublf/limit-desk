"""Open Limit Desk, starting the local server only when necessary."""
from pathlib import Path
import ctypes
import subprocess
import sys
import time
import urllib.request
import os

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'


def ready():
    try:
        with urllib.request.urlopen(URL, timeout=1) as response:
            return b'Limit Desk' in response.read(4096)
    except Exception:
        return False


def app_command():
    candidates = [
        Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Edge/Application/msedge.exe',
    ]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise FileNotFoundError('Microsoft Edge is required to open the app window.')
    return [str(executable), '--app=' + URL,
            '--user-data-dir=' + str(ROOT / '.local' / 'app-profile'),
            '--no-first-run', '--no-default-browser-check',
            '--window-size=1280,860', '--force-dark-mode']


def main():
    if not ready():
        folder = ROOT / '.local'
        folder.mkdir(exist_ok=True)
        with (folder / 'launcher.log').open('ab') as output:
            subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT),
                stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            if ready():
                break
            time.sleep(.25)
        else:
            ctypes.windll.user32.MessageBoxW(None, 'Limit Desk could not start. Check .local/launcher.log.', 'Limit Desk', 16)
            return
    try:
        subprocess.Popen(app_command(), cwd=str(ROOT),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        ctypes.windll.user32.MessageBoxW(None, 'Could not open Limit Desk. Microsoft Edge is required.', 'Limit Desk', 16)


if __name__ == '__main__':
    main()
