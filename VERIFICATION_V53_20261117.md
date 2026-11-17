# MAIL AI Narrative Hunter v5.3 — verifikasi produksi selesai

17 November 2026. PR [#29](https://github.com/Yono24-jpg/solana-telegram-screening/pull/29) merged sebagai `4910f964413a074c1f46503e082a3171deb9059a`. **v5.3 berjalan di produksi dan 12 run diverifikasi selama 65,81 menit. Kualitas data tetap degraded; tidak ada klaim peningkatan kelengkapan menyeluruh atau target 90%.**

Upgrade v5.2 sebelumnya tidak diulang. Implementasi: [SMART_DISCOVERY_V53.md](SMART_DISCOVERY_V53.md). CI [44072982173](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44072982173) dan [44072972725](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44072972725) success. Semua 12 run produksi success dan masing-masing lulus **299 tes** (284 lama + 15 regresi baru). Tidak ada perubahan kode runtime selama jendela produksi ini.

## Jendela hasil

**17 November 2026, 20:20:24–21:26:13 WIT** (11:20:24–12:26:13 UTC). Run awal dipicu merge, run berikutnya mengikuti scheduler. Pemeriksaan benar-benar dilanjutkan sampai run kedua belas selesai.

| Ukuran | Hasil |
|---|---|
| Kelengkapan seluruh inventaris | **1.025/4.290 = 23,89%** |
| Rentang kelengkapan per run | 21,04–27,49% |
| Pool muda 1–60 menit, data lengkap | **203/1.579 = 12,86%** |
| Sampel tetap v5.2 | **11/30 = 36,67%** lengkap pada baseline |
| Sampel tetap, akhir v5.3 | **12/30 = 40,00%** lengkap; seluruh 30 identitas teramati pada setiap run |
| Rentang lengkap pada sampel tetap | 11–16 dari 30; peningkatan belum konsisten |
| Lead inisialisasi pool dari RPC | **4**; bukan kandidat aman atau alert |
| Pembacaan detail transaksi RPC | 28 percobaan; 36 cache hits tercatat antarputaran |
| Durasi pipeline | 70,9–80,0 detik; median **77,3 detik**, anggaran scan 200 detik |
| Request jaringan Gecko | **36**, maksimal 3 per run; tidak ditemukan HTTP 429 dalam jendela |
| Antrean durable akhir | **300** identitas; cache 11 signature, 6 selesai; cohort 30 |
| Alert token | **0**; belum ada kandidat melewati seluruh gerbang |
| Telegram produksi | Laporan kesehatan terkirim, **message_id 415** |

Observasi dapat berulang antarputaran. Inventaris mencakup identitas antrean tanpa snapshot pasar lengkap terbaru; identitas tersebut tetap tidak lengkap dan tidak dihitung sebagai harga/volume/likuiditas teramati. Cache identitas tidak memasukkan angka pasar lama. Angka 756 perbaikan parsial dan 104 transisi menjadi lengkap pada perbandingan pre/post recovery dapat berulang; keduanya bukan jumlah token unik yang pulih permanen. Ringkasan source_mix bersifat deskriptif, bukan bukti freshness atau dasar keamanan.

## Investigasi penurunan 41,23% → 31,64%

Angka 41,23% (94/228) dan 31,64% (1.254/3.963 observasi) memakai kumpulan pool dan waktu berbeda. Sampel pasar berubah serta lebih banyak pool parsial dipertahankan, sehingga rasio itu tidak membuktikan regresi algoritme pada pool identik. Log v5.2 menunjukkan respons Dex yang berhasil tetapi tetap parsial dan gangguan Gecko (12 HTTP 429, 35 backoff pada jendela verifikasi sebelumnya). Kekurangan perubahan harga lima menit, likuiditas dan volume tetap dominan.

Pada v5.3 rasio inventaris turun lebih lanjut ke 23,89%; **tidak ada bukti bahwa kelengkapan seluruh inventaris sudah membaik**. Inventaris kini juga mempertahankan lead/identitas antrean yang belum memiliki data pasar terbaru. Denominator tidak dipangkas dan field kosong tidak diganti nol, FDV, atau agregat token. Run akhir masih kekurangan priceChange.m5 pada 265 pool, volume.m5 pada 263, liquidity.usd pada 193, volume.h1 pada 148, marketCap pada 58 dan priceUsd pada 31. Satu pool dapat kekurangan beberapa field.

## Pembandingan pool yang sama

Baseline asli diambil dari arsip v5.2 [run 44070114701](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44070114701), artifact 14321738237: 30 observasi pertama, 11 lengkap, sembilan berumur 1–60 menit saat baseline. Ini sampel diagnostik nonacak, bukan gambaran seluruh pasar. Identitas/missing-field awal ada di [audit/cohort-v52-to-v53.json](audit/cohort-v52-to-v53.json).

v5.3 melakukan request ulang untuk identitas mint/pair yang sama, maksimal dua batch per putaran. Data finansial baseline tidak dipakai sebagai pasar terbaru atau bukti keamanan. Seluruh 30 identitas ditemukan pada 12 run; denominator tetap 30. Hasil akhir naik satu pool lengkap, tetapi waktu, umur pool, dan kondisi pasar berubah sehingga **ini perbandingan temporal, bukan eksperimen A/B kausal**.

Artifact terakhir 14327084185 di [run 44083079863](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44083079863) diunduh dan diperiksa: tepat 30 mint/pair sama dengan baseline, missing-field awal identik, jumlah lengkap akhir 12. SHA256 ZIP: `e805d1a29d33eaab1e756b6162d8fed2254a4881dfa0e927272ef9dc8dd5556b`. Laporan same-pool-v53.json juga membandingkan snapshot pre/post recovery pada identitas yang sama; pada run akhir 76→83 lengkap dari 365 entri pre-recovery, 7 pulih dan 0 regresi. Pool tambahan setelah tahap ini dilaporkan terpisah dalam total inventaris akhir.

## SMART DISCOVERY, API dan keamanan

- Parser RPC mainnet menerima transaksi finalized yang sukses, signature yang cocok, program CPMM resmi, discriminator initialize dan posisi akun/fee receiver yang sesuai sumber resmi. Maksimal satu pembacaan daftar signature dan enam detail transaksi per run, sub-anggaran waktu 18 detik. Empat lead terdeteksi, tetapi tidak diberikan angka USD, rolling volume, market cap, narasi atau status aman dari transaksi itu. Beberapa detail transaksi tetap unavailable; percobaan gagal tidak dianggap penemuan. Cakupan RPC ini khusus CPMM, bukan seluruh pool Solana. Feed dan narasi dinamis seluruh kategori tetap berjalan.
- Antrean mengutamakan pool muda, maksimum 80 pemeriksaan ulang per tahap. Setelah stabil, delapan run terakhir memakai seluruh 80 slot untuk pool berumur paling lama 60 menit. Pool di bawah satu menit boleh masuk antrean; gerbang alert minimum umur 60 detik tetap berlaku. Cache transaksi menghindari pembacaan ulang; cache identitas tidak menjadi sumber angka pasar.
- Gecko hanya membaca satu halaman pool terbaru, tanpa halaman trending, dengan batas 3 request/run, pacing 12 detik dan backoff 429 persisten. Hidrasi: 24 batch Gecko sukses dan 24 skip karena batas lokal; discovery: satu request per run. Tidak ditemukan 429 pada 36 request. Ini pengamatan pada jendela tersebut, bukan jaminan layanan tidak akan membatasi lagi.
- Helius: **52 percobaan** dalam jendela; ledger akhir **353/600.000** estimasi kredit 31 hari dan 185/20.000 hari berjalan. Birdeye: **18 CU** direservasi dalam jendela; ledger akhir **546/24.000** estimasi CU 31 hari. Ledger mencakup percobaan gagal dan hanya aplikasi ini; bukan pembacaan tagihan akun atau aplikasi lain. Paket berbayar, DAS/enhanced parsing berbayar, dan akses X tidak diaktifkan.
- Semua run ALERT ONLY, X reads false, scanner ON. Bot lama dan ON/OFF dipertahankan. Pengamatan momentum, volume, likuiditas dan narasi tetap melewati aturan pasar lama; data kosong tidak dilonggarkan.
- Internal NARRATIVE WATCH/antrean tidak mengotorisasi pengiriman. VERIFIED ALERT tetap memerlukan audit keamanan lengkap dan quote akhir segar. security_checks kosong pada jendela ini karena tidak ada kandidat melewati gerbang awal; tes keamanan lulus tetapi **audit akhir token produksi nyata belum teruji oleh sampel ini**.

## Cron dan Telegram

Cloudflare mail-solana-scheduler tetap `*/5 * * * *`, versi aff5f5f0-79e3-480f-86fb-06e66928dd0c pada 100% deployment. Log 11:19–12:29 UTC memuat 14 tick: **11 dispatch HTTP 204**, satu scanner_already_active saat run merge, dan dua recent_scanner_run (20:51 dan 21:21 WIT) karena cooldown anti-duplikasi. Dua jeda 10 menit merupakan skip cooldown; cron tetap lima menit, tetapi ini tidak menjamin eksekusi scan baru tepat setiap lima menit. Tidak ditemukan kegagalan dispatch pada jendela tersebut.

Setiap run membuktikan getMe/getChat/getUpdates untuk @SolHawkHunter917Bot dan channel tujuan. [Run 44079192738](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44079192738) mengirim laporan kesehatan 6 jam pada **21:02:25 WIT**, sendMessage berhasil dan message_id **415** diverifikasi. Ini pesan kesehatan produksi, bukan sinyal palsu atau alert token. Tidak dikirim tes duplikat.

State main terakhir diperiksa langsung dari origin/main: last_scan 44083079863, versi 5.3, enabled true, queue 300, signature cache 11, cohort 30, X false. Bot lama, kode transaksi dan secret tidak diubah.

## Bukti per putaran

Waktu WIT, 17 November 2026. Semua run success, 299 tes lulus, 0 alert token.

| Run | Waktu WIT | Lengkap/total | Muda lengkap/total | Sampel tetap lengkap | Lead RPC | Durasi detik |
|---|---|---:|---:|---:|---:|---:|
| [44073079522](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44073079522) | 20:20:24 | 86/314 (27.39%) | 13/77 | 16/30 | 2 | 80.0 |
| [44073967172](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44073967172) | 20:26:10 | 81/338 (23.96%) | 14/96 | 13/30 | 0 | 77.9 |
| [44074711081](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44074711081) | 20:31:16 | 87/358 (24.3%) | 20/118 | 12/30 | 1 | 78.7 |
| [44075481325](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44075481325) | 20:36:14 | 91/331 (27.49%) | 15/80 | 12/30 | 0 | 76.9 |
| [44076208847](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44076208847) | 20:41:15 | 89/386 (23.06%) | 17/158 | 11/30 | 0 | 77.2 |
| [44076958552](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44076958552) | 20:46:20 | 82/383 (21.41%) | 15/156 | 12/30 | 0 | 77.8 |
| [44078447400](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44078447400) | 20:56:11 | 82/364 (22.53%) | 13/159 | 12/30 | 0 | 77.4 |
| [44079192738](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44079192738) | 21:01:18 | 92/355 (25.92%) | 19/151 | 12/30 | 1 | 70.9 |
| [44079972732](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44079972732) | 21:06:11 | 83/317 (26.18%) | 22/145 | 11/30 | 0 | 76.5 |
| [44080749387](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44080749387) | 21:11:11 | 80/343 (23.32%) | 19/148 | 12/30 | 0 | 77.4 |
| [44081529325](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44081529325) | 21:16:14 | 87/397 (21.91%) | 18/145 | 14/30 | 0 | 77.0 |
| [44083079863](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/44083079863) | 21:26:13 | 85/404 (21.04%) | 18/146 | 12/30 | 0 | 76.5 |

[Bukti terstruktur lengkap](audit/verification-v53-20261117.json). Status akhir: implementasi/deployment/verifikasi operasional selesai; kelengkapan pasar masih degraded, tanpa klaim 90% atau jaminan token aman.
