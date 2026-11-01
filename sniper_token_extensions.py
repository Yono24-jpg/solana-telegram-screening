"""Fail-closed mint TLV audit; no wallet, signing or transaction construction.
Layouts: solana-program/token-2022 interface/src/extension/mod.rs.
Only transfer-neutral metadata or provably disabled controls are accepted.
"""
import base64
import struct

TOKEN_PROGRAM='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
NAMES={1:'TransferFeeConfig',3:'MintCloseAuthority',4:'ConfidentialTransferMint',6:'DefaultAccountState',
9:'NonTransferable',10:'InterestBearingConfig',12:'PermanentDelegate',14:'TransferHook',
16:'ConfidentialTransferFeeConfig',18:'MetadataPointer',19:'TokenMetadata',20:'GroupPointer',
21:'TokenGroup',22:'GroupMemberPointer',23:'TokenGroupMember',24:'ConfidentialMintBurn',
25:'ScaledUiAmount',26:'Pausable',28:'PermissionedBurn'}


def metadata_valid(data):
    # Borsh TokenMetadata: update_authority, mint, three strings, Vec<(String,String)>.
    if len(data)<80:return False
    pos=64
    def string():
        nonlocal pos
        if pos+4>len(data):raise ValueError()
        size=int.from_bytes(data[pos:pos+4],'little');pos+=4
        if pos+size>len(data):raise ValueError()
        data[pos:pos+size].decode('utf-8');pos+=size
    try:
        for _ in range(3):string()
        if pos+4>len(data):return False
        count=int.from_bytes(data[pos:pos+4],'little');pos+=4
        if count>(len(data)-pos)//8:return False
        for _ in range(count):string();string()
        return pos==len(data)
    except (ValueError,UnicodeDecodeError):return False


def audit_raw_mint(value):
    result=dict(verified=False,extensions=[],reasons=[],transfer_fee_bps=None,
                transfer_restrictions_verified=False)
    try:
        if not isinstance(value,dict) or value.get('owner') not in (TOKEN_PROGRAM,TOKEN_2022):
            raise ValueError('unsupported_mint_owner')
        encoded=value.get('data')
        if not isinstance(encoded,list) or len(encoded)!=2 or encoded[1]!='base64':
            raise ValueError('raw_mint_data_missing')
        data=base64.b64decode(encoded[0],validate=True)
        if len(data)<82 or data[45]!=1 or data[:4] not in (bytes(4),b'\x01\0\0\0') or data[46:50] not in (bytes(4),b'\x01\0\0\0'):
            raise ValueError('invalid_mint_base_layout')
        result.update(mint_revoked=data[:4]==bytes(4),freeze_revoked=data[46:50]==bytes(4),
                      decimals=data[44],raw_length=len(data),transfer_fee_bps=0)
        if value['owner']==TOKEN_PROGRAM:
            if len(data)!=82:raise ValueError('unexpected_legacy_mint_length')
        elif len(data)!=82:
            if len(data)<166 or any(data[82:165]) or data[165]!=1 or len(data)==355:
                raise ValueError('invalid_extended_mint_layout')
            pos=166;seen=set()
            while pos<len(data):
                if not any(data[pos:]):break  # zero-filled allocation padding only
                if pos+4>len(data):raise ValueError('truncated_tlv_header')
                kind,size=struct.unpack_from('<HH',data,pos);pos+=4
                if kind==0 or kind in seen or pos+size>len(data):raise ValueError('invalid_or_duplicate_tlv')
                seen.add(kind);body=data[pos:pos+size];pos+=size
                row=dict(id=kind,name=NAMES.get(kind,'Unknown'),length=size,status='reject')
                if kind in (18,20,22) and size==64:
                    row['status']='pass_metadata_only'
                elif kind==19 and metadata_valid(body):row['status']='pass_metadata_only'
                elif kind==21 and size==80:row['status']='pass_metadata_only'
                elif kind==23 and size==72:row['status']='pass_metadata_only'
                elif kind in (3,12) and size==32 and not any(body):row['status']='pass_disabled'
                elif kind==6 and size==1 and body==b'\x01':row['status']='pass_initialized_accounts'
                elif kind==14 and size==64 and not any(body):row['status']='pass_disabled'
                elif kind==26 and size==33:
                    row.update(pause_authority_present=any(body[:32]),paused=body[32]!=0)
                    if not any(body):row['status']='pass_immutable_unpaused'
                elif kind==1 and size==108:
                    schedules=[]
                    for offset in (72,90):
                        epoch,maximum,bps=struct.unpack_from('<QQH',body,offset)
                        schedules.append(dict(epoch=epoch,maximum_fee=maximum,basis_points=bps))
                    row.update(schedules=schedules,fee_config_mutable=any(body[:32]),
                               withdraw_authority_present=any(body[32:64]))
                    result['transfer_fee_bps']=max(s['basis_points'] for s in schedules)
                    # Accept zero current AND future fees only, and no ability to raise fees.
                    if not any(body[:32]) and all(s['basis_points']==0 for s in schedules):
                        row['status']='pass_immutable_zero_fee'
                # All confidential, nontransferable, scaled/interest, active pausable,
                # permissioned burn, account-only and future unknown types fail closed.
                if row['status']=='reject':result['reasons'].append('extension_unverified_or_restricted_'+row['name'])
                result['extensions'].append(row)
        result['transfer_restrictions_verified']=not result['reasons']
        result['verified']=result['transfer_restrictions_verified']
    except (ValueError,TypeError,KeyError,struct.error) as error:
        result['reasons'].append(str(error) if isinstance(error,ValueError) else 'malformed_raw_mint')
    return result


def uint64(value):
    if isinstance(value,bool) or not isinstance(value,(int,str)):
        raise ValueError('invalid_raw_amount')
    if isinstance(value,str) and (not value.isascii() or not value.isdigit()):
        raise ValueError('invalid_raw_amount')
    result=int(value)
    if not 0<=result<2**64:raise ValueError('invalid_raw_amount')
    return result


def validate_quote(quote,input_mint,output_mint,amount,verified_intermediates=()):
    """A route quote proves current quoted routability, never guaranteed execution."""
    try:
        if not isinstance(quote,dict) or quote.get('inputMint')!=input_mint or quote.get('outputMint')!=output_mint:
            return False
        if quote.get('swapMode')!='ExactIn' or uint64(quote['inAmount'])!=amount or amount<=0:return False
        out=uint64(quote['outAmount']);threshold=uint64(quote['otherAmountThreshold'])
        if (out<=0 or not 0<threshold<=out or quote.get('slippageBps')!=50
            or threshold<out*9950//10000):return False
        if type(quote.get('contextSlot')) is not int or quote['contextSlot']<=0:return False
        import math
        impact=float(quote['priceImpactPct'])
        if not math.isfinite(impact) or abs(impact)>.01:return False
        route=quote.get('routePlan')
        if not isinstance(route,list) or not route:return False
        if len(route)>8:return False
        wrapped_sol='So11111111111111111111111111111111111111112'
        allowed={input_mint,output_mint,wrapped_sol}|set(verified_intermediates)
        inflow={};outflow={};edges={}
        for leg in route:
            swap=leg['swapInfo'];source=swap['inputMint'];target=swap['outputMint']
            if source not in allowed or target not in allowed or source==target:return False
            if source==output_mint or target==input_mint:return False
            incoming=uint64(swap['inAmount']);outgoing=uint64(swap['outAmount'])
            if not swap.get('ammKey') or incoming<=0 or outgoing<=0:return False
            # Current Jupiter responses may omit the deprecated per-leg fee fields.
            # Net outAmount already includes AMM/platform fees; never treat omitted
            # fee components as zero. If present, both fields must validate.
            if 'feeAmount' in swap or 'feeMint' in swap:
                if uint64(swap['feeAmount'])<0 or swap['feeMint'] not in (source,target):return False
            outflow[source]=outflow.get(source,0)+incoming
            inflow[target]=inflow.get(target,0)+outgoing
            edges.setdefault(source,set()).add(target)
        if outflow.get(input_mint)!=amount or inflow.get(output_mint)!=out:return False
        for token in (set(inflow)|set(outflow))-{input_mint,output_mint}:
            if not 0<outflow.get(token,0)<=inflow.get(token,0):return False
        # Only the audited mint, USDC endpoints and canonical wrapped SOL allowed.
        visiting=set();visited=set()
        def acyclic(node):
            if node in visiting:return False
            if node in visited:return True
            visiting.add(node)
            if any(not acyclic(t) for t in edges.get(node,())):return False
            visiting.remove(node);visited.add(node);return True
        if not acyclic(input_mint):return False
        reachable={input_mint}
        for _ in range(len(allowed)):
            reachable.update(t for source in list(reachable) for t in edges.get(source,()))
        return set(inflow)|set(outflow) <= reachable and output_mint in reachable

    except (KeyError,ValueError,TypeError,OverflowError):return False


def base58_public_key(raw):
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    value=int.from_bytes(raw,'big');encoded=''
    while value:
        value,digit=divmod(value,58);encoded=alphabet[digit]+encoded
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+encoded


def audit_raw_token_account(value,expected_mint,expected_authority,expected_program,minimum_raw=0):
    """Current pool vault: frozen/CPI/memo/hook/withheld-fee checks, fail closed."""
    result=dict(verified=False,reasons=[],extensions=[])
    try:
        if not isinstance(value,dict) or value.get('owner')!=expected_program or expected_program not in (TOKEN_PROGRAM,TOKEN_2022):
            raise ValueError('vault_program_unverified')
        encoded=value.get('data')
        if not isinstance(encoded,list) or encoded[1]!='base64':raise ValueError('vault_raw_data_unavailable')
        data=base64.b64decode(encoded[0],validate=True)
        if len(data)<165:raise ValueError('vault_base_truncated')
        if base58_public_key(data[:32])!=expected_mint or base58_public_key(data[32:64])!=expected_authority:
            raise ValueError('vault_mint_or_authority_mismatch')
        if data[108]!=1:raise ValueError('vault_frozen_or_uninitialized')
        if data[109:113] not in (bytes(4),b'\x01\0\0\0'):raise ValueError('vault_native_option_invalid')
        if data[72:76]!=bytes(4):raise ValueError('vault_delegate_unverified')
        close=data[129:133]
        if close not in (bytes(4),b'\x01\0\0\0') or (close!=bytes(4) and base58_public_key(data[133:165])!=expected_authority):
            raise ValueError('vault_close_authority_unverified')
        amount=int.from_bytes(data[64:72],'little');withheld=0
        if expected_program==TOKEN_PROGRAM and len(data)!=165:raise ValueError('vault_legacy_length_invalid')
        if expected_program==TOKEN_2022 and len(data)!=165:
            if len(data)<166 or data[165]!=2:raise ValueError('vault_extension_account_type_invalid')
            pos=166;seen=set()
            while pos<len(data):
                if not any(data[pos:]):break
                if pos+4>len(data):raise ValueError('vault_tlv_truncated')
                kind,size=struct.unpack_from('<HH',data,pos);pos+=4
                if kind==0 or kind in seen or pos+size>len(data):raise ValueError('vault_tlv_invalid')
                seen.add(kind);body=data[pos:pos+size];pos+=size
                ok=False
                if kind==2 and size==8:withheld=int.from_bytes(body,'little');ok=True
                elif kind in (7,27) and size==0:ok=True
                elif kind in (8,11,15) and size==1 and body==b'\0':ok=True
                result['extensions'].append(dict(id=kind,length=size,verified=ok))
                if not ok:raise ValueError('vault_extension_unverified_'+str(kind))
        # Token-2022 credits base.amount with transfer amount MINUS fee.
        # withheld_amount is a separate accumulator, not part of base.amount.
        # Do not subtract it twice (program/src/processor.rs credited_amount).
        spendable=amount
        result.update(amount_raw=amount,withheld_raw=withheld,spendable_raw=spendable,
            mint=expected_mint,authority=expected_authority,program=expected_program)
        if spendable<0 or spendable<minimum_raw:raise ValueError('vault_spendable_balance_insufficient')
        result['verified']=True
    except (ValueError,TypeError,KeyError,IndexError,struct.error) as error:
        result['reasons'].append(str(error) if isinstance(error,ValueError) else 'vault_malformed')
    return result
