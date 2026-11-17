# MAIL Hunter v5.2 — Verifikasi produksi 17 November 2026

Verifikasi selesai; target kelengkapan data 90% **belum tercapai**. Scanner beroperasi dengan kesehatan data `degraded`.

PR #26 sudah merge sebelumnya, commit `da39af2ec667b57821d11343cbef23e81d03fa6b`; upgrade tidak diulang. Perbaikan terarah PR #27, commit `ee936852a4f98759d38696b22841e2ed1b0d1de4`, memperbaiki akumulasi statistik fallback dan pencatatan retry saat deadline. Tidak mengubah gerbang keamanan, batas API, atau syarat field pasar.

## Jendela bukti

**13 run unik setelah perbaikan, 63.85 menit**, dari 2026-11-17T01:12:19.994Z hingga 2026-11-17T02:16:10.704Z. Dalam WIT: 17 November 2026, 10:12:19–11:16:10. Semua run dan penyimpanan state berhasil; 284 tes Python lulus pada setiap run. Total termasuk dua run v5.2 sebelum perbaikan: 15 run selama 73,57 menit.

| Ukuran | Hasil |
|---|---|
| Kelengkapan gabungan | 1659/4559 observasi pool = 36.39% |
| Rentang kelengkapan per run | 27.36–44.66% |
| Putaran terakhir | 126/339 lengkap = 37,17%; 213 belum lengkap |
| Pool muda 1–60 menit | 292/937 observasi lengkap = 31.16%; terakhir 26/89 |
| Durasi scan | 12.0–64.6 detik; median 37.1 detik; anggaran 200 detik |
| Kandidat lolos / alert token | 0 / 0 |
| Tes pengiriman Telegram | Berhasil, message_id 413 |
| Helius selama jendela | 13 percobaan standard RPC; ledger terakhir 196/600.000 estimasi kredit 31 hari |
| Birdeye selama jendela | 51 CU direservasi; ledger terakhir 429/24.000 estimasi CU 31 hari |

Total merupakan **observasi pool yang dapat berulang antarputaran**, bukan jumlah token unik. Kelengkapan sembilan field pasar bukan bukti token aman atau siap alert; gerbang harga lanjutan dan keamanan tetap wajib.

## Perbandingan sebelum dan sesudah

Baseline historis: 94/228 = 41,23%. Run v5.1 tepat sebelum upgrade [43992246288](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43992246288): 138/284 = 48,59%, durasi sekitar 36,4 detik. Hasil pascaperbaikan 36.39% tidak menunjukkan peningkatan kelengkapan yang konsisten. Sampel pasar berubah, sehingga ini bukan eksperimen dengan pool identik dan tidak membuktikan dampak kausal upgrade.

Token muda tercatat pada semua run pascaperbaikan; data lengkapnya tetap terbatas. Waktu menuju hasil discovery tersedia dalam bukti JSON. Polling lima menit tidak mengukur latency pengindeksan penyedia dan tidak menjamin penemuan instan.

## Kendala dan perbaikan

1. Statistik fallback sebelumnya tertimpa tiap batch. Kini `attempts`, `successes`, `total_rows`, dan `status_counts` mencatat semua batch tanpa menghilangkan field kompatibilitas.
2. Timestamp retry sebelumnya diberikan kepada semua kandidat sebelum request berjalan. Kini hanya batch yang benar-benar dipanggil dicatat dan pekerjaan berhenti pada deadline yang sama.
3. Lima tes baru mencakup batch campuran sukses/gagal, deadline, serta retensi dan penggabungan watchlist parsial token muda. PR #27 CI [43993641151](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43993641151) lulus 284 tes.
4. Dex pair/token fallback merespons, tetapi sering tetap tidak menyediakan field yang diperlukan. Gecko pernah memulihkan snapshot parsial, lalu berulang kali HTTP 429/backoff. Backoff dan pacing dipertahankan.
5. Kekurangan akhir terbesar: `priceChange.m5=170`, `liquidity.usd=85`, `marketCap=31`, `priceUsd=7`. Satu pool bisa kekurangan beberapa field, sehingga angka ini tidak dijumlahkan sebagai jumlah pool.
6. Birdeye dipakai secara terbatas untuk valuasi circulating yang memenuhi syarat. Data agregat token tidak disalin menjadi volume/likuiditas/harga pool. RPC tidak dipakai mengarang metrik harga lima menit. CoinGecko memverifikasi satu circulating market cap pada run 02:11 UTC.
7. Tidak ditemukan perbaikan parser tambahan yang terbukti bisa membawa cakupan ke 90% dari respons sumber yang tersedia. Tidak mengisi data kosong dengan nol, memakai FDV sebagai market cap, memangkas denominator, atau melonggarkan keamanan.

## Keamanan, cron, dan Telegram

- Mode produksi terakhir `ALERT ONLY`, scanner ON, `x_reads_enabled=false`. Bot lama dan tombol ON/OFF tetap.
- Semua 13 run pascaperbaikan menyelesaikan 284 tes. Tidak ada kandidat yang lolos gerbang awal; `security_checks=[]` pada jendela ini. Karena itu tidak ada klaim token produksi telah lolos audit keamanan akhir.
- Ledger dan anti-duplikasi tetap; tidak ada kode transaksi atau wallet baru, pembelian paket, atau perubahan akses.
- Cloudflare `mail-solana-scheduler` mempertahankan cron `*/5 * * * *`, versi `aff5f5f0-79e3-480f-86fb-06e66928dd0c`. Bukti memuat 13 dispatch HTTP 204 dan dua slot `recent_scanner_run` sesudah run merge; tidak ditemukan kegagalan tick dalam jendela yang dikueri.
- Setiap run mengenali `@SolHawkHunter917Bot` dan tujuan channel. Pengiriman nyata diuji sekali melalui pemeriksaan Telegram yang sudah ada pada branch diagnostik, [run 43994986330](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43994986330), berhasil `sendMessage`, `message_id=413`. Ini pesan tes koneksi berlabel, bukan sinyal token; tidak dihitung sebagai alert.
- Estimasi kuota berasal dari ledger scanner, mencakup percobaan gagal. Bukan pembacaan tagihan akun dan tidak mencakup aplikasi lain. Tidak ada paket berbayar yang dibeli atau diaktifkan.

## Bukti setiap putaran

Waktu UTC, 17 November 2026. Tambahkan sembilan jam untuk WIT.

| GitHub run | Waktu scan UTC | Lengkap/total | Cakupan | Muda lengkap/total | Durasi detik | Alert |
|---|---|---:|---:|---:|---:|---:|
| [43993734373](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43993734373) | 01:12:19 | 91/254 | 35.83% | 10/25 | 19.3 | 0 |
| [43994891166](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43994891166) | 01:21:11 | 163/365 | 44.66% | 27/61 | 64.6 | 0 |
| [43995540775](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43995540775) | 01:26:38 | 159/395 | 40.25% | 33/80 | 50.1 | 0 |
| [43996171702](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43996171702) | 01:31:12 | 145/403 | 35.98% | 31/86 | 39.3 | 0 |
| [43996800116](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43996800116) | 01:36:19 | 136/386 | 35.23% | 21/86 | 35.8 | 0 |
| [43997429171](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43997429171) | 01:41:19 | 98/303 | 32.34% | 10/34 | 12.0 | 0 |
| [43998048795](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43998048795) | 01:46:17 | 138/385 | 35.84% | 16/85 | 34.9 | 0 |
| [43998651419](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43998651419) | 01:51:11 | 131/381 | 34.38% | 27/96 | 36.8 | 0 |
| [43999249606](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43999249606) | 01:56:15 | 81/296 | 27.36% | 2/36 | 12.0 | 0 |
| [43999849027](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43999849027) | 02:01:09 | 128/368 | 34.78% | 24/90 | 42.7 | 0 |
| [44000466998](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44000466998) | 02:06:20 | 137/363 | 37.74% | 41/98 | 37.9 | 0 |
| [44001084235](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44001084235) | 02:11:11 | 126/321 | 39.25% | 24/71 | 37.8 | 0 |
| [44001698406](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44001698406) | 02:16:10 | 126/339 | 37.17% | 26/89 | 37.1 | 0 |

Bukti terstruktur: [audit/verification-v52-20261117.json](audit/verification-v52-20261117.json).
