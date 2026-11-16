# Bukti produksi MAIL AI Narrative Hunter v5.0

Tanggal: 16 November 2026. Waktu di bawah UTC (WIT = UTC+9).

- Upgrade repositori/bot lama: [PR12](https://github.com/Yono24-jpg/solana-telegram-screening/pull/12), merge `ded128d310cbc65843ecef7762924a19b2da01a6`.
- [Audit tanpa pengiriman](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43813502068): success. **202 tes Python +28 scheduler/Workers +28 web scanner lama; 0 gagal.** Pemeriksaan sumber publik:283 pool,140 hasil discovery narasi,0 CA manual,0 sinyal.
- [Produksi v5](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43813587121): success.323 pool,0 sinyal kandidat,30 catatan observasi baru. Laporan kesehatan Telegram **message_id408** diterima API pada05:58:04UTC /14:58:04WIT. `getMe` mengonfirmasi `@SolHawkHunter917Bot`, tujuan channel benar. Tombol ON/OFF dipertahankan; state durable `enabled=true` dan reservation kesehatan `sent` terverifikasi.
- [Validasi scheduler produksi](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43813587149): success, termasuk Wrangler dry-run.
- Cloudflare Worker yang sama diunggah05:57:59.480UTC. Deployment **79aa45c1441c4051958d577634ac8b15**. Kode yang dibaca kembali memuat prompt global multibahasa. Binding AI, secret GitHub, secret admin, SCHEDULER_ENABLED dan Durable Object tetap ada. Cron yang dibaca kembali **`*/5 * * * *`**; tidak membuat bot atau scheduler kedua.
- OIDC AI produksi `status=ok`; provider mengembalikan **`@cf/meta/llama-3.3-70b-instruct-sd`** (permintaan aliasfp8-fast). Nol entitas AI lolos validasi literal dua penerbit pada putaran ini; narasi berbasis sumber/rules tetap bekerja. Ini bukan bukti penggunaan GPT-6.

Tick Cloudflare versi baru diamati **06:01:00.770UTC /15:01:00.770WIT**, slot5982696: `recent_scanner_run`, run43813587121. Cron berjalan dan mencegah dispatch ganda setelah scan produksi barusan. Tick ini bukan klaim scan kedua telah dijalankan; waktu eksekusi Actions dapat bergeser.

## Hasil dan batas bukti

Produksi menolak119 pool karena MC,84 karena data pasar penting tidak lengkap,50 karena volume1h,32 karena umur,27 aktivitas lemah,6 likuiditas,4 harga terlambat/menurun,1 kenaikan24h ekstrem. Total323. Tidak ada kandidat mencapai gerbang keamanan akhir pada putaran ini; jalur keamanan Token-2022/insider/transaksi diuji dengan fixture adversarial offline, bukan dinyatakan lolos oleh token live.

Kondisi sumber **degraded**: sumber China tidak mengembalikan artikel terbaru dan Bluesky publik tidak dapat diakses. Lima locale lain dan sepuluh feed discovery pasar tersedia. Kekosongan data tidak diubah menjadi klaim aman/organik. Cakupan global adalah sampel, bukan seluruh media sosial. Tidak ada pengenalan isi gambar/video atau pemantauan seluruh foto profil influencer.

Enam skor terpisah tersedia; nilai sosial yang belum terukur tetap null. Memori dan evaluator5m/15m/1h/24h sudah terpasang, tetapi seluruh horizon v5 masih menunggu observasi pada run pertama. Replay tanpa informasi masa depan tidak membuktikan keuntungan; arsip historis sebelum lonjakan tujuh kasus tidak lengkap. Sembilan kartu riset/negatif tersimpan di `audit/case-studies-v5.json`; tidak menjadi whitelist atau instruksi melonggarkan keamanan.

Rincian kemampuan: [V5_GLOBAL_INTELLIGENCE.md](V5_GLOBAL_INTELLIGENCE.md). Bukti terstruktur: [audit/deployment-v5-20261116.json](audit/deployment-v5-20261116.json). Artefak lengkap setiap run dipertahankan14 hari melalui Actions.

**ALERT ONLY. Tidak ada auto trading, secret yang ditampilkan, atau sinyal kandidat buatan. Bukti keamanan dan skor tidak menjamin bebas rug pull.**
