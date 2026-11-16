# Uji token nyata MAIL AI Narrative Hunter v3.0 — 16 November 2026

**Hasil: keempat CA berhasil diambil pada audit akhir; tidak ada token yang memenuhi seluruh syarat alert.**

Pengamatan per token: 16-11-2026 13:53:50 WIT sampai 16-11-2026 13:54:59 WIT. Angka antar penyedia dan antar waktu dapat berbeda; tabel pasar menggunakan satu snapshot utuh yang dipilih scanner.

[Audit live berhasil](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43806788814) · [Perubahan PR #11](https://github.com/Yono24-jpg/solana-telegram-screening/pull/11)

## Identitas dan cakupan pengujian

CA di bawah cocok dengan token/pool publik yang diperiksa dan akun mint on-chain. Nama yang sama dipakai banyak token. Tidak ada bukti dalam audit ini bahwa token diterbitkan atau disahkan Anthropic, Rockstar Games, atau pengelola FiveM.

Rockstar utama yang diuji adalah mint **9HFUE…pump**, pool rockstar/TTWO. Mint senama **4cRMc…7DEu** yang muncul dalam pencarian awal merupakan token berbeda; jangan mencampur angkanya. FiveM **8dbLr…pump** juga berbeda dari **2YxbK…pump** yang diuji.

## Perbaikan dan batas data

- Discovery umum menambah dua halaman trending, pencarian nama narasi kanonis dan alias terbatas (maksimal 12 kueri), serta mempertahankan snapshot yang lebih lengkap ketika hasil pencarian berikutnya tidak lengkap.
- Pool yang sudah terlihat tetapi datanya kurang lengkap dicoba ulang melalui batch pasangan dan GeckoTerminal. Kelengkapan v3 mencakup volume 1 jam dan market cap yang benar-benar dilaporkan. FDV tidak dijadikan market cap. Metrik dua snapshot tidak dijahit menjadi bukti lengkap palsu.
- Empat CA permintaan pengguna juga dimasukkan ke **daftar retrieval CA eksplisit**, bukan daftar token aman. Entri berhenti digunakan ketika pool mencapai 24 jam; semua gerbang tetap berlaku. Klaim "keempat ditemukan" pada audit akhir mencakup jalur CA terarah ini, bukan jaminan discovery umum menemukan semua token.
- Pada putaran ini 40 pool tidak lengkap dicoba ulang; 0 memperoleh snapshot v3 lengkap. Kekosongan yang tetap ada tidak diisi dengan angka buatan. Anthropic Inu tetap tidak memiliki satu snapshot yang sekaligus lengkap untuk MC dan perubahan 5m.
- Semua standar keamanan, batas pasar, filter anti-mengejar harga, dan penolakan Token-2022 v3 tetap sama. Pemeriksaan program yang tidak didukung dibuat lebih awal agar tidak menghabiskan jatah data publik.
- Workflow audit hanya memiliki akses repositori baca dan RPC. Tidak menerima kredensial Telegram atau kunci wallet, tidak menulis state produksi, dan tidak mengirim transaksi/alert.

## Hasil per token

### Anthropic Inu

CA: `GgDHtSGcXn5YrADnpsQSVHFAa5xLwVEuD7FWeRgvpump`

[DexScreener](https://dexscreener.com/solana/96RoBEefW9fgNRfjbd7LnFnNGxmpvDh1wkpKhFbX4QwT) · [Solscan mint](https://solscan.io/token/GgDHtSGcXn5YrADnpsQSVHFAa5xLwVEuD7FWeRgvpump)

Waktu: 16-11-2026 13:53:50 WIT. Ditemukan pada audit akhir: True; retrieval CA eksplisit: True.

| Gerbang pasar | Nilai | Syarat | Hasil |
|---|---:|---|---|
| Umur pool | 5.73 jam | 1 menit–24 jam | Lolos |
| Prioritas awal | Tidak | 1–60 menit | Di luar prioritas; masih boleh diperiksa |
| Market cap | $tidak tersedia | $20.000–$500.000 | Tidak terverifikasi |
| Likuiditas | $1,462.90 | >= $10.000 | Ditolak |
| Volume 1 jam | $0.16 | >= $5.000 | Ditolak |
| BUY/SELL 5m | 0.0/0.0 | >= 1,5× | Ditolak |
| Rasio BUY/SELL | 0.00 | >= 1,5× | Ditolak |
| Volume 5m | $0.00 | >= $1.500 | Ditolak / tidak terverifikasi |
| BUY 5m | 0.0 | >= 12 | Ditolak |
| LP / MC | tidak tersedia | >= 8% | Tidak terverifikasi / ditolak |
| Perubahan harga 5m | 0.00% | 0%–25% | Lolos |
| Perubahan harga 1h | 0.00% | -15%–80% | Lolos |
| Perubahan harga 24h | -98.69% | <= +200% | Lolos |

Narasi: **95/100**, topik Anthropic. Penolakan narasi: `None`. Skor momentum tidak diteruskan ketika gerbang awal menolak; kode: `liquidity`.

- Sumber narasi: [Crypto Briefing](https://news.google.com/rss/articles/CBMioAFBVV95cUxOemJiejJ6X1h6blBrVnJsX0t2ZnlCblk0VEVaV19rWW1mMndaQjVHeVg4UkxFNUFtUUp6ZFJxX0otWEZxTFdmU3dzUUY2RGJDb2V1VmtvTHYxWU9ZVVFpUkRmUUUxQ1VlVmZMNl91cVZuZ0VPWGhMOHFXUGlIN3QtR29xTW1ZRVBwTjlTVGJ0UWctTmJtelFFZ3NBbW9GTWhR?oc=5) — Amazon, Microsoft, OpenAI, Anthropic to be named AI ‘national champions’: WSJ - Crypto Briefing (16-11-2026 13:06:42 WIT).
- Sumber narasi: [Crypto Briefing](https://news.google.com/rss/articles/CBMipAFBVV95cUxPZFdKOG5tbVJQbG43cVFoU24zS2JzMF9hVlh6MFBRZDJ1bzQ4QnAtdFVlQ0pZNHVIOVdPaXUxaUVQeDltTEU4QnNLcGpLdmNhdkR6R3A4a0xRaFBUYU05NTlMUjVtMnJqdU5qS2NzcUlQZGViSVZDZExyUE91YTJEVHB2b3dtWGhiWmN2VFBzV3ZEUm5QcjdqTFpkdDZfTXhQaWpoYg?oc=5) — Alibaba unveils Qwen3.8-Max AI model, challenging US rivals Anthropic, OpenAI - Crypto Briefing (16-11-2026 11:38:11 WIT).

| Gerbang keamanan | Bukti | Keputusan |
|---|---|---|
| Mint authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Freeze authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Program token | Token-2022 | **Ditolak: v3 belum mendukung seluruh pemeriksaannya** |
| LP kandidat (RugCheck) | 100.00% dilaporkan terkunci; nilai $1,473.43 | Ditolak / tidak lengkap; bukan verifikasi independen semua locker |
| Konsentrasi akun token top 10 | 0.62% setelah vault yang terbukti dikecualikan | Lolos <=30% |
| Pemilik terbesar pada sampel | 0.25% | Lolos <=15% |
| Developer | Kepemilikan 0.00%; 0 transaksi dalam jendela terakhir yang diperiksa; batas riwayat 5 | Tidak ditemukan outflow token pada sampel; bukan pembuktian semua wallet developer |
| Insider / jaringan wallet | Data jaringan null/tidak lengkap meskipun counter bernilai 0 | Tidak terverifikasi; blokir |
| Keragaman / wash heuristic | unavailable; pembeli unik None; tanda risiko: tidak ada pada sampel yang tersedia | Tidak lengkap / pola mencurigakan; blokir |
| Jual dan pola bundle | insufficient_sell_or_buyer_sample | Belum terverifikasi; blokir |
| Risiko RugCheck | Low Liquidity (danger) | Flag kosong bukan bukti bebas rug pull |
| Skor keamanan v3 | Tidak diberikan karena gerbang wajib tidak lengkap atau gagal | **Tidak memenuhi syarat alert** |

Kode gerbang laporan penuh: `v3_token_program_unsupported`. Kode eksekusi pemeriksa v3: `base_security_incomplete`. Gerbang bisa berhenti pada alasan pertama; tabel di atas tetap melaporkan komponen lain secara independen.

### GRAND THEFT CRYPTO (FiveM)

CA: `2YxbK7V6ZTKSxcavk3V4kFzdtZ4uywhhoyuSxapjpump`

[DexScreener](https://dexscreener.com/solana/6nwmQSgHWtRfXw9xqQM3hseyKzWrQq2gzamoSbjKqs32) · [Solscan mint](https://solscan.io/token/2YxbK7V6ZTKSxcavk3V4kFzdtZ4uywhhoyuSxapjpump)

Waktu: 16-11-2026 13:54:53 WIT. Ditemukan pada audit akhir: True; retrieval CA eksplisit: True.

| Gerbang pasar | Nilai | Syarat | Hasil |
|---|---:|---|---|
| Umur pool | 4.50 jam | 1 menit–24 jam | Lolos |
| Prioritas awal | Tidak | 1–60 menit | Di luar prioritas; masih boleh diperiksa |
| Market cap | $423,530.00 | $20.000–$500.000 | Lolos |
| Likuiditas | $46,762.05 | >= $10.000 | Lolos |
| Volume 1 jam | $61,128.23 | >= $5.000 | Lolos |
| BUY/SELL 5m | 305/206 | >= 1,5× | Ditolak |
| Rasio BUY/SELL | 1.48 | >= 1,5× | Ditolak |
| Volume 5m | $5,489.09 | >= $1.500 | Lolos |
| BUY 5m | 305 | >= 12 | Lolos |
| LP / MC | 11.04% | >= 8% | Lolos |
| Perubahan harga 5m | 12.99% | 0%–25% | Lolos |
| Perubahan harga 1h | 23.35% | -15%–80% | Lolos |
| Perubahan harga 24h | 1,036.00% | <= +200% | Ditolak |

Narasi: **100/100**, topik GTA. Penolakan narasi: `None`. Skor momentum tidak diteruskan ketika gerbang awal menolak; kode: `weak_activity`.

- Sumber narasi: [GameGPU](https://news.google.com/rss/articles/CBMirgFBVV95cUxOVi05VHhqUkhzTm96b0ZKV295aFFJbUZfMmNELWtuakZqTWNfVU8zVU05bFhBbjFrSHB1T1U5VHg3ZW1FWmRfRm83dm5QZ28tY0tzXzNJb3k0dlJCOFNkRWdjWERuckxqandxdE1mR3hoTXFPT1JRSkZrS2tsMS1DLUpNQ2pFVjBDZVJ2UUFnLS1nTUZIbTBza2E3QWpSZFZObU9YN1pGWUVoVlhlbkE?oc=5) — Rockstar Games is actively adapting the GTA 6 engine to the Switch 2 hardware. - GameGPU (16-11-2026 12:50:11 WIT).
- Sumber narasi: [TweakTown](https://news.google.com/rss/articles/CBMi3AFBVV95cUxPQ0ZaYnhNY0FJY1k4aXEzaEgtM3hjbjBjUmR6eXUyRnRFS1h0UndCV0JwUzF0MzRVbm9lX0RNcE5hQnRNazVfZ0lyXzFDczI5cXhEaDY5bnFFbXRISXkyd2pZd2hwR0tKcFN4bmYwVTl5cWdtZ1dPaXM5bktvVmU3UVdtaTBzdHg5Q01QdEZpN3BTX3FLaEU3REhOb0MxZVpOeVk1R3IwdEh0cW9XRHZjLTlxQjJGVUwtMzNHNmQtMmNHUlF6N1p1M29Ed2h5ZllydDVwWUxvMEhUcmVC?oc=5) — GTA 6 reportedly has a 50-hour story, matching Red Dead Redemption 2 despite its much larger map - TweakTown (16-11-2026 12:37:14 WIT).

| Gerbang keamanan | Bukti | Keputusan |
|---|---|---|
| Mint authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Freeze authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Program token | Token-2022 | **Ditolak: v3 belum mendukung seluruh pemeriksaannya** |
| LP kandidat (RugCheck) | 100.00% dilaporkan terkunci; nilai $45,362.37 | Memenuhi ambang laporan >=95% dan >=$10.000; bukan verifikasi independen semua locker |
| Konsentrasi akun token top 10 | 2.46% setelah vault yang terbukti dikecualikan | Lolos <=30% |
| Pemilik terbesar pada sampel | 0.25% | Lolos <=15% |
| Developer | Kepemilikan 0.11%; 0 transaksi dalam jendela terakhir yang diperiksa; batas riwayat 5 | Tidak ditemukan outflow token pada sampel; bukan pembuktian semua wallet developer |
| Insider / jaringan wallet | Data jaringan null/tidak lengkap meskipun counter bernilai 0 | Tidak terverifikasi; blokir |
| Keragaman / wash heuristic | observed_sample; pembeli unik 92; tanda risiko: banyak_alamat_beli_dan_jual | Tidak lengkap / pola mencurigakan; blokir |
| Jual dan pola bundle | 3 wallet jual finalized dan 12 transaksi beli finalized | Bukti historis sampel tersedia; bukan jaminan penjualan berikutnya |
| Risiko RugCheck | Tidak ada flag pada snapshot provider | Flag kosong bukan bukti bebas rug pull |
| Skor keamanan v3 | Tidak diberikan karena gerbang wajib tidak lengkap atau gagal | **Tidak memenuhi syarat alert** |

Kode gerbang laporan penuh: `v3_token_program_unsupported`. Kode eksekusi pemeriksa v3: `wash_sample_risky_or_incomplete`. Gerbang bisa berhenti pada alasan pertama; tabel di atas tetap melaporkan komponen lain secara independen.

### Cyber Dacity Coin

CA: `C5X8tVbt8cGw7iaaEuAVGTxFVZ4uSjscmiUbVpVwpump`

[DexScreener](https://dexscreener.com/solana/9iqd6n93rWEvk8KmWWw2fPBonSvfpkGHvDgpchVzSGXk) · [Solscan mint](https://solscan.io/token/C5X8tVbt8cGw7iaaEuAVGTxFVZ4uSjscmiUbVpVwpump)

Waktu: 16-11-2026 13:54:57 WIT. Ditemukan pada audit akhir: True; retrieval CA eksplisit: True.

| Gerbang pasar | Nilai | Syarat | Hasil |
|---|---:|---|---|
| Umur pool | 5.42 jam | 1 menit–24 jam | Lolos |
| Prioritas awal | Tidak | 1–60 menit | Di luar prioritas; masih boleh diperiksa |
| Market cap | $239,071.00 | $20.000–$500.000 | Lolos |
| Likuiditas | $34,734.10 | >= $10.000 | Lolos |
| Volume 1 jam | $45,823.04 | >= $5.000 | Lolos |
| BUY/SELL 5m | 99/27 | >= 1,5× | Lolos |
| Rasio BUY/SELL | 3.67 | >= 1,5× | Lolos |
| Volume 5m | $3,417.76 | >= $1.500 | Lolos |
| BUY 5m | 99 | >= 12 | Lolos |
| LP / MC | 14.53% | >= 8% | Lolos |
| Perubahan harga 5m | -6.12% | 0%–25% | Ditolak |
| Perubahan harga 1h | -1.79% | -15%–80% | Lolos |
| Perubahan harga 24h | 583.00% | <= +200% | Ditolak |

Narasi: **0/100**, topik belum terverifikasi. Penolakan narasi: `narrative_unverified`. Skor momentum tidak diteruskan ketika gerbang awal menolak; kode: `late_or_falling_price`.

Situs/profil token mengklaim tema GTA, tetapi nama/simbol dan bukti berita yang dikumpulkan belum cukup untuk memverifikasi hubungan narasi dalam aturan scanner. Skor 0 berarti belum terverifikasi, bukan bukti tema tersebut tidak ada.


| Gerbang keamanan | Bukti | Keputusan |
|---|---|---|
| Mint authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Freeze authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Program token | Token-2022 | **Ditolak: v3 belum mendukung seluruh pemeriksaannya** |
| LP kandidat (RugCheck) | 100.00% dilaporkan terkunci; nilai $35,008.56 | Memenuhi ambang laporan >=95% dan >=$10.000; bukan verifikasi independen semua locker |
| Konsentrasi akun token top 10 | 1.84% setelah vault yang terbukti dikecualikan | Lolos <=30% |
| Pemilik terbesar pada sampel | 0.19% | Lolos <=15% |
| Developer | Kepemilikan 0.00%; 0 transaksi dalam jendela terakhir yang diperiksa; batas riwayat 5 | Tidak ditemukan outflow token pada sampel; bukan pembuktian semua wallet developer |
| Insider / jaringan wallet | Data jaringan null/tidak lengkap meskipun counter bernilai 0 | Tidak terverifikasi; blokir |
| Keragaman / wash heuristic | unavailable; pembeli unik None; tanda risiko: tidak ada pada sampel yang tersedia | Tidak lengkap / pola mencurigakan; blokir |
| Jual dan pola bundle | insufficient_sell_or_buyer_sample | Belum terverifikasi; blokir |
| Risiko RugCheck | Tidak ada flag pada snapshot provider | Flag kosong bukan bukti bebas rug pull |
| Skor keamanan v3 | Tidak diberikan karena gerbang wajib tidak lengkap atau gagal | **Tidak memenuhi syarat alert** |

Kode gerbang laporan penuh: `v3_token_program_unsupported`. Kode eksekusi pemeriksa v3: `wash_sample_risky_or_incomplete`. Gerbang bisa berhenti pada alasan pertama; tabel di atas tetap melaporkan komponen lain secara independen.

### rockstar

CA: `9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump`

[DexScreener](https://dexscreener.com/solana/5PYNPPTNpdG5REsu3VqeJKqHePiJ1uwP5L7A2CcHMxdY) · [Solscan mint](https://solscan.io/token/9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump)

Waktu: 16-11-2026 13:54:59 WIT. Ditemukan pada audit akhir: True; retrieval CA eksplisit: True.

| Gerbang pasar | Nilai | Syarat | Hasil |
|---|---:|---|---|
| Umur pool | 17.91 jam | 1 menit–24 jam | Lolos |
| Prioritas awal | Tidak | 1–60 menit | Di luar prioritas; masih boleh diperiksa |
| Market cap | $529,719.00 | $20.000–$500.000 | Ditolak |
| Likuiditas | $72,335.46 | >= $10.000 | Lolos |
| Volume 1 jam | $108,740.15 | >= $5.000 | Lolos |
| BUY/SELL 5m | 35/33 | >= 1,5× | Ditolak |
| Rasio BUY/SELL | 1.06 | >= 1,5× | Ditolak |
| Volume 5m | $3,101.32 | >= $1.500 | Lolos |
| BUY 5m | 35 | >= 12 | Lolos |
| LP / MC | 13.66% | >= 8% | Lolos |
| Perubahan harga 5m | -4.41% | 0%–25% | Ditolak |
| Perubahan harga 1h | -2.09% | -15%–80% | Lolos |
| Perubahan harga 24h | 1,124.00% | <= +200% | Ditolak |

Narasi: **100/100**, topik GTA. Penolakan narasi: `None`. Skor momentum tidak diteruskan ketika gerbang awal menolak; kode: `weak_activity`.

- Sumber narasi: [GameGPU](https://news.google.com/rss/articles/CBMirgFBVV95cUxOVi05VHhqUkhzTm96b0ZKV295aFFJbUZfMmNELWtuakZqTWNfVU8zVU05bFhBbjFrSHB1T1U5VHg3ZW1FWmRfRm83dm5QZ28tY0tzXzNJb3k0dlJCOFNkRWdjWERuckxqandxdE1mR3hoTXFPT1JRSkZrS2tsMS1DLUpNQ2pFVjBDZVJ2UUFnLS1nTUZIbTBza2E3QWpSZFZObU9YN1pGWUVoVlhlbkE?oc=5) — Rockstar Games is actively adapting the GTA 6 engine to the Switch 2 hardware. - GameGPU (16-11-2026 12:50:11 WIT).
- Sumber narasi: [TweakTown](https://news.google.com/rss/articles/CBMi3AFBVV95cUxPQ0ZaYnhNY0FJY1k4aXEzaEgtM3hjbjBjUmR6eXUyRnRFS1h0UndCV0JwUzF0MzRVbm9lX0RNcE5hQnRNazVfZ0lyXzFDczI5cXhEaDY5bnFFbXRISXkyd2pZd2hwR0tKcFN4bmYwVTl5cWdtZ1dPaXM5bktvVmU3UVdtaTBzdHg5Q01QdEZpN3BTX3FLaEU3REhOb0MxZVpOeVk1R3IwdEh0cW9XRHZjLTlxQjJGVUwtMzNHNmQtMmNHUlF6N1p1M29Ed2h5ZllydDVwWUxvMEhUcmVC?oc=5) — GTA 6 reportedly has a 50-hour story, matching Red Dead Redemption 2 despite its much larger map - TweakTown (16-11-2026 12:37:14 WIT).

| Gerbang keamanan | Bukti | Keputusan |
|---|---|---|
| Mint authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Freeze authority | Dicabut berdasarkan akun mint finalized | Lolos |
| Program token | Token-2022 | **Ditolak: v3 belum mendukung seluruh pemeriksaannya** |
| LP kandidat (RugCheck) | 100.00% dilaporkan terkunci; nilai $72,368.02 | Memenuhi ambang laporan >=95% dan >=$10.000; bukan verifikasi independen semua locker |
| Konsentrasi akun token top 10 | 24.89% setelah vault yang terbukti dikecualikan | Lolos <=30% |
| Pemilik terbesar pada sampel | 4.05% | Lolos <=15% |
| Developer | Kepemilikan 0.00%; 5 transaksi dalam jendela terakhir yang diperiksa; batas riwayat 5 | Tidak ditemukan outflow token pada sampel; bukan pembuktian semua wallet developer |
| Insider / jaringan wallet | 7 jaringan; graphInsidersDetected=320 | Jaringan terdeteksi; blokir |
| Keragaman / wash heuristic | observed_sample; pembeli unik 34; tanda risiko: tidak ada pada sampel yang tersedia | Lolos sampel |
| Jual dan pola bundle | supported_pool_swap_unverified | Belum terverifikasi; blokir |
| Risiko RugCheck | Tidak ada flag pada snapshot provider | Flag kosong bukan bukti bebas rug pull |
| Skor keamanan v3 | Tidak diberikan karena gerbang wajib tidak lengkap atau gagal | **Tidak memenuhi syarat alert** |

Kode gerbang laporan penuh: `v3_token_program_unsupported`. Kode eksekusi pemeriksa v3: `v3_token_program_unsupported`. Gerbang bisa berhenti pada alasan pertama; tabel di atas tetap melaporkan komponen lain secara independen.

## Kesimpulan dan keterbatasan

**Tidak ada alert yang dikirim oleh audit ini.** Token-2022 tidak otomatis berarti rug pull; v3 menolaknya karena belum mendukung pemeriksaan lengkap program tersebut. Memiliki mint/freeze yang dicabut dan LP yang dilaporkan terkunci tidak cukup untuk meloloskan token.

Transaksi FiveM memperlihatkan penjualan sukses pada sampel, tetapi pola roundtrip tinggi adalah peringatan heuristik dan bukan pembuktian manipulasi. Untuk Cyber Dacity data trade feed belum tersedia, dan untuk Rockstar instruksi swap pada sampel belum dikenali; keduanya tidak disimpulkan pasti tidak bisa dijual. Null insider tidak dianggap nol. Sumber pasar berubah cepat, dan hasil tidak menjamin keamanan, keuntungan, atau kenaikan berikutnya.

Validasi: 174 tes Python lulus; audit live tanpa akses Telegram berhasil. File aturan keamanan `security_v3.py`, `evidence.py`, `screening_rules.py` dan `bot.py` tidak diubah pada perbaikan ini. Cron Cloudflare tetap lima menit.

[Bukti JSON ringkas](audit/real-token-20261116.json) memuat snapshot dan komponen independen. Artefak lengkap tersedia pada run GitHub Actions audit (retensi 14 hari).
