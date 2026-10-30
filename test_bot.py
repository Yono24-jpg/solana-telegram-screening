import base64, copy, unittest
from bot import candidate, secure, PROGRAM
class Filters(unittest.TestCase):
    def setUp(self):
        self.p={'pairCreatedAt':940000,'chainId':'solana','baseToken':{'address':'mint','symbol':'TEST'},'pairAddress':'pair','liquidity':{'usd':20000},'volume':{'m5':2500},'txns':{'m5':{'buys':25,'sells':10}}}
    def test_age(self):
        self.assertIsNotNone(candidate(self.p,1000))
        self.assertIsNone(candidate(self.p,1540.01))
        self.assertIsNone(candidate(self.p,939))
    def test_missing_or_invalid(self):
        for field in ('liquidity','volume','txns','pairCreatedAt'):
            p=copy.deepcopy(self.p);del p[field];self.assertIsNone(candidate(p,1000))
        for val in (None,float('nan'),float('inf'),True,-1):
            p=copy.deepcopy(self.p);p['liquidity']['usd']=val;self.assertIsNone(candidate(p,1000))
    def test_pressure(self):
        self.p['txns']['m5']['sells']=40;self.assertIsNone(candidate(self.p,1000))
    def test_security(self):
        b=bytearray(82);b[45]=1
        a={'owner':PROGRAM,'executable':False,'data':[base64.b64encode(b).decode(),'base64']}
        self.assertTrue(secure(a))
        b[46]=1;a['data'][0]=base64.b64encode(b).decode();self.assertFalse(secure(a))
        a['owner']='Token2022';self.assertFalse(secure(a));self.assertFalse(secure(None))
if __name__=='__main__':unittest.main()
