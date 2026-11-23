import json, tempfile, unittest, urllib.error, ssl, os, subprocess, sys
from pathlib import Path
from unittest.mock import patch
import server
import statusline
import connect_cli

class ConnectionTests(unittest.TestCase):
    def test_permission_error_is_actionable(self):
        err = PermissionError('blocked')
        err.winerror = 10013
        with patch('server.urlopen', side_effect=urllib.error.URLError(err)):
            result = server.collect('claude', lambda: server.request_json('https://api.anthropic.com', 'test'))
        self.assertEqual(result['code'], 'network_blocked')
        self.assertIn('10013', result['message'])
        self.assertTrue(result['action'])

    def test_certificate_failure_is_distinct(self):
        with patch('server.urlopen', side_effect=urllib.error.URLError(ssl.SSLCertVerificationError('bad cert'))):
            result = server.collect('claude', lambda: server.request_json('https://api.anthropic.com', 'test'))
        self.assertEqual(result['code'], 'tls_certificate')

    def test_claude_capture_works_without_external_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.local').mkdir()
            (root/'.local/claude.json').write_text(json.dumps({'snapshotAt':'2020-01-01T00:00:00Z','rate_limits':{'five_hour':{'used_percentage':0}}}))
            with patch('server.ROOT', root), patch('server.request_json') as network:
                data = server.claude()
                network.assert_not_called()
        self.assertEqual(data['windows'][0]['used'], 0)
        self.assertEqual(data['snapshotAt'], '2020-01-01T00:00:00Z')

    def test_antigravity_capture_works_without_legacy_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.local').mkdir()
            (root/'.local/gemini.json').write_text(json.dumps({'plan_tier':'Pro','quota':{'gemini-weekly':{'remaining_fraction':.25,'reset_time':'2030-01-01T00:00:00Z'}}}))
            with patch('server.ROOT', root), patch('server.request_json') as network:
                data = server.gemini()
                network.assert_not_called()
        self.assertEqual(data['windows'][0]['used'],75)
        self.assertEqual(data['windows'][0]['label'],'週間')
        self.assertNotIn('remaining', data['windows'][0])
        self.assertEqual(data['displayName'],'Gemini / Antigravity')

    def test_antigravity_filters_3p_and_argon_and_orders_gemini_and_neon(self):
        payload = {
            'plan_tier': 'Google AI Pro',
            'snapshotAt': '2026-11-19T00:00:00Z',
            'quota': {
                '3p-5h': {'remaining_fraction': 0.9, 'reset_time': '2026-11-19T05:00:00Z'},
                '3p-weekly': {'remaining_fraction': 0.8, 'reset_time': '2026-11-26T00:00:00Z'},
                'gemini-argon-wtu-weekly': {'remaining_fraction': 0.5, 'reset_time': '2026-11-26T00:00:00Z'},
                'gemini-weekly': {'remaining_fraction': 0.6, 'reset_time': '2026-11-26T00:00:00Z'},
                'gemini-5h': {'remaining_fraction': 0.75, 'reset_in_seconds': 3600},
                'gemini-neon-weekly': {'remaining_fraction': 0.4, 'reset_time': '2026-11-26T00:00:00Z'},
                'gemini-neon-5h': {'remaining_fraction': 0.7, 'reset_time': '2026-11-19T05:00:00Z', 'remaining_amount': 12},
                'gemini-disabled-5h': {'remaining_fraction': 0.5, 'disabled': True},
                'gemini-daily': {'remaining_fraction': 0.25},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.local').mkdir()
            (root/'.local/gemini.json').write_text(json.dumps(payload))
            with patch('server.ROOT', root):
                data = server.gemini()
        self.assertEqual([w['label'] for w in data['windows']], ['5時間', '週間', '5時間 · Neon', '週間 · Neon', 'gemini-daily'])
        self.assertEqual(data['windows'][0]['used'], 25)
        self.assertEqual(data['windows'][0]['reset'], '2026-11-19T01:00:00+00:00')
        self.assertNotIn('remaining', data['windows'][0])
        self.assertEqual(data['windows'][2]['remaining'], 12)
        self.assertEqual(data['windows'][4]['durationMinutes'], 1440)

    def test_antigravity_sanitize_keeps_reset_in_seconds(self):
        data = {'quota': {'gemini-5h': {'remaining_fraction': 0.8, 'reset_in_seconds': 1800, 'secret': 'hidden'}}, 'plan_tier': 'Google AI Pro'}
        result = statusline.sanitize(data, 'gemini')
        self.assertEqual(result['quota']['gemini-5h']['reset_in_seconds'], 1800)
        self.assertNotIn('secret', json.dumps(result))

    def test_migrated_cli_has_specific_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.gemini/antigravity-cli').mkdir(parents=True)
            with patch.dict(os.environ, {'LIMIT_DESK_GEMINI_HOME':str(root/'.gemini')}), patch('server.HOME',root), patch('server.ROOT',root):
                data=server.collect('gemini',server.gemini)
        self.assertEqual(data['code'],'antigravity_detected')

    def test_capture_strips_identity_and_tokens(self):
        data = {'quota':{'gemini-weekly':{'remaining_fraction':.5,'secret':'hidden'}},'plan_tier':'Pro','email':'private','access_token':'secret','transcript_path':'private'}
        result = statusline.sanitize(data,'gemini')
        for secret in ('private','hidden','secret'):
            self.assertNotIn(secret,json.dumps(result))

    def test_installer_preserves_existing_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            path.write_text('{"theme":"dark"}')
            connect_cli.install(path,'claude')
            data=json.loads(path.read_text())
            self.assertEqual(data['theme'],'dark')
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))),1)
            connect_cli.install(path,'claude')
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))),1)
            path.write_text('{"statusLine":{"command":"custom-script"}}')
            connect_cli.install(path,'claude')
            self.assertEqual(json.loads(path.read_text())['statusLine']['command'],'custom-script')

class WindowsCommandTests(unittest.TestCase):
    def test_legacy_install_is_upgraded_to_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            old=subprocess.list2cmdline([sys.executable,str(connect_cli.ROOT/'statusline.py'),'claude'])
            path.write_text(json.dumps({'theme':'dark','statusLine':{'type':'command','command':old}}))
            connect_cli.install(path,'claude')
            data=json.loads(path.read_text())
            self.assertNotIn(chr(92), data['statusLine']['command'])
            self.assertEqual(data['theme'],'dark')
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))),1)

    def test_gemini_install_enables_and_stacks_statusline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.json'
            path.write_text('{"theme":"dark"}')
            connect_cli.install(path, 'gemini')
            data = json.loads(path.read_text())
            self.assertTrue(data['statusLine']['enabled'])
            self.assertTrue(data['statusLine']['stack_with_default'])
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))), 1)
            connect_cli.install(path, 'gemini')
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))), 1)
            data['statusLine']['enabled'] = False
            path.write_text(json.dumps(data))
            connect_cli.install(path, 'gemini')
            self.assertTrue(json.loads(path.read_text())['statusLine']['enabled'])
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))), 2)

if __name__=='__main__': unittest.main()
