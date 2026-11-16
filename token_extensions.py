"""On-chain Token-2022 extension audit. Unknown and mutable layouts fail closed."""
import struct
import vault_checks

CLASSIC = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
NAMES = ['Uninitialized','TransferFeeConfig','TransferFeeAmount','MintCloseAuthority',
 'ConfidentialTransferMint','ConfidentialTransferAccount','DefaultAccountState','ImmutableOwner',
 'MemoTransfer','NonTransferable','InterestBearingConfig','CpiGuard','PermanentDelegate',
 'NonTransferableAccount','TransferHook','TransferHookAccount','ConfidentialTransferFeeConfig',
 'ConfidentialTransferFeeAmount','MetadataPointer','TokenMetadata','GroupPointer','TokenGroup',
 'GroupMemberPointer','TokenGroupMember','ConfidentialMintBurn','ScaledUiAmount','Pausable','PausableAccount']


def audit(account, mint):
    out = {'complete':False, 'reject':None, 'extensions':[], 'program':None}
    try:
        if account.get('executable') is not False:raise ValueError('mint_executable_or_unverified')
        raw = vault_checks.raw_data(account); owner = account['owner']; out['program'] = owner
        if owner not in (CLASSIC,TOKEN2022): raise ValueError('token_program_unsupported')
        if len(raw)<82 or raw[45]!=1: raise ValueError('invalid_initialized_mint')
        if struct.unpack_from('<I',raw,0)[0]!=0: raise ValueError('mint_authority_active')
        if struct.unpack_from('<I',raw,46)[0]!=0: raise ValueError('freeze_authority_active')
        if owner==CLASSIC:
            if len(raw)!=82: raise ValueError('invalid_classic_layout')
        elif len(raw)!=82:
            if len(raw)<166 or any(raw[82:165]) or raw[165]!=1: raise ValueError('invalid_token2022_layout')
            entries={}; pos=166
            while pos<len(raw):
                if len(raw)-pos<4: raise ValueError('extension_header_truncated')
                kind,size=struct.unpack_from('<HH',raw,pos); pos+=4
                if kind==0:
                    if size or any(raw[pos:]): raise ValueError('extension_padding_invalid')
                    break
                if kind in entries or size>len(raw)-pos: raise ValueError('extension_duplicate_or_truncated')
                data=raw[pos:pos+size]; pos+=size; entries[kind]=data
                out['extensions'].append({'id':kind,'name':NAMES[kind] if kind<len(NAMES) else 'Unknown'})
                if kind not in (18,19): raise ValueError('token2022_dangerous_or_unsupported_extension')
            if 18 in entries:
                data=entries[18]
                if len(data)!=64 or any(data[:32]) or data[32:]!=vault_checks.key_bytes(mint):
                    raise ValueError('metadata_pointer_mutable_or_external')
                if 19 not in entries: raise ValueError('pointed_metadata_missing')
            if 19 in entries:
                data=entries[19]
                if len(data)<80 or any(data[:32]) or data[32:64]!=vault_checks.key_bytes(mint):
                    raise ValueError('token_metadata_mutable_or_mismatched')
                pos=64
                def string():
                    nonlocal pos
                    if pos+4>len(data): raise ValueError('metadata_truncated')
                    size=struct.unpack_from('<I',data,pos)[0]; pos+=4
                    if size>4096 or pos+size>len(data): raise ValueError('metadata_string_invalid')
                    data[pos:pos+size].decode('utf-8'); pos+=size
                for _ in range(3): string()
                if pos+4>len(data): raise ValueError('metadata_truncated')
                count=struct.unpack_from('<I',data,pos)[0]; pos+=4
                if count>64: raise ValueError('metadata_fields_excessive')
                for _ in range(count*2): string()
                if pos!=len(data): raise ValueError('metadata_trailing_bytes')
        out['complete']=True
    except Exception as error:
        # Only fixed local messages are exposed; decode/RPC errors have generic codes.
        out['reject']=str(error) if type(error) is ValueError else 'extension_evidence_unavailable'
    return out
