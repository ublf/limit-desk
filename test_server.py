import unittest
import os
import os
from unittest.mock import patch
import tempfile
from pathlib import Path
import server

class QuotaTests(unittest.TestCase):
    def test_invalid_and_zero_percent(self):
        self.assertEqual(server.window('5h', 0)['used'], 0)
        self.assertEqual(server.window('5h', 100)['used'], 100)
        for value in [None, True, -1, 101, float('nan'), '30']:
            self.assertIsNone(server.window('5h', value))

    def test_codex_rpc_and_multiple_windows(self):
        class Pipe:
            def write(self, text): pass
            def flush(self): pass
            def close(self): pass
            def __iter__(self):
                yield '{"id":1,"result":{}}\n'
                yield '{"id":2,"result":{"rateLimitsByLimitId":{"codex":{"planType":"plus","primary":{"usedPercent":0,"windowDurationMins":300,"resetsAt":1900000000},"secondary":{"usedPercent":90,"windowDurationMins":10080}}}}}\n'
        class Process:
            stdin = Pipe()
            stdout = Pipe()
            def kill(self): pass
            def wait(self): pass
        with patch('server.subprocess.Popen', return_value=Process()):
            result = server.codex()
        self.assertEqual(result['plan'], 'plus')
        self.assertEqual([w['used'] for w in result['windows']], [0, 90])
        self.assertEqual(result['windows'][1]['label'], '週間')

    def test_claude_no_fabricated_missing_limits(self):
        with tempfile.TemporaryDirectory() as folder, patch('server.ROOT', Path(folder)), patch('server.read_json', return_value={'claudeAiOauth': {'accessToken': 'test'}}), patch('server.request_json', return_value={'five_hour': {'utilization': 42, 'resets_at': '2030-01-01T00:00:00Z'}, 'seven_day': None}):
            result = server.claude()
        self.assertEqual(len(result['windows']), 1)
        self.assertEqual(result['windows'][0]['used'], 42)

    def test_gemini_fraction_and_unknown_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'oauth_creds.json').write_text('{"access_token":"test"}')
            with patch.dict(os.environ, {'LIMIT_DESK_GEMINI_HOME':tmp}), patch('server.ROOT',root), patch('server.request_json', side_effect=[{'cloudaicompanionProject':'test-project'}, {'buckets':[{'modelId':'gemini-test','remainingFraction':.75},{'modelId':'unknown'}]}]):
                result = server.gemini()
        self.assertEqual(len(result['windows']), 1)
        self.assertEqual(result['windows'][0]['used'], 25)

    def test_failure_does_not_leak_credentials(self):
        def failure(): raise RuntimeError('secret-value')
        result = server.collect('test', failure)
        self.assertNotIn('secret-value', str(result))
        self.assertEqual(result['status'], 'error')

    def test_missing_data_is_not_zero(self):
        result = server.collect('test', lambda: {'windows':[]})
        self.assertEqual(result['status'], 'unavailable')

if __name__ == '__main__':
    unittest.main()
