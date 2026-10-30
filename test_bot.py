import base64, copy, unittest
from bot import candidate, secure, market_cap, PROGRAM
class Filters(unittest.TestCase):
    def setUp(self):
        self.p={'pairCreatedAt':940000,'chainId':'solana','baseToken':{'address':'mint','symbol':'TEST'},'pairAddress':'pair','liquidity':{'usd':20000},'volume':{'m5':2500},'txns':{'m5':{'buys':25,'sells':10}}}
    def test_age(self):
        self.assertIsNotNone(candidate(self.p,1000))
        self.assertIsNotNone(candidate(self.p,4540))
        self.assertIsNone(candidate(self.p,4540.01))
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
    def test_security(self):
        b=bytearray(82);b[45]=1
        a={'owner':PROGRAM,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertTrue(secure(a))
        b[46]=1;a['data'][0]=base64.b64encode(b).decode();self.assertFalse(secure(a))
        a['owner']='Token2022';self.assertFalse(secure(a));self.assertFalse(secure(None))
if __name__=='__main__':unittest.main()
