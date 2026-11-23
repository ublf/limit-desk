"""Optional Claude Code statusLine collector. Stores only quota fields."""
import datetime as dt
import json
from pathlib import Path
import sys

try:
    data = json.load(sys.stdin)
    raw = data.get('rate_limits') or {}
    rates = {key: {field: item[field] for field in ('used_percentage', 'resets_at') if field in item}
             for key, item in raw.items() if isinstance(item, dict)}
    if rates:
        path = Path(__file__).resolve().parent / '.local'
        path.mkdir(exist_ok=True)
        temporary = path / 'claude.tmp'
        temporary.write_text(json.dumps({'rate_limits': rates}), encoding='utf-8')
        temporary.replace(path / 'claude.json')
    parts = ['%s: %s%%' % (key, value['used_percentage']) for key, value in rates.items() if 'used_percentage' in value]
    print(' | '.join(parts) or 'Limit Desk: waiting for quota')
except (ValueError, OSError):
    print('Limit Desk: quota unavailable')
