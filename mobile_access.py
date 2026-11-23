"""Allow a configured Tailscale login through a loopback-only Serve proxy."""
import json
from pathlib import Path


def allowed(root, host, headers):
    host = (host or '').lower()
    local = host in ('127.0.0.1:8765', 'localhost:8765')
    login = headers.get('Tailscale-User-Login')
    forwarded = headers.get('X-Forwarded-For') or headers.get('X-Forwarded-Host') or headers.get('X-Forwarded-Proto')
    if local and not login and not forwarded:
        return True
    try:
        config = json.loads((Path(root) / '.local/mobile.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return False
    expected_host = config.get('host', '').lower()
    expected_login = config.get('login')
    return bool(expected_host and expected_login and login == expected_login and (local or host == expected_host))
