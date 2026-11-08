"""Read-only vault proofs from authenticated pool state; no label-based exclusions.

Layouts: pump-fun/pump-public-docs IDL; raydium-io/raydium-sdk-V2 and
raydium-cp-swap/raydium-clmm on-chain PoolState. See UPGRADE.md for sources.
Unknown protocols, changed layouts, or missing evidence retain the raw accounts.
"""
import base64
import hashlib
import struct
from collections import defaultdict

ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
PUMP = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
CPMM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
CLMM = 'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK'
AMM_V4 = '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
CPMM_AUTHORITY = 'GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL'
POOL_DISC = bytes([241,154,109,4,17,177,109,188])
STATE_DISC = hashlib.sha256(b'account:PoolState').digest()[:8]


def b58encode(raw):
    n = int.from_bytes(raw,'big'); result = ''
    while n:
        n, digit = divmod(n,58); result = ALPHABET[digit]+result
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+result


def key_bytes(value):
    if not isinstance(value,str) or not 32 <= len(value) <= 44: raise ValueError('invalid_public_key')
    n = 0
    for letter in value:
        if letter not in ALPHABET: raise ValueError('invalid_public_key')
        n = n*58+ALPHABET.index(letter)
    raw = b'\0'*(len(value)-len(value.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8,'big') if n else b'')
    if len(raw) != 32: raise ValueError('invalid_public_key_size')
    return raw


def raw_data(account):
    if not isinstance(account,dict) or account.get('executable') is not False: raise ValueError('invalid_account')
    data = account.get('data')
    if not isinstance(data,list) or len(data)!=2 or data[1]!='base64': raise ValueError('invalid_encoding')
    return base64.b64decode(data[0],validate=True)


def pda_with_stored_bump(seeds, bump, program):
    if not isinstance(bump,int) or not 0 <= bump <= 255: raise ValueError('invalid_bump')
    # Bump comes from the program-owned state, not an untrusted off-chain label.
    return b58encode(hashlib.sha256(b''.join(seeds)+bytes([bump])+key_bytes(program)+b'ProgramDerivedAddress').digest())


def pool_vault(pool, account):
    """Return the candidate mint's vault and authority, or refuse an exemption."""
    pair = pool['pairAddress']; mint = pool['baseToken']['address']
    key_bytes(pair); key_bytes(mint)
    owner = account.get('owner') if isinstance(account,dict) else None
    if owner not in (PUMP,CPMM,CLMM,AMM_V4): raise ValueError('unsupported_pool_program')
    raw = raw_data(account); at = lambda offset:b58encode(raw[offset:offset+32])
    disabled = False
    if owner == PUMP:
        if len(raw)<211 or raw[:8]!=POOL_DISC: raise ValueError('unrecognized_pool_layout')
        expected = pda_with_stored_bump([b'pool',raw[9:11],raw[11:43],raw[43:75],raw[75:107]],raw[8],PUMP)
        if expected!=pair: raise ValueError('pool_pda_mismatch')
        mints = (at(43),at(75)); vaults = (at(139),at(171)); authority = pair; protocol = 'PumpSwap'
    elif owner == CPMM:
        if len(raw)!=637 or raw[:8]!=STATE_DISC: raise ValueError('unrecognized_pool_layout')
        authority = pda_with_stored_bump([b'vault_and_lp_mint_auth_seed'],raw[328],CPMM)
        if authority!=CPMM_AUTHORITY: raise ValueError('pool_authority_mismatch')
        mints = (at(168),at(200)); vaults = (at(72),at(104)); protocol = 'Raydium CPMM'
        disabled = bool(raw[329] & 4)
    elif owner == CLMM:
        if len(raw)!=1544 or raw[:8]!=STATE_DISC: raise ValueError('unrecognized_pool_layout')
        extra = raw[391:393] if raw[391:393]!=b'\0\0' else b''
        expected = pda_with_stored_bump([b'pool',raw[9:41],raw[73:105],raw[105:137],extra],raw[8],CLMM)
        if expected!=pair: raise ValueError('pool_pda_mismatch')
        mints = (at(73),at(105)); vaults = (at(137),at(169)); authority = pair; protocol = 'Raydium CLMM'
        disabled = bool(raw[389] & 16)
    else:
        if len(raw)!=752: raise ValueError('unrecognized_pool_layout')
        status, nonce = struct.unpack_from('<QQ',raw)
        if status not in range(1,8): raise ValueError('uninitialized_pool')
        authority = pda_with_stored_bump([b'amm authority'],nonce,AMM_V4)
        mints = (at(400),at(432)); vaults = (at(336),at(368)); protocol = 'Raydium AMM v4'
        disabled = status not in (1,6)
    if mint not in mints or mints[0]==mints[1] or vaults[0]==vaults[1]: raise ValueError('pool_mint_mismatch')
    index = mints.index(mint); other = mints[1-index]
    quote = (pool.get('quoteToken') or {}).get('address')
    if quote and quote!=other: raise ValueError('pool_quote_mismatch')
    return {'vault':vaults[index], 'authority':authority, 'mint':mint, 'protocol':protocol,
            'token_program':at(232+index*32) if owner==CPMM else None,
            'swaps_disabled':disabled, 'pool':pair}


def token_account(account, mint, token_program):
    if account.get('owner')!=token_program: raise ValueError('wrong_token_program')
    raw = raw_data(account)
    if len(raw)<165 or b58encode(raw[:32])!=mint or raw[108] not in (1,2): raise ValueError('wrong_token_account')
    if token_program=='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' and len(raw)!=165: raise ValueError('wrong_token_account_length')
    if len(raw)>165 and raw[165]!=2: raise ValueError('wrong_token_account_type')
    return {'authority':b58encode(raw[32:64]),'amount':struct.unpack_from('<Q',raw,64)[0],
            'raw':raw,'frozen':raw[108]==2}


def verify_vault(proof, account, token_program):
    if proof.get('token_program') and proof['token_program']!=token_program: raise ValueError('vault_token_program_mismatch')
    parsed = token_account(account,proof['mint'],token_program); raw = parsed['raw']
    if parsed['authority']!=proof['authority'] or parsed['frozen']: raise ValueError('vault_authority_or_state_mismatch')
    if struct.unpack_from('<I',raw,72)[0]!=0 or struct.unpack_from('<Q',raw,121)[0]!=0: raise ValueError('vault_delegate_unverified')
    close = struct.unpack_from('<I',raw,129)[0]
    if close not in (0,1) or (close and b58encode(raw[133:165])!=proof['authority']): raise ValueError('vault_close_authority_unverified')
    if len(raw)>165:
        if raw[165]!=2: raise ValueError('vault_extensions_unverified')
        offset = 166; seen = set()
        while offset<len(raw):
            if not any(raw[offset:]): break
            if offset+4>len(raw): raise ValueError('vault_extensions_unverified')
            kind,size = struct.unpack_from('<HH',raw,offset); offset += 4
            # Only immutable-owner token-account extension is supported here.
            if kind!=7 or size!=0 or kind in seen: raise ValueError('vault_extensions_unverified')
            seen.add(kind); offset += size
    return parsed


def concentration(pool, mint_account, api, rpc):
    """Compare raw and adjusted top-10 TOKEN ACCOUNTS, using at most two RPCs."""
    mint = pool['baseToken']['address']; pair = pool['pairAddress']
    initial = raw_data(mint_account); supply = struct.unpack_from('<Q',initial,36)[0]
    if supply<=0: raise ValueError('invalid_supply')
    response = rpc(api,'getTokenLargestAccounts',[mint,{'commitment':'finalized'}])
    rows = response['value']; slot = response['context']['slot']
    if not isinstance(rows,list) or not 1<=len(rows)<=20 or not isinstance(slot,int) or isinstance(slot,bool): raise ValueError('invalid_holder_response')
    balances = []; addresses = []
    for row in rows:
        key_bytes(row['address']); amount = row['amount']
        if not isinstance(amount,str) or not amount.isascii() or not amount.isdigit(): raise ValueError('invalid_holder_amount')
        balances.append(int(amount)); addresses.append(row['address'])
    if len(set(addresses))!=len(addresses) or balances!=sorted(balances,reverse=True) or sum(balances)>supply: raise ValueError('invalid_holder_snapshot')
    raw_pct = 100*sum(balances[:10])/supply
    out = {'raw_top10_pct':raw_pct,'top10_accounts_pct':raw_pct,'excluded_vaults':[], 'excluded_pct':0,
           'verified':False,'vault_status':'unverified','top1_observed_owner_pct':None,'reject':None}
    try:
        batch = rpc(api,'getMultipleAccounts',[[mint,pair]+addresses,{'encoding':'base64','commitment':'finalized','minContextSlot':slot}])
        values = batch['value']; batch_slot = batch['context']['slot']
        if len(values)!=len(addresses)+2 or not isinstance(batch_slot,int) or not 0<=batch_slot-slot<=40: raise ValueError('inconsistent_rpc_slots')
        if api.security_reason(values[0]): raise ValueError('mint_security_changed')
        current_supply = struct.unpack_from('<Q',raw_data(values[0]),36)[0]
        if current_supply!=supply: raise ValueError('supply_changed')
        token_program = values[0]['owner']; parsed = {}
        for key,amount,account in zip(addresses,balances,values[2:]):
            token = token_account(account,mint,token_program)
            parsed[key] = token
        if sum(t['amount'] for t in parsed.values())>supply: raise ValueError('invalid_current_balances')
        proof = None
        try:
            proof = pool_vault(pool,values[1]); out['vault_status'] = 'not_in_largest_accounts'
            if proof['swaps_disabled']: out['reject'] = 'pool_swaps_disabled'
            if proof['vault'] in parsed:
                vault = verify_vault(proof,values[2+addresses.index(proof['vault'])],token_program)
                out['excluded_vaults'] = [{'address':proof['vault'],'protocol':proof['protocol'],'pool':pair}]
                # Keep numerator and denominator at the largest-accounts snapshot.
                # Ordinary trades can change balances while the immutable vault role is proved.
                out['excluded_pct'] = 100*balances[addresses.index(proof['vault'])]/supply
                out['vault_status'] = 'onchain_verified'
        except (ValueError,TypeError,KeyError,IndexError,struct.error):
            out['vault_status'] = 'unsupported_or_unproven'; out['excluded_vaults'] = []
        excluded = {r['address'] for r in out['excluded_vaults']}
        non_vault = [(key,amount) for key,amount in zip(addresses,balances) if key not in excluded]
        if len(non_vault)<10 and len(rows)==20: raise ValueError('insufficient_nonvault_sample')
        if len(rows)<10 and sum(balances)!=supply: raise ValueError('incomplete_holder_sample')
        out['top10_accounts_pct'] = 100*sum(amount for key,amount in non_vault[:10])/supply
        owners = defaultdict(int)
        for key,amount in non_vault: owners[parsed[key]['authority']] += parsed[key]['amount']
        out['top1_observed_owner_pct'] = 100*max(owners.values(),default=0)/supply
        out['verified'] = True; out['context_slot'] = slot; out['proof_context_slot'] = batch_slot
        out['balances_changed_during_proof'] = any(parsed[k]['amount']!=amount for k,amount in zip(addresses,balances))
    except Exception:
        # No partial exemption survives a failed or changing snapshot.
        out.update(top10_accounts_pct=raw_pct,excluded_vaults=[],excluded_pct=0,verified=False,vault_status='snapshot_unavailable_or_changed',top1_observed_owner_pct=None)
    return out
