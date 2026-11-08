"""One requested connection test; sends no market signal and never retries sendMessage."""
import json
import os
from pathlib import Path
import re
import time
import bot


def main():
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        if not os.environ.get(key): raise RuntimeError('missing_'+key)
    bot.REQUEST_DEADLINE = time.monotonic()+60
    identity = bot.tg('getMe')
    username = identity.get('username', '')
    if not identity.get('is_bot') or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        raise RuntimeError('invalid_bot_identity')
    chat = bot.tg('getChat', chat_id=os.environ['TELEGRAM_CHAT_ID'])
    if chat.get('type') not in ('channel', 'group', 'supergroup') or not isinstance(chat.get('id'), int):
        raise RuntimeError('invalid_destination')
    print('TELEGRAM_BOT username=@'+username)
    public_handle = chat.get('username')
    if isinstance(public_handle, str) and re.fullmatch(r'[A-Za-z0-9_]{5,32}', public_handle):
        print('TELEGRAM_DESTINATION username=@'+public_handle)
    # A public handle is printed; secret Chat ID and token are never printed or saved.
    msg = bot.tg('sendMessage', chat_id=chat['id'],
                text='✅ TES KONEKSI SCANNER SOLANA\nBot: @'+username+'\nRepositori: Yono24-jpg/solana-telegram-screening\nUpgrade EARLY WATCH + STRONG SIGNAL. Ini pesan tes, bukan sinyal token.\nALERT ONLY • Tanpa trading otomatis.',
                reply_markup=bot.KEYBOARD, disable_web_page_preview=True)
    if not isinstance(msg.get('message_id'), int) or msg['message_id'] <= 0 or msg.get('chat', {}).get('id') != chat['id']:
        raise RuntimeError('send_not_verified')
    print('TELEGRAM_TEST_OK message_id='+str(msg['message_id']))
    Path('reports').mkdir(exist_ok=True)
    Path('reports/telegram-test.json').write_text(json.dumps({'ok':True, 'bot_username':username,
            'message_id':msg['message_id'], 'destination_type':chat['type']}, indent=2))


if __name__ == '__main__':
    try: main()
    except Exception:
        print('TELEGRAM_TEST_FAILED: no automatic resend; check sanitized API logs')
        raise SystemExit(1)
