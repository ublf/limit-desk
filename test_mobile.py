import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import mobile_access
import setup_mobile

class MobileAccessTests(unittest.TestCase):
    def test_local_access_remains_available(self):
        self.assertTrue(mobile_access.allowed('.', '127.0.0.1:8765', {}))
        self.assertFalse(mobile_access.allowed('.', 'example.com', {}))
    def test_only_configured_tailnet_identity_can_use_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.local').mkdir()
            (root/'.local/mobile.json').write_text(json.dumps({'host':'pc.test.ts.net:8443','login':'owner@example.com'}))
            self.assertTrue(mobile_access.allowed(root,'pc.test.ts.net:8443',{'Tailscale-User-Login':'owner@example.com'}))
            self.assertTrue(mobile_access.allowed(root,'127.0.0.1:8765',{'Tailscale-User-Login':'owner@example.com'}))
            self.assertFalse(mobile_access.allowed(root,'pc.test.ts.net:8443',{}))
            self.assertFalse(mobile_access.allowed(root,'pc.test.ts.net:8443',{'Tailscale-User-Login':'other@example.com'}))
            self.assertFalse(mobile_access.allowed(root,'127.0.0.1:8765',{'X-Forwarded-For':'external'}))
            self.assertFalse(mobile_access.allowed(root,'wrong.ts.net:8443',{'Tailscale-User-Login':'owner@example.com'}))
    def test_setup_uses_private_serve_and_keeps_loopback_target(self):
        status={'BackendState':'Running','Self':{'DNSName':'pc.test.ts.net.','UserID':1},'User':{'1':{'LoginName':'owner@example.com'}}}
        with tempfile.TemporaryDirectory() as tmp, patch('setup_mobile.ROOT',Path(tmp)), patch('setup_mobile.executable',return_value='tailscale'), patch('setup_mobile.ready',return_value=True), patch('setup_mobile.command',side_effect=[json.dumps(status),'{}','private URL']) as command:
            setup_mobile.main()
            self.assertEqual(command.call_args.args,('tailscale','serve','--bg','--https=8443','http://127.0.0.1:8765'))
            config=json.loads((Path(tmp)/'.local/mobile.json').read_text())
            self.assertEqual(config['host'],'pc.test.ts.net:8443')
    def test_existing_different_service_is_preserved(self):
        status={'BackendState':'Running','Self':{'DNSName':'pc.test.ts.net.','UserID':1},'User':{'1':{'LoginName':'owner@example.com'}}}
        settings={'Web':{'pc.test.ts.net:8443':{'Handlers':{'/':{'Proxy':'http://localhost:9999'}}}}}
        with patch('setup_mobile.executable',return_value='tailscale'),patch('setup_mobile.command',side_effect=[json.dumps(status),json.dumps(settings)]) as command:
            with self.assertRaises(ValueError):setup_mobile.main()
            self.assertEqual(command.call_count,2)

if __name__=='__main__':unittest.main()
