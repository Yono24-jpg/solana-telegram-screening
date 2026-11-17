# MAIL Hunter v5.2 — pemeriksaan ulang produksi

17 November 2026. Verifikasi operasional selesai; target data 90% belum tercapai. Ini pemeriksaan ulang log produksi yang sudah berjalan, bukan klaim menunggu 65 menit baru dalam sesi ini.

PR #26 sudah merged (`da39af2`), perbaikan #27 juga merged (`ee93685`). Upgrade dan deployment tidak diulang. Log terbaru menegaskan versi 5.2 berjalan di produksi.

## Hasil

13 putaran unik pada 18:56:10–20:01:20 WIT, rentang 65,17 menit; semua Actions success dan masing-masing 284 tes lulus. Scan 29,2–56,9 detik, median 38,0 detik.

Kelengkapan gabungan 1.254/3.963 observasi pool = **31,64%**; token muda 1–60 menit: 175/1.248 = **14,02%**. Pool dapat berulang antarputaran. Terakhir 76/328 = 23,17%, muda 8/83. Health seluruh putaran degraded; pipeline operational.

Baseline historis 41,23%; sebelum upgrade 48,59%; verifikasi awal pascaperbaikan 36,39%; kini 31,64%. Tidak ada bukti peningkatan konsisten. Sampel pasar berubah sehingga angka ini bukan eksperimen kausal pool identik.

## Kendala data

Dex pair fallback sukses 52/52 batch; respons tetap parsial. Gecko hydration: 12 HTTP 429, 35 provider_backoff dan 5 batch sukses, total 100 baris. Hidrasi memberikan 55 perbaikan parsial tetapi tidak memulihkan satu pool menjadi lengkap dalam tahap ini. Angka pemulihan tahap hidrasi berbeda dari kelengkapan seluruh pipeline. Terakhir field kurang: priceChange.m5 196, liquidity.usd 156, volume.m5 144, volume.h1 83, marketCap 13, priceUsd 5, pairCreatedAt 4. Satu pool bisa kekurangan beberapa field.

Kode rotasi/deadline/identitas pool diperiksa. Perbaikan statistik batch dan timestamp retry sudah tersedia melalui #27. Tidak ditemukan perubahan parser tambahan yang terbukti menyelesaikan kekurangan respons sumber. Backoff dipertahankan; data agregat token tidak dijadikan metrik pool dan data kosong tidak diisi angka rekaan. Karena itu target 90% tetap tidak lulus, bukan dinyatakan selesai secara kualitas data.

## Kuota, keamanan, cron dan Telegram

- Helius 13 percobaan standard RPC dalam jendela; ledger terakhir 298/600.000 estimasi kredit 31 hari.
- Birdeye 18 CU direservasi dalam jendela; ledger terakhir 528/24.000 estimasi CU 31 hari. Ini ledger aplikasi, bukan tagihan akun atau penggunaan aplikasi lain. Batas gratis tidak dinaikkan dan paket tidak dibeli.
- Semua putaran ALERT ONLY dan X reads false. Bot lama tetap; tidak ada perubahan kode runtime pada pemeriksaan ulang ini.
- Tidak ada kandidat lolos, 0 alert, security_checks kosong. Tes gerbang keamanan lulus, tetapi jalur audit akhir token nyata tidak terlatih oleh sampel produksi ini; tidak ada klaim token aman.
- Cloudflare mail-solana-scheduler cron tetap `*/5 * * * *`, versi aff5f5f0-79e3-480f-86fb-06e66928dd0c pada 100% traffic. Dalam 09:54–11:04 UTC: 14 tick, 13 HTTP 204, 1 recent_scanner_run. Slot 19:51 WIT sengaja dilewati karena run sebelumnya masih berada dalam cooldown 295 detik. Tidak ditemukan kegagalan dispatch pada jendela ini.
- getMe/getChat/getUpdates sukses pada 13 putaran untuk @SolHawkHunter917Bot dan channel tujuan. Tes sendMessage sebelumnya diperiksa langsung dari [log run 43994986330](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43994986330): berhasil message_id 413. Tidak mengirim tes duplikat. Alert kandidat nyata belum teruji karena tidak ada kandidat memenuhi syarat.

## Bukti per putaran

Waktu WIT, 17 November 2026.

| Run | Waktu | Lengkap/total | Cakupan | Muda lengkap/total | Scan detik |
|---|---|---:|---:|---:|---:|
| [44060104648](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44060104648) | 18:56:10 | 103/319 | 32.29% | 10/93 | 35.8 |
| [44060865607](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44060865607) | 19:01:21 | 115/309 | 37.22% | 16/96 | 36.8 |
| [44061644842](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44061644842) | 19:06:13 | 107/306 | 34.97% | 20/90 | 38.6 |
| [44062430223](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44062430223) | 19:11:19 | 109/319 | 34.17% | 16/98 | 56.9 |
| [44063222585](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44063222585) | 19:16:11 | 95/321 | 29.6% | 13/102 | 37.7 |
| [44064001834](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44064001834) | 19:21:19 | 84/307 | 27.36% | 9/89 | 48.5 |
| [44064786416](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44064786416) | 19:26:13 | 91/307 | 29.64% | 12/99 | 38.0 |
| [44065541853](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44065541853) | 19:31:11 | 109/311 | 35.05% | 26/103 | 34.7 |
| [44066321495](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44066321495) | 19:36:11 | 98/275 | 35.64% | 13/99 | 38.7 |
| [44067083258](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44067083258) | 19:41:14 | 89/282 | 31.56% | 9/107 | 38.5 |
| [44067849489](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44067849489) | 19:46:12 | 94/271 | 34.69% | 14/85 | 36.4 |
| [44069359823](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44069359823) | 19:56:11 | 84/308 | 27.27% | 9/104 | 39.6 |
| [44070114701](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44070114701) | 20:01:20 | 76/328 | 23.17% | 8/83 | 29.2 |

[Bukti terstruktur](audit/reverification-v52-20261117-evening.json). Laporan awal tetap tersedia di VERIFICATION_V52_20261117.md.
