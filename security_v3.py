"""Mandatory, read-only v3 evidence gates. Unknown evidence never becomes safe."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import re
import hashlib
import vault_checks
import time
import evidence
from screening_rules import address, amount, number
from market_data import QUOTE_ASSETS


class EvidenceMissing(ValueError):
    """Only locally generated, non-sensitive rejection codes."""


def report_gate(report, pool, allowed_programs=None):
    """Pool-specific liquidity and explicit insider coverage, not token-wide LP labels."""
    if not isinstance(report,dict): return 'full_report_unavailable'
    mint = pool['baseToken']['address']
    if report.get('mint') != mint: return 'report_mint_mismatch'
    if report.get('rugged') is not False: return 'rugged_or_unknown'
    token = report.get('token') or {}
    if token.get('mintAuthority','missing') is not None or token.get('freezeAuthority','missing') is not None: return 'report_authority_active_or_unknown'
    if report.get('tokenProgram') not in (allowed_programs or ('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',)): return 'v3_token_program_unsupported'
    supply = token.get('supply')
    if not number(supply) or supply <= 0: return 'report_supply_unavailable'
    if not address(report.get('creator')): return 'developer_unknown'
    networks = report.get('insiderNetworks')
    if not isinstance(networks,list) or not number(report.get('graphInsidersDetected')): return 'insider_coverage_unavailable'
    if report['graphInsidersDetected'] < 0 or (not networks and report['graphInsidersDetected'] != 0): return 'insider_coverage_inconsistent'
    # Any reported network is conservative rejection, including bundles and linked funders.
    if networks or report['graphInsidersDetected'] > 0: return 'insider_or_bundle_network_detected'
    risks = report.get('risks')
    if not isinstance(risks,list): return 'risk_report_unavailable'
    for risk in risks:
        if not isinstance(risk,dict) or not isinstance(risk.get('level'),str): return 'risk_report_malformed'
        if risk['level'].lower() in ('danger','critical'): return 'provider_danger'
        if re.search('insider|bundl|wash|creator|rug|mutable', str(risk.get('name','')),re.I): return 'provider_suspicious_flag'
    score = report.get('score_normalised')
    if not number(score) or not 0 <= score < 40: return 'provider_risk_high_or_unknown'
    markets = report.get('markets')
    if not isinstance(markets,list): return 'liquidity_security_unavailable'
    markets = [m for m in markets if isinstance(m,dict) and m.get('pubkey') == pool['pairAddress']]
    if len(markets)!=1: return 'candidate_pool_lock_unavailable'
    market = markets[0]
    if mint not in (market.get('mintA'),market.get('mintB')): return 'locked_pool_mint_unverified'
    lp = market.get('lp') or {}
    pct = lp.get('lpLockedPct'); usd = lp.get('lpLockedUSD')
    if not number(pct) or not number(usd) or not 95 <= pct <= 100 or usd < 10000: return 'pool_lock_under_95_or_unverified'
    return None


def developer_check(report, api, now):
    creator = report['creator']; mint = report['mint']; supply = report['token']['supply']
    data = evidence.rpc(api,'getTokenAccountsByOwner',[creator,{'mint':mint},{'encoding':'jsonParsed','commitment':'finalized'}])
    if not isinstance(data,dict) or not isinstance(data.get('value'),list): raise EvidenceMissing('developer_balances_unavailable')
    balance = 0
    for row in data['value']:
        info = row['account']['data']['parsed']['info']
        if info['mint'] != mint or info['owner'] != creator: raise EvidenceMissing('developer_identity_mismatch')
        raw = info['tokenAmount']['amount']
        if not isinstance(raw,str) or not raw.isdigit(): raise EvidenceMissing('developer_balance_malformed')
        balance += int(raw)
    pct = 100*balance/supply
    if pct > 5: return {'reject':'developer_holds_over_5_pct','holding_pct':pct}
    signatures = evidence.rpc(api,'getSignaturesForAddress',[creator,{'limit':5,'commitment':'finalized'}])
    if not isinstance(signatures,list) or not signatures: raise EvidenceMissing('developer_history_unavailable')
    observed = 0
    for row in signatures:
        if not isinstance(row,dict) or not number(row.get('blockTime')): raise EvidenceMissing('developer_history_incomplete')
        if row['blockTime'] > now: raise EvidenceMissing('developer_history_future')
        if now-row['blockTime'] > 3600 or row.get('err') is not None: continue
        tx = evidence.rpc(api,'getTransaction',[row['signature'],{'encoding':'jsonParsed','commitment':'finalized','maxSupportedTransactionVersion':0}])
        if not isinstance(tx,dict) or not isinstance(tx.get('meta'),dict) or tx['meta'].get('err') is not None: raise EvidenceMissing('developer_transaction_unavailable')
        pre = owner_balances(tx['meta'].get('preTokenBalances'), creator, mint)
        post = owner_balances(tx['meta'].get('postTokenBalances'), creator, mint)
        if post < pre: return {'reject':'developer_recent_token_outflow','holding_pct':pct}
        observed += 1
    return {'reject':None,'holding_pct':pct,'recent_transactions_checked':observed,'history_limit':5}


def owner_balances(rows, owner, mint):
    if not isinstance(rows,list): raise EvidenceMissing('token_balances_unavailable')
    total = 0
    for r in rows:
        if not isinstance(r,dict): raise EvidenceMissing('token_balances_malformed')
        if r.get('owner') == owner and r.get('mint') == mint:
            raw = r['uiTokenAmount']['amount']
            if not isinstance(raw,str) or not raw.isdigit(): raise EvidenceMissing('token_balance_malformed')
            total += int(raw)
    return total


def has_pool_swap(tx, pair):
    """A pool reference alone is not a swap: require a supported program instruction."""
    instructions = list(tx.get('transaction',{}).get('message',{}).get('instructions',[]))
    for group in tx.get('meta',{}).get('innerInstructions') or []:
        instructions.extend(group.get('instructions',[]))
    names = {
        vault_checks.PUMP: ('buy','sell','buy_exact_quote_in'),
        vault_checks.CPMM: ('swap_base_input','swap_base_output'),
        vault_checks.CLMM: ('swap','swap_v2','swap_router_base_in'),
    }
    for instruction in instructions:
        if not isinstance(instruction,dict) or pair not in instruction.get('accounts',[]): continue
        program = instruction.get('programId'); encoded = instruction.get('data')
        if program not in (*names,vault_checks.AMM_V4) or not isinstance(encoded,str) or not 1<=len(encoded)<=4096: continue
        try:
            value=0
            for letter in encoded: value=value*58+vault_checks.ALPHABET.index(letter)
            raw=b'\0'*(len(encoded)-len(encoded.lstrip('1')))+(value.to_bytes((value.bit_length()+7)//8,'big') if value else b'')
            if program==vault_checks.AMM_V4 and raw and raw[0] in (9,11): return True
            if program in names and raw[:8] in [hashlib.sha256(('global:'+name).encode()).digest()[:8] for name in names[program]]: return True
        except (ValueError,OverflowError): continue
    return False


def transaction_sample(pool, buyers, api, now):
    mint = pool['baseToken']['address']; pair = pool['pairAddress']
    sample = buyers.get('transactions', [])
    if not isinstance(sample,list): raise EvidenceMissing('trade_sample_unavailable')
    # At most one buy per observed wallet, plus three independently signed sells.
    picks = []; seen = set()
    for kind, limit in [('sell',3),('buy',12)]:
        selected = 0
        for row in sample:
            if row.get('kind')!=kind or (kind,row.get('wallet')) in seen: continue
            if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{64,88}',row.get('signature','')): raise EvidenceMissing('invalid_trade_signature')
            seen.add((kind,row['wallet'])); picks.append(row); selected += 1
            if selected >= limit: break
        if selected < limit: raise EvidenceMissing('insufficient_sell_or_buyer_sample')
    def read(row):
        try:
            tx = evidence.rpc(api,'getTransaction',[row['signature'],{'encoding':'jsonParsed','commitment':'finalized','maxSupportedTransactionVersion':0}])
            return row, tx
        except Exception: return row, None
    slots = defaultdict(set); cosigners = defaultdict(set); sellers = set()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for row, tx in executor.map(read,picks):
            if not isinstance(tx,dict) or not isinstance(tx.get('meta'),dict): raise EvidenceMissing('trade_transaction_missing')
            meta = tx['meta']; when = tx.get('blockTime'); slot = tx.get('slot')
            if meta.get('err') is not None or not number(when) or not 0<=now-when<=300 or not isinstance(slot,int): raise EvidenceMissing('trade_transaction_failed_or_stale')
            if not has_pool_swap(tx,pair): raise EvidenceMissing('supported_pool_swap_unverified')
            keys = tx['transaction']['message']['accountKeys']
            if not isinstance(keys,list) or not all(isinstance(k,dict) for k in keys): raise EvidenceMissing('trade_keys_unavailable')
            addresses = [k.get('pubkey') for k in keys]; wallet = row['wallet']
            if pair not in addresses or not any(k.get('pubkey')==wallet and k.get('signer') is True for k in keys): raise EvidenceMissing('trade_pool_or_signer_mismatch')
            pre = owner_balances(meta.get('preTokenBalances'),wallet,mint); post = owner_balances(meta.get('postTokenBalances'),wallet,mint)
            if row['kind']=='sell':
                if post >= pre: raise EvidenceMissing('sell_token_debit_unverified')
                quote_gain = any(owner_balances(meta.get('postTokenBalances'),wallet,q)>owner_balances(meta.get('preTokenBalances'),wallet,q) for q in QUOTE_ASSETS)
                index = addresses.index(wallet)
                if not quote_gain:
                    quote_gain = meta['postBalances'][index]+(meta.get('fee',0) if index==0 else 0)>meta['preBalances'][index]
                if not quote_gain: raise EvidenceMissing('sell_proceeds_unverified')
                sellers.add(wallet)
            else:
                if post <= pre: raise EvidenceMissing('buy_credit_unverified')
                slots[slot].add(wallet)
                for k in keys:
                    if k.get('signer') is True and k.get('pubkey')!=wallet: cosigners[k['pubkey']].add(wallet)
    if max((len(v) for v in slots.values()),default=0)>=4 or max((len(v) for v in cosigners.values()),default=0)>=4:
        return {'reject':'bundled_slot_or_shared_signer_pattern'}
    return {'reject':None,'finalized_sells':len(sellers),'finalized_buys':12,'sample_limit':15,
            'caveat':'Sampel transaksi, bukan pemetaan semua insider; jual setiap wallet tidak dijamin.'}


def inspect(pool, sec, buyers, api, now, extension_proof=None):
    out = {'complete':False,'score':None,'reject':None,'checks':{},'risks':[
        'Risiko rug pull tetap ada; laporan pihak ketiga dan sampel wallet dapat melewatkan hubungan tersembunyi.',
        'LP lock berdasarkan laporan pool RugCheck; status dapat berubah.',
        'Bukti jual adalah transaksi historis terbaru, bukan jaminan semua wallet bisa menjual.']}
    try:
        if sec.get('reject') or not sec.get('complete') or not sec.get('authority_verified') or sec.get('score')!=100:
            raise EvidenceMissing('base_security_incomplete')
        distribution = sec.get('distribution') or {}
        if not distribution.get('verified') or not number(distribution.get('top1_observed_owner_pct')): raise EvidenceMissing('holder_owner_coverage_incomplete')
        if buyers.get('risks') or not buyers.get('strong'): raise EvidenceMissing('wash_sample_risky_or_incomplete')
        report = api.request('https://api.rugcheck.xyz/v1/tokens/'+pool['baseToken']['address']+'/report')
        if sec.get('token_program') != report.get('tokenProgram') or sec.get('mint_supply') != (report.get('token') or {}).get('supply'):
            raise EvidenceMissing('provider_onchain_mint_mismatch')
        allowed = None
        if extension_proof is not None:
            if not extension_proof.get('complete') or extension_proof.get('reject') or extension_proof.get('program')!=sec.get('token_program'):
                raise EvidenceMissing('token_extension_evidence_incomplete')
            allowed = (extension_proof['program'],)
        reason = report_gate(report,pool,allowed)
        if reason: raise EvidenceMissing(reason)
        out['checks']['provider'] = {'fetched_at':now,'insider_networks':0,'pool':pool['pairAddress'],
                                    'lp_locked_pct':next(m['lp']['lpLockedPct'] for m in report['markets'] if m['pubkey']==pool['pairAddress'])}
        developer = developer_check(report,api,time.time()); out['checks']['developer'] = developer
        if developer.get('reject'): raise EvidenceMissing(developer['reject'])
        trades = transaction_sample(pool,buyers,api,time.time()); out['checks']['transactions'] = trades
        if trades.get('reject'): raise EvidenceMissing(trades['reject'])
        out.update(complete=True,score=100)
    except Exception as error:
        # Only internal fixed codes; never expose HTTP URLs or exception text from providers.
        out['reject'] = str(error) if isinstance(error,EvidenceMissing) else 'v3_security_unavailable'
    return out
