import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'cloud'))
from auth_rate_limit import FailedAuthLimiter, client_ip
from test_interactions import HttpTests as Base


class LimiterTests(unittest.TestCase):
    def test_threshold_expiry_and_no_sliding_lockout(self):
        now=[0]
        limit=FailedAuthLimiter(clock=lambda:now[0])
        for _ in range(7):self.assertEqual(limit.failure('a'),0)
        self.assertEqual(limit.failure('a'),600)
        now[0]=100
        self.assertEqual(limit.failure('a'),500)
        now[0]=601
        self.assertEqual(limit.remaining('a'),0)
        self.assertEqual(limit.failure('a'),0)

    def test_success_window_other_ips_and_capacity(self):
        now=[0];limit=FailedAuthLimiter(capacity=3,clock=lambda:now[0])
        for _ in range(7):limit.failure('a')
        limit.success('a');self.assertEqual(limit.failure('a'),0)
        now[0]=301;self.assertEqual(limit.failure('a'),0)
        self.assertEqual(limit.remaining('b'),0)
        for key in ['b','c','d']:limit.failure(key)
        self.assertEqual(len(limit.entries),3)

    def test_concurrent_failures(self):
        limit=FailedAuthLimiter()
        workers=[threading.Thread(target=lambda:limit.failure('a')) for _ in range(8)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertGreater(limit.remaining('a'),0)

    def test_only_loopback_proxy_can_supply_rightmost_hop(self):
        self.assertEqual(client_ip('203.0.113.1','198.51.100.9'),'203.0.113.1')
        self.assertEqual(client_ip('127.0.0.1','198.51.100.9, 203.0.113.1'),'203.0.113.1')
        self.assertEqual(client_ip('::ffff:127.0.0.1','::ffff:203.0.113.1'),'203.0.113.1')
        self.assertEqual(client_ip('127.0.0.1','bad-header'),'127.0.0.1')


class AuthRateHttpTests(Base):
    def test_blocked_source_does_not_block_valid_owner_or_device(self):
        for _ in range(7):self.assertEqual(self.request('/api/interactions')[0],401)
        code,data=self.request('/api/interactions')
        self.assertEqual(code,429);self.assertGreater(data['retryAfter'],0)
        self.assertEqual(self.request('/api/interactions',{})[0],429)
        code,_=self.request('/api/interactions',headers={'Cookie':'codex_history=test-session'})
        self.assertEqual(code,200)
        self.assertEqual(self.request('/api/interactions')[0],401)  # Successful owner request reset the streak.
        for _ in range(8):self.request('/api/device/interactions',{})
        self.assertEqual(self.request('/api/device/interactions',{})[0],429)
        from rpc_interactions import Interactions
        code,_=self.request('/api/device/interactions',{'snapshot':Interactions(lambda _:None).snapshot()},
                             {'Authorization':'Bearer test-only-token'})
        self.assertEqual(code,200)

    def test_invalid_oauth_state_and_pending_owner_recovery(self):
        self.ns['OWNER']='owner';self.ns['OAUTH_STATES']={}
        H=self.ns['H'];H.exchange_feishu_code=lambda *_:{'open_id':'owner'}
        for _ in range(8):self.request('/api/auth/oauth/callback?state=bad&code=bad')
        self.assertEqual(self.request('/api/interactions')[0],429)
        self.ns['OAUTH_STATES']['pending']=(self.ns['time'].time()+60,'/api/auth/config')
        # A valid pre-existing OAuth flow can still finish without waiting out the ban.
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('GET','/api/auth/oauth/callback?state=pending&code=synthetic')
        response=conn.getresponse();response.read()
        self.assertEqual(response.status,302)
        self.assertIn('HttpOnly',response.getheader('Set-Cookie'))
        conn.close()
        self.assertEqual(self.request('/api/interactions')[0],401)


del Base
