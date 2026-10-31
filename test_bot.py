import base64, copy, unittest
from bot import candidate, secure, market_cap, market_rejection, security_reason, crash_risk_reason, liquidity_risk_reason, rugcheck_risk_reason, PROGRAM, TOKEN_2022
class Filters(unittest.TestCase):
    def setUp(self):
        self.p={'pairCreatedAt':940000,'chainId':'solana','baseToken':{'address':'mint','symbol':'TEST'},'pairAddress':'pair','liquidity':{'usd':20000},'volume':{'m5':2500},'txns':{'m5':{'buys':25,'sells':10}}}
    def test_crash_risk_gate(self):
        p={'priceChange':{'m5':3,'h1':12}}
        self.assertIsNone(crash_risk_reason(p))
        p['priceChange']['m5']=-16
        self.assertEqual(crash_risk_reason(p),'rapid_price_drop')
        p['priceChange']['m5']=0
        p['priceChange']['h1']=-31
        self.assertEqual(crash_risk_reason(p),'rapid_price_drop')
        del p['priceChange']['h1']
        self.assertEqual(crash_risk_reason(p),'unverified_price_change')
        p['priceChange']['h1']=float('nan')
        self.assertEqual(crash_risk_reason(p),'unverified_price_change')
        p['priceChange']={'m5':26,'h1':10}
        self.assertEqual(crash_risk_reason(p),'already_pumped')
        p['priceChange']={'m5':10,'h1':81}
        self.assertEqual(crash_risk_reason(p),'already_pumped')
        p['priceChange']={'m5':25,'h1':80}
        self.assertIsNone(crash_risk_reason(p))
    def test_rugcheck_risk_gate(self):
        self.assertIsNone(rugcheck_risk_reason({'risks':[], 'score_normalised':20}))
        self.assertEqual(rugcheck_risk_reason({'risks':[{'level':'danger'}], 'score_normalised':20}),'danger_risk_flag')
        self.assertEqual(rugcheck_risk_reason({'risks':[], 'score_normalised':60}),'high_risk_score')
        self.assertEqual(rugcheck_risk_reason({'risks':[], 'score_normalised':None}),'unverified_risk_score')
        self.assertEqual(rugcheck_risk_reason({'score_normalised':10}),'unverified_risk_report')
    def test_liquidity_risk_gate(self):
        p=copy.deepcopy(self.p)
        p['marketCap']=100000
        self.assertIsNone(liquidity_risk_reason(p))
        p['liquidity']['usd']=9999
        self.assertEqual(liquidity_risk_reason(p),'low_liquidity')
        p['liquidity']['usd']=10000
        p['marketCap']=200000
        self.assertEqual(liquidity_risk_reason(p),'thin_liquidity_relative_to_cap')
        p['marketCap']=125000
        self.assertIsNone(liquidity_risk_reason(p))
        del p['marketCap']
        self.assertEqual(liquidity_risk_reason(p),'unverified_liquidity_or_cap')
    def test_age(self):
        self.assertIsNone(candidate(self.p,1000))
        self.assertIsNone(candidate(self.p,1239.99))
        self.assertIsNotNone(candidate(self.p,1240))
        self.assertIsNotNone(candidate(self.p,11740))
        self.assertIsNone(candidate(self.p,11740.01))
        self.assertIsNone(candidate(self.p,939))
    def test_missing_or_invalid(self):
        for field in ('liquidity','volume','txns','pairCreatedAt'):
            p=copy.deepcopy(self.p);del p[field];self.assertIsNone(candidate(p,1240))
        for val in (None,float('nan'),float('inf'),True,-1):
            p=copy.deepcopy(self.p);p['liquidity']['usd']=val;self.assertIsNone(candidate(p,1240))
    def test_looser_market_thresholds(self):
        p=copy.deepcopy(self.p)
        p['liquidity']['usd']=5000
        p['volume']['m5']=500
        p['txns']['m5']={'buys':5,'sells':5}
        self.assertIsNotNone(candidate(p,1240))
        p['liquidity']['usd']=4999
        self.assertIsNone(candidate(p,1240))
        p['liquidity']['usd']=5000
        p['volume']['m5']=499
        self.assertIsNone(candidate(p,1240))
        p['volume']['m5']=500
        p['txns']['m5']['buys']=4
        self.assertIsNone(candidate(p,1240))
    def test_pressure(self):
        self.p['txns']['m5']['sells']=40;self.assertIsNone(candidate(self.p,1240))
    def test_market_cap(self):
        self.p['marketCap']=125000
        self.assertEqual(market_cap(self.p),125000)
        for value in (None,0,-1,True,float('nan'),float('inf'),'125000'):
            self.p['marketCap']=value
            self.assertIsNone(market_cap(self.p))
        del self.p['marketCap']
        self.assertIsNone(market_cap(self.p))
    def test_market_rejection_reasons(self):
        self.assertIsNone(market_rejection(self.p,1240))
        cases=[('liquidity',lambda p:p['liquidity'].update(usd=4999)),('volume_5m',lambda p:p['volume'].update(m5=499)),('transactions_5m',lambda p:p['txns']['m5'].update(buys=4)),('buy_sell_ratio',lambda p:p['txns']['m5'].update(sells=30)),('age',lambda p:p.update(pairCreatedAt=-11000000))]
        for expected,modify in cases:
            p=copy.deepcopy(self.p);modify(p)
            self.assertEqual(market_rejection(p,1240),expected)
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
