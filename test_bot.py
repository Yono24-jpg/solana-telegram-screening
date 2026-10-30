import base64, copy, unittest
from bot import candidate, secure, market_cap, market_rejection, security_reason, PROGRAM, TOKEN_2022
class Filters(unittest.TestCase):
    def setUp(self):
        self.p={'pairCreatedAt':940000,'chainId':'solana','baseToken':{'address':'mint','symbol':'TEST'},'pairAddress':'pair','liquidity':{'usd':20000},'volume':{'m5':2500},'txns':{'m5':{'buys':25,'sells':10}}}
    def test_age(self):
        self.assertIsNotNone(candidate(self.p,1000))
        self.assertIsNotNone(candidate(self.p,11740))
        self.assertIsNone(candidate(self.p,11740.01))
        self.assertIsNone(candidate(self.p,939))
    def test_missing_or_invalid(self):
        for field in ('liquidity','volume','txns','pairCreatedAt'):
            p=copy.deepcopy(self.p);del p[field];self.assertIsNone(candidate(p,1000))
        for val in (None,float('nan'),float('inf'),True,-1):
            p=copy.deepcopy(self.p);p['liquidity']['usd']=val;self.assertIsNone(candidate(p,1000))
    def test_looser_market_thresholds(self):
        p=copy.deepcopy(self.p)
        p['liquidity']['usd']=5000
        p['volume']['m5']=500
        p['txns']['m5']={'buys':5,'sells':5}
        self.assertIsNotNone(candidate(p,1000))
        p['liquidity']['usd']=4999
        self.assertIsNone(candidate(p,1000))
        p['liquidity']['usd']=5000
        p['volume']['m5']=499
        self.assertIsNone(candidate(p,1000))
        p['volume']['m5']=500
        p['txns']['m5']['buys']=4
        self.assertIsNone(candidate(p,1000))
    def test_pressure(self):
        self.p['txns']['m5']['sells']=40;self.assertIsNone(candidate(self.p,1000))
    def test_market_cap(self):
        self.p['marketCap']=125000
        self.assertEqual(market_cap(self.p),125000)
        for value in (None,0,-1,True,float('nan'),float('inf'),'125000'):
            self.p['marketCap']=value
            self.assertIsNone(market_cap(self.p))
        del self.p['marketCap']
        self.assertIsNone(market_cap(self.p))
    def test_market_rejection_reasons(self):
        self.assertIsNone(market_rejection(self.p,1000))
        cases=[('liquidity',lambda p:p['liquidity'].update(usd=4999)),('volume_5m',lambda p:p['volume'].update(m5=499)),('transactions_5m',lambda p:p['txns']['m5'].update(buys=4)),('buy_sell_ratio',lambda p:p['txns']['m5'].update(sells=30)),('age',lambda p:p.update(pairCreatedAt=-4000000))]
        for expected,modify in cases:
            p=copy.deepcopy(self.p);modify(p)
            self.assertEqual(market_rejection(p,1000),expected)
    def test_security_diagnostics(self):
        self.assertEqual(security_reason(None),'account_missing')
        b=bytearray(82);b[45]=1
        a={'owner':PROGRAM,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertIsNone(security_reason(a))
        b[0]=1;a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'mint_authority_active')
        b[0]=0;b[46]=1;a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'freeze_authority_active')
        a['owner']='Token2022'
        self.assertEqual(security_reason(a),'unsupported_token_program')
    def test_token2022_extension_free_only(self):
        b=bytearray(82);b[45]=1
        a={'owner':TOKEN_2022,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertIsNone(security_reason(a))
        self.assertTrue(secure(a))
        b.extend(bytes(83)+bytes([1])+bytes([10,0,1,0,0]))
        a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'token2022_extensions_unverified')
        self.assertFalse(secure(a))
        b[165]=2
        a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'token2022_invalid_extension_layout')
        b=bytearray(82);b[45]=1;b[0]=1
        a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'mint_authority_active')
        a['owner']='unknown_program'
        self.assertEqual(security_reason(a),'unsupported_token_program')
    def test_token2022_metadata_only(self):
        b=bytearray(166);b[45]=1;b[165]=1
        b.extend(bytes([18,0,64,0])+bytes(64))
        a={'owner':TOKEN_2022,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertIsNone(security_reason(a))
        b.extend(bytes([19,0,64,0])+bytes(64))
        a['data'][0]=base64.b64encode(b).decode()
        self.assertIsNone(security_reason(a))
        b.extend(bytes([14,0,1,0,1]))
        a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'token2022_extensions_unverified')
        b=bytearray(166);b[45]=1;b[165]=1
        b.extend(bytes([18,0,1,0,0]))
        a['data'][0]=base64.b64encode(b).decode()
        self.assertEqual(security_reason(a),'token2022_invalid_extension_layout')
    def test_security(self):
        b=bytearray(82);b[45]=1
        a={'owner':PROGRAM,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertTrue(secure(a))
        b[46]=1;a['data'][0]=base64.b64encode(b).decode();self.assertFalse(secure(a))
        a['owner']='Token2022';self.assertFalse(secure(a));self.assertFalse(secure(None))
if __name__=='__main__':unittest.main()
