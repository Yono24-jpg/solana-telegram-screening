# Verifikasi ulang MAIL Hunter v5 — 16 November 2026, 16:10 WIT

Permintaan upgrade diperiksa terhadap kode dan produksi yang sudah ada. Tidak dibuat bot baru dan tidak dilakukan deployment ulang tanpa perubahan kode.

## Bukti terkini

- Main diperiksa pada commit `448710b5ff1f54ea417c6a80e836d7826549de9b`; implementasi v5 dan perbaikan evaluator sudah tergabung melalui PR12/PR13.
- Pengujian ulang lokal: 213 Python + 30 scheduler/Workers + 28 legacy web = **271 lulus, 0 gagal**. Wrangler dry-run berhasil dengan binding Durable Object dan AI.
- Cloudflare GET deployments membuktikan deployment aktif `0468af17-1ae3-4e7b-9453-e3baf4fa63c9`, versi `aff5f5f0-79e3-480f-86fb-06e66928dd0c`, trafik 100%, diunggah 15:56:38 WIT. ID versi berbeda dari ID deployment.
- Cron dibaca kembali `*/5 * * * *`, enabled/configured true. Read-back kode memuat prompt ANY language dan `Date.parse(run.created_at || run.run_started_at)`.
- Telemetry 16:01:00 WIT: recent_scanner_run (mencegah scan ganda); 16:06:02 WIT: dispatch_accepted, HTTP204, versi aktif tersebut.
- [Produksi 43821389797](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43821389797): success. 310 pool, 0 sinyal. Penolakan: market cap130, data pasar kosong60, umur53, volume1h36, aktivitas24, likuiditas5, harga1, percepatan viral belum terbukti1. Total310; belum ada kandidat mencapai gerbang keamanan akhir.
- Log run tersebut mengonfirmasi getMe @SolHawkHunter917Bot, getChat channel benar, getUpdates berhasil, STATE_PERSIST_OK. Scanner enabled=true. ON/OFF dipertahankan dan diuji regresi; tidak mengubah state ON/OFF produksi untuk pengujian.
- [Log kesehatan awal](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43813587121): TELEGRAM_HEALTH_OK message_id408 pada14:58:04 WIT. Durable reservation sent; produksi terkini not_due. Tidak mengirim ulang pesan uji.
- Model aktual tercatat `@cf/meta/llama-3.3-70b-instruct-sd`, status ok, Workers AI. Bukan bukti GPT-6; bukan klaim model terbaik secara universal.
- Memori produksi:5m observed16/missed131;15m observed25/missed113;1h observed60/missed0;24h belum ada. Batch produksi memulihkan33/33 quote. Harga terlewat tidak diisi dari masa depan.
- Audit publik read-only tambahan selesai:249 pool,0 sinyal, health degraded. Tidak mendapat token Telegram/OIDC dan tidak menyimpan perubahan ke produksi. Memakai cache berita tersimpan yang masih valid sehingga bukan bukti seluruh sumber baru diambil ulang. Hasil tetap menunjukkan Bluesky unavailable dan beberapa kueri locale tanpa artikel baru.

## Kemampuan dan batas

Tiga mode, enam skor, gerbang pasar dan keamanan wajib, parser Token-2022 konservatif, sumber alternatif, reservasi pengiriman, memori terbatas, evaluator dan replay kronologis tersedia. Rincian: [V5_GLOBAL_INTELLIGENCE.md](V5_GLOBAL_INTELLIGENCE.md).

Cakupan global merupakan sampel; tidak ada analisis isi gambar/video atau pemantauan seluruh influencer. X nonaktif tanpa akses resmi. Boost berbayar dapat diamati, organik tetap unknown. Bukti keamanan penting tidak tersedia menyebabkan penolakan. Pemeriksaan wallet/insider/wash dan kemampuan jual terbatas pada snapshot/transaksi teramati; bukan jaminan keamanan masa depan. Kasus GTA, MIHAO, Anthropig, PNUT, GOAT, WIF, CHILLGUY dan negatif disimpan sebagai kartu riset; bukan backtest profit historis tervalidasi atau pelatihan bobot model.

ALERT ONLY; bot lama utuh, secret tidak ditampilkan, tidak ada sinyal buatan atau auto trading.
