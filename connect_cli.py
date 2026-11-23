"""Run from your normal terminal to connect official CLI status lines."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get('USERPROFILE') or Path.home())


def install(path, provider):
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    legacy_command = subprocess.list2cmdline([sys.executable, str(ROOT / 'statusline.py'), provider])
    command = subprocess.list2cmdline([Path(sys.executable).as_posix(), (ROOT / 'statusline.py').as_posix(), provider])
    existing = data.get('statusLine')
    expected = {'type': 'command', 'command': command}
    if provider == 'gemini':
        expected['enabled'] = True
        expected['stack_with_default'] = True
    if existing and existing.get('command') == command and all(existing.get(k) == v for k, v in expected.items()):
        print(provider + ': already connected')
        return
    if existing and existing.get('command') not in (command, legacy_command):
        print(provider + ': existing statusLine preserved. See README for manual integration.')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.limitdesk-' + str(time.time_ns()) + '.bak'))
    data['statusLine'] = expected
    temporary = path.with_name(path.name + '.limitdesk.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    print(provider + ': connected. Restart the CLI to activate.')


if __name__ == '__main__':
    try:
        install(Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude'))) / 'settings.json', 'claude')
        if (HOME / '.gemini/antigravity-cli').exists():
            install(HOME / '.gemini/antigravity-cli/settings.json', 'gemini')
    except (OSError, ValueError) as error:
        print('Setup failed (' + type(error).__name__ + '). Run from your normal PowerShell terminal, outside the coding sandbox.')
        sys.exit(1)
