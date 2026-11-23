"""Local CLI quota dashboard. Python 3.10+, no dependencies."""
import concurrent.futures
from mobile_access import allowed as mobile_request_allowed
import datetime as dt
import json
import math
import os
from pathlib import Path
import queue
import ssl
import sqlite3
from quota_history import record_payload, read_history
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlsplit
from claude_usage import analyze as analyze_claude_usage
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get('USERPROFILE') or Path.home())
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=3)

class ProviderError(ValueError):
    def __init__(self, code, message, action=None):
        super().__init__(message)
        self.code = code
        self.action = action


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise ValueError('認証ファイルがありません。CLIでログインしてください。')

def request_json(url, token, body=None, headers=None):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(headers or {})})
    try:
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        messages = {401: '認証期限切れです。CLIで再ログインしてください。', 403: 'この認証では利用枠へのアクセスが許可されていません。', 429: '取得回数の制限中です。しばらく待ってください。'}
        raise ValueError(messages.get(error.code, 'サービス応答エラー (HTTP %s)' % error.code)) from None
    except (URLError, TimeoutError, PermissionError) as error:
        reason = error.reason if isinstance(error, URLError) else error
        if isinstance(reason, PermissionError) or getattr(reason, 'winerror', None) == 10013:
            raise ProviderError('network_blocked', 'OSまたは実行環境が外部通信を拒否しました（WinError 10013）。', '通常のPowerShellから start.ps1 を起動してください。公式statusLine連携でも取得できます。') from None
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ProviderError('tls_certificate', 'サービスのTLS証明書を検証できませんでした。', 'PCの証明書・プロキシ設定を確認してください。') from None
        if isinstance(reason, TimeoutError):
            raise ProviderError('network_timeout', 'サービスへの接続がタイムアウトしました。', '通信状態を確認して再取得してください。') from None
        raise ProviderError('network_unreachable', 'サービスに接続できませんでした。', 'ネットワーク・プロキシ設定を確認してください。') from None

def window(label, used, reset=None, **extra):
    if isinstance(used, bool) or not isinstance(used, (float, int)) or not 0 <= used <= 100:
        return None
    if isinstance(reset, (int, float)):
        reset = dt.datetime.fromtimestamp(reset, dt.timezone.utc).isoformat()
    return {'label': label, 'used': round(used, 1), 'reset': reset, **extra}

def codex_live():
    executable = os.environ.get('LIMIT_DESK_CODEX', 'codex')
    try:
        proc = subprocess.Popen([executable, 'app-server', '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), env={**os.environ, 'HOME': str(HOME)})
    except OSError:
        raise ValueError('Codex CLIが見つかりません。PATHまたは LIMIT_DESK_CODEX を確認してください。')
    messages = queue.Queue()
    def reader():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        messages.put(None)
    threading.Thread(target=reader, daemon=True).start()
    def send(message):
        proc.stdin.write(json.dumps(message) + '\n')
        proc.stdin.flush()
    def receive(id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                msg = messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if msg is None:
                raise ValueError('Codex App Serverが終了しました。CLIのログイン状態を確認してください。')
            if msg.get('id') == id:
                if 'error' in msg:
                    raise ValueError('Codexから利用枠を取得できません。CLIで /status を確認してください。')
                return msg.get('result', {})
        raise ValueError('Codexの取得がタイムアウトしました。')
    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'limit_desk', 'version': '1.0.0'}}})
        receive(1)
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'account/rateLimits/read', 'params': {}})
        data = receive(2)
        groups = data.get('rateLimitsByLimitId') or {'codex': data.get('rateLimits', {})}
        windows = []
        plan = None
        for key, group in groups.items():
            plan = plan or group.get('planType')
            for slot in ('primary', 'secondary'):
                item = group.get(slot)
                if not item:
                    continue
                minutes = item.get('windowDurationMins')
                label = {300: '5時間', 10080: '週間', 1440: '日次'}.get(minutes, str(minutes) + '分' if minutes else slot)
                windows.append(window(label if key == 'codex' else key + ' / ' + label, item.get('usedPercent'), item.get('resetsAt'), durationMinutes=minutes))
        return {'plan': plan, 'windows': [w for w in windows if w], 'source': 'Codex App Server'}
    finally:
        proc.kill()
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()

def codex():
    try:
        return codex_live()
    except ValueError as error:
        live_error = str(error)
    # CLI session events contain quota snapshots, never infer quotas from tokens.
    base = Path(os.environ.get('CODEX_HOME', str(HOME / '.codex'))) / 'sessions'
    files = sorted(base.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:20] if base.exists() else []
    newest = None
    for file in files:
        try:
            with file.open('rb') as stream:
                stream.seek(max(0, file.stat().st_size - 2_000_000))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()
            for line in reversed(lines):
                if '"rate_limits"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                payload = event.get('payload') or {}
                rates = payload.get('rate_limits')
                if not isinstance(rates, dict):
                    continue
                stamp = event.get('timestamp')
                if not stamp or (newest and stamp <= newest[0]):
                    continue
                windows = []
                for slot in ('primary', 'secondary'):
                    item = rates.get(slot)
                    if isinstance(item, dict):
                        minutes = item.get('window_minutes')
                        label = {300: '5時間', 10080: '週間', 1440: '日次'}.get(minutes, str(minutes) + '分' if minutes else slot)
                        w = window(label, item.get('used_percent'), item.get('resets_at'), durationMinutes=minutes)
                        if w:
                            windows.append(w)
                if windows:
                    newest = (stamp, windows, rates.get('plan_type'))
        except OSError:
            continue
    if newest:
        return {'plan': newest[2], 'windows': newest[1], 'source': 'Codex CLI 記録値', 'snapshotAt': newest[0], 'message': 'ライブ取得不可。CLIに記録された時点の値です。' }
    raise ValueError(live_error)

def captured_quota(name):
    path = ROOT / '.local' / (name + '.json')
    if not path.exists():
        return None
    try:
        data = read_json(path)
        if not isinstance(data, dict):
            return None
        # Use the actual snapshot time, including old records. Never present as live.
        data['snapshotAt'] = data.get('snapshotAt') or dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat()
        return data
    except (ValueError, OSError):
        return None


def claude_windows(rates, field):
    labels = {'five_hour': '5時間', 'seven_day': '週間', 'seven_day_sonnet': '週間 · Sonnet', 'seven_day_opus': '週間 · Opus', 'spend_limit': '支出上限'}
    return [w for key, label in labels.items() if isinstance(rates.get(key), dict)
            for w in [window(label, rates[key].get(field), rates[key].get('resets_at'), durationMinutes=300 if key == 'five_hour' else 10080 if key.startswith('seven_day') else None)] if w]


def claude():
    capture = captured_quota('claude')
    if capture:
        windows = claude_windows(capture.get('rate_limits') or {}, 'used_percentage')
        if windows:
            return {'plan': capture.get('plan'), 'source': 'Claude Code statusLine',
                    'windows': windows, 'snapshotAt': capture['snapshotAt'],
                    'message': 'CLIが通知した記録値。CLIの状態更新時に反映されます。'}
    base = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude')))
    auth = read_json(base / '.credentials.json').get('claudeAiOauth') or {}
    token = auth.get('accessToken')
    if not token:
        raise ProviderError('claude_auth_missing', 'ClaudeのOAuth認証がありません。', 'claudeでログイン、または公式statusLine連携を設定してください。')
    rates = request_json('https://api.anthropic.com/api/oauth/usage', token, headers={'anthropic-beta': 'oauth-2025-04-20'})
    return {'plan': auth.get('subscriptionType'), 'source': 'Claude OAuth usage（非公開API）',
            'windows': claude_windows(rates, 'utilization')}


def antigravity_bucket_meta(key):
    lower = key.lower()
    if lower in ('gemini-5h', 'gemini-five-hour'):
        return (0, '5時間', 300)
    if lower == 'gemini-weekly':
        return (1, '週間', 10080)
    duration = (10080 if 'weekly' in lower else
                300 if '5h' in lower or 'five-hour' in lower else
                1440 if 'daily' in lower or '24h' in lower else None)
    if 'neon' in lower:
        period = {300: '5時間', 10080: '週間', 1440: '日次'}.get(duration)
        order = 2 if duration == 300 else 3 if duration == 10080 else 4
        return (order, period + ' · Neon' if period else key, duration)
    return (10, key, duration)


def antigravity_reset_time(item, snapshot_at):
    reset = item.get('reset_time')
    if reset:
        return reset
    seconds = item.get('reset_in_seconds')
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds >= 0 and isinstance(snapshot_at, str):
        try:
            base_time = dt.datetime.fromisoformat(snapshot_at.replace('Z', '+00:00'))
            if base_time.tzinfo is None:
                base_time = base_time.replace(tzinfo=dt.timezone.utc)
            return (base_time + dt.timedelta(seconds=seconds)).astimezone(dt.timezone.utc).isoformat()
        except ValueError:
            return None
    return None


def antigravity_windows(quota, snapshot_at=None):
    ranked = []
    for key, item in quota.items():
        if not isinstance(item, dict) or item.get('disabled'):
            continue
        lower = key.lower()
        if lower == '3p' or lower.startswith('3p-') or 'argon' in lower:
            continue
        fraction = item.get('remaining_fraction')
        if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
            order, label, duration = antigravity_bucket_meta(key)
            extra = {'durationMinutes': duration}
            if item.get('remaining_amount') is not None:
                extra['remaining'] = item.get('remaining_amount')
            w = window(label, (1 - fraction) * 100, antigravity_reset_time(item, snapshot_at), **extra)
            if w:
                ranked.append((order, key, w))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in ranked]

def gemini():
    base = Path(os.environ.get('LIMIT_DESK_GEMINI_HOME', str(HOME / '.gemini')))
    capture = captured_quota('gemini')
    if capture:
        windows = antigravity_windows(capture.get('quota') or {}, capture.get('snapshotAt'))
        if windows:
            return {'plan': capture.get('plan_tier'), 'source': 'Antigravity CLI statusLine',
                    'displayName': 'Gemini / Antigravity', 'windows': windows,
                    'snapshotAt': capture['snapshotAt'], 'message': 'CLIが通知した記録値。CLIの状態更新時に反映されます。'}
    if not (base / 'oauth_creds.json').exists():
        if (base / 'antigravity-cli').exists() or (HOME / 'AppData/Local/agy/bin/agy.exe').exists():
            raise ProviderError('antigravity_detected', 'Antigravity CLI（agy）を検出しました。従来のGemini CLI認証では取得できません。', 'start.ps1 -ConnectCli で公式statusLine連携を設定し、agyを再起動してください。')
        raise ProviderError('gemini_auth_missing', 'Gemini CLIのGoogle認証ファイルがありません。', '別の環境で使っている場合は LIMIT_DESK_GEMINI_HOME を指定してください。')
    creds = read_json(base / 'oauth_creds.json')
    token = creds.get('access_token')
    if not token:
        raise ValueError('Googleログインの認証がありません。Gemini CLIでログインしてください。')
    if creds.get('expiry_date', float('inf')) < time.time() * 1000:
        raise ValueError('Google認証期限切れです。Gemini CLIを起動して更新してください。')
    endpoint = 'https://cloudcode-pa.googleapis.com/v1internal:'
    project = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GOOGLE_CLOUD_PROJECT_ID')
    info = request_json(endpoint + 'loadCodeAssist', token, {'metadata': {'ideType': 'IDE_UNSPECIFIED'}, **({'cloudaicompanionProject': project} if project else {})})
    project = project or info.get('cloudaicompanionProject')
    if not isinstance(project, str) or not project:
        raise ValueError('Google Cloudプロジェクトが取得できません。GOOGLE_CLOUD_PROJECT を設定してください。')
    data = request_json(endpoint + 'retrieveUserQuota', token, {'project': project})
    windows = []
    for bucket in data.get('buckets', []):
        fraction = bucket.get('remainingFraction')
        if isinstance(fraction, (float, int)) and not isinstance(fraction, bool):
            w = window(bucket.get('modelId') or bucket.get('tokenType') or '利用枠', (1 - fraction) * 100, bucket.get('resetTime'), remaining=bucket.get('remainingAmount'))
            if w:
                windows.append(w)
    tier = info.get('currentTier') or info.get('paidTier') or {}
    return {'plan': tier.get('name') or tier.get('id'), 'source': 'Gemini CLI Code Assist（非公開API）', 'windows': windows}

def collect(id, fn):
    result = {'id': id, 'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        result.update(fn())
        result['status'] = 'ok' if result['windows'] else 'unavailable'
        if not result['windows']:
            result['message'] = 'このアカウントから利用枠が返されませんでした。CLIで確認してください。'
    except ProviderError as error:
        result.update(status='unavailable', code=error.code, message=str(error), action=error.action, windows=[])
    except ValueError as error:
        result.update(status='unavailable', message=str(error), windows=[])
    except Exception:
        result.update(status='error', message='取得できませんでした。CLIの設定・認証状態を確認してください。', windows=[])
    return result

class Dashboard(BaseHTTPRequestHandler):
    cache = None
    cached_at = 0
    lock = threading.Lock()
    analytics_cache = {}
    def do_GET(self):
        if not mobile_request_allowed(ROOT, self.headers.get('Host'), self.headers):
            self.send_error(403)
            return
        path = self.path.split('?')[0]
        if path == '/api/claude/usage-details':
            scope = parse_qs(urlsplit(self.path).query).get('scope', ['30m'])[0]
            seconds = 18000 if scope == '5h' else 1800
            now = time.time()
            with self.lock:
                cached = type(self).analytics_cache.get(seconds)
                if cached is None or now - cached[0] > 60:
                    base = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude'))) / 'projects'
                    report = analyze_claude_usage(base, now-seconds, now)
                    type(self).analytics_cache[seconds] = (now, report)
                else:
                    report = cached[1]
                try:
                    capture = captured_quota('claude')
                    if capture:
                        record_payload(ROOT, capture)
                    report = {**report, 'quotaHistory': read_history(ROOT, now-seconds, now)}
                except (OSError, sqlite3.Error):
                    report = {**report, 'quotaHistory': {}, 'historyUnavailable': True}
                content = json.dumps(report, ensure_ascii=False).encode()
            mime = 'application/json; charset=utf-8'
        elif path == '/api/usage':
            with self.lock:
                if self.cache is None or time.monotonic() - type(self).cached_at > 60:
                    tasks = [POOL.submit(collect, id, fn) for id, fn in [('claude', claude), ('codex', codex), ('gemini', gemini)]]
                    type(self).cache = {'providers': [t.result() for t in tasks], 'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat()}
                    type(self).cached_at = time.monotonic()
                content = json.dumps(self.cache, ensure_ascii=False).encode()
            mime = 'application/json; charset=utf-8'
        elif path in ('/', '/index.html', '/app.js', '/style.css', '/favicon.ico', '/icon-192.png', '/icon-512.png', '/manifest.json'):
            file = ROOT / 'dist' / ('index.html' if path == '/' else path[1:])
            if not file.is_file():
                self.send_error(404)
                return
            content = file.read_bytes()
            mime = {
                '.html': 'text/html; charset=utf-8',
                '.css': 'text/css; charset=utf-8',
                '.js': 'text/javascript; charset=utf-8',
                '.ico': 'image/x-icon',
                '.png': 'image/png',
                '.json': 'application/manifest+json; charset=utf-8',
            }[file.suffix]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)
    def log_message(self, *_):
        pass

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Dashboard)
    print('Limit Desk: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()



