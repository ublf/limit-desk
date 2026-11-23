"""Official Claude / Antigravity statusLine receiver. No credentials or transcripts saved."""
import datetime as dt
import json
from pathlib import Path
import sys
import uuid
import sqlite3
from quota_history import record_payload


def sanitize(data, provider):
    if provider == 'claude':
        raw = data.get('rate_limits') or {}
        if not isinstance(raw, dict):
            return None
        rates = {key: {field: item[field] for field in ('used_percentage', 'resets_at') if field in item}
                 for key, item in raw.items() if isinstance(item, dict)}
        return {'rate_limits': rates} if rates else None
    raw = data.get('quota') or {}
    if not isinstance(raw, dict):
        return None
    quota = {key: {field: item[field] for field in ('remaining_fraction', 'remaining_amount', 'reset_time', 'reset_in_seconds', 'disabled') if field in item}
             for key, item in raw.items() if isinstance(item, dict)}
    return {'quota': quota, 'plan_tier': data.get('plan_tier')} if quota else None


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else 'claude'
    if provider not in ('claude', 'gemini'):
        return
    temporary = None
    try:
        data = json.load(sys.stdin)
        payload = sanitize(data, provider)
        path = Path(__file__).resolve().parent / '.local'
        path.mkdir(exist_ok=True)
        # Only execution health, no identity, tokens, or original input.
        health = {'receivedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'hasQuota': bool(payload)}
        health_tmp = path / (provider + '-health-' + uuid.uuid4().hex + '.tmp')
        health_tmp.write_text(json.dumps(health), encoding='utf-8')
        health_tmp.replace(path / (provider + '-health.json'))
        if payload:
            payload['snapshotAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
            path = Path(__file__).resolve().parent / '.local'
            path.mkdir(exist_ok=True)
            temporary = path / (provider + '-' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(payload), encoding='utf-8')
            temporary.replace(path / (provider + '.json'))
            if provider == 'claude':
                try:
                    record_payload(Path(__file__).resolve().parent, payload)
                except (OSError, sqlite3.Error):
                    pass
            print('Limit Desk: quota synced')
        else:
            print('Limit Desk: waiting for quota')
    except (ValueError, OSError, AttributeError, TypeError):
        print('Limit Desk: quota unavailable')
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
