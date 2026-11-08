# Scanner v2 — ALERT ONLY

Ini upgrade scanner di repositori yang sama, memakai bot Telegram, tujuan, tombol ON/OFF, dan secrets yang sudah ada. Tidak ada private key, transaksi, pembelian, atau penjualan otomatis. `bot.scan()` lama, Cloudflare, dan seluruh tes lama dipertahankan. Branch `backup/scanner-before-v2-20261108` menyimpan titik sebelum upgrade.

## Temuan audit

Run #106 gagal di `getMe` dengan galat transport setelah 27 tes filter lulus. Versi lama memberi Telegram, discovery, dan pemeriksaan keamanan satu anggaran 30 detik. V2 memisahkan kontrol (30 detik) dari scanning (100 detik), memakai timeout permintaan 8 detik, dan mengambil feed independen dengan paling banyak empat koneksi sekaligus. Ini mengurangi kemungkinan seluruh waktu habis sebelum kandidat diperiksa; tidak menjamin provider selalu tersedia.

## Pencarian dan penilaian

DexScreener profiles, boosts, ads, takeovers dan GeckoTerminal new pools tetap dipakai. Boost/iklan tidak memberi poin. Pool 1 menit–24 jam dipantau; pool 1–60 menit didahulukan. Riwayat observasi bertahan antar-run. Umur mint dinyatakan terverifikasi hanya jika pagination RPC mencapai akhir riwayat dan transaksi paling awal memuat initializeMint/initializeMint2 untuk mint yang sama, berhasil dan finalized. Pemeriksaan dibatasi 3.000 signature; riwayat terpotong diberi status belum terverifikasi. Pool baru bukan bukti token baru; status meme juga tidak dapat dipastikan hanya dari data DEX.

Prasyarat pasar: LP >= $10.000, LP/market cap >= 8%, volume 5m >= $1.500, BUY >= 12, rasio BUY/SELL >= 1,5, harga 5m tidak turun dan belum melampaui +25%. Market cap berasal dari penyedia, bukan audit valuasi.

| Skor terpisah | Komponen |
|---|---|
| Market 0–100 | Tekanan BUY 25, jumlah BUY 20, kedalaman LP 20, volume 15, harga awal 10, percepatan 10 |
| Keamanan 0–100 | Authority dan ekstensi mint 40, konsentrasi 10 akun token 30, RugCheck 30 |
| Komunitas 0–100 atau belum cukup data | Rata-rata analisis X dan Telegram; hanya dihitung ketika keduanya memiliki data |

**EARLY WATCH**: market >=60 dan mint/freeze serta ekstensi sudah lolos. Penarikan LP, flag bahaya RugCheck yang diketahui, dan top10 akun >30% tetap menolak kandidat. Bukti distribusi, RugCheck, mint age, komunitas, atau pembeli yang belum tersedia ditulis sebagai risiko; status ini bukan rekomendasi beli.

**STRONG SIGNAL**: masing-masing skor market, keamanan, komunitas >=80; semua pemeriksaan wajib lengkap; umur mint terbukti <=24 jam; minimal 20 alamat pembeli unik dan 3 alamat penjual dalam sampel trade 5m; tidak ada pola konsentrasi/nominal berulang/putaran beli-jual yang melewati batas. Perlu dua observasi 5–15 menit terpisah, volume, BUY dan jumlah transaksi masing-masing tumbuh >=10%; LP bertahan >=90%; harga belum melonjak (5m <=15%, 1j <=60%, harga dibanding baseline <=15%). Kekurangan bukti tidak diubah menjadi lolos.

Trade disaring berdasarkan mint tujuan/sumber dan hash transaksi, lalu dihitung alamat pengirim unik. Alamat berbeda dapat dikendalikan orang/bot yang sama. Keragaman alamat, transaksi, interaksi X dan anggota Telegram **tidak membuktikan pembeli manusia nyata**, bebas manipulasi, atau profit. Heuristik tidak dipasarkan sebagai detektor bot pasti.

## X dan Telegram

Tautan hanya diambil dari metadata token; host dan pola handle divalidasi. Konflik metadata tidak dipilih sembarangan. Tautan akun yang belum dapat dibaca tidak dipromosikan sebagai akun resmi terverifikasi. Identitas lebih kuat memerlukan mint yang sama dalam profil/posting/pinned message. Tidak ada pemindaian situs sembarang atau bypass akun privat.

- X: memakai API resmi profil dan maksimal 20 posting, tanggal posting, interaksi yang tersedia, pengulangan teks, umur akun, serta penyebutan mint. Memerlukan secret `X_BEARER_TOKEN` dan variabel `X_READS_ENABLED=1`. Default tidak mengaktifkan panggilan X berbayar. Tanpa konfigurasi atau saat API menolak, skor tidak dibuat-buat; STRONG SIGNAL tertahan. Tidak ada pembelian paket/API baru otomatis.
- Telegram: `getChat`, `getChatMemberCount` dan sampel posting publik `t.me/s/<handle>` jika tersedia. Tidak bergabung grup atau menghubungi admin. Jumlah anggota tidak memberi poin. Grup privat, komentar, keseluruhan riwayat, identitas bot, dan aktivitas semua anggota dapat tidak tersedia. Untuk kanal, skor menggambarkan posting publik, bukan percakapan semua anggota. Tautan dapat terbaca tanpa identitas mint yang cocok; status konsistensinya tetap diperiksa.
- X/Telegram dengan banyak teks berulang ditandai indikasi spam, bukan vonis palsu. Tanda centang dan jumlah pengikut bukan bukti keaslian.

## Pengiriman dan pemulihan

Satu alert per mint per tingkat. Kenaikan EARLY WATCH ke STRONG SIGNAL boleh dikirim sekali karena ada bukti baru. Setelah STRONG SIGNAL, EARLY WATCH tidak dikirim lagi. Ledger bertahan 14 hari, lebih lama dari jendela umur pool; pesan lama mendapat perlindungan migrasi.

Sebelum mengirim, reservasi disimpan ke `state.json` dan di-push pada Actions main. Jika penyimpanan gagal, pesan tidak dikirim. Kegagalan jaringan setelah sendMessage ditandai unknown dan tidak diulang otomatis untuk menghindari duplikasi. Akibatnya sebuah pesan yang tidak jelas hasilnya dapat terlewat; tidak ada klaim exactly-once Telegram.

`persist_state.py` melakukan merge terhadap main terbaru dan hanya menulis state.json; tidak mereset/menghapus kode. ON/OFF dari offset callback admin terbaru tetap berlaku. Data yang disimpan hanyalah kontrol, statistik publik dan bukti agregat, bukan token API atau isi chat privat.

## Performa dan jadwal

Harga setelah sinyal diamati pada target 5m, 15m, 1j, 24j. Laporan menyertakan waktu observasi sebenarnya dan perubahan harga sejak alert; tidak termasuk fee/slippage dan bukan laba transaksi. Bila jadwal terlambat melewati jendela toleransi (10 menit; 3 jam untuk titik 24j), titik ditandai missed, bukan diisi harga belakangan seolah tepat waktu. Riwayat dan laporan tersedia di state serta artifact Actions `scanner-v2-report-*`.

Cron tetap `3-59/5 * * * *`. Satu job menjalankan tiga putaran dengan jeda 30 detik, batas 10 menit. GitHub Actions dapat terlambat, mengantre atau melewatkan jadwal; bukan layanan pemantauan 24/7 tepat per menit. Feed gratis punya cakupan dan rate limit; tidak mencakup semua peluncuran. Tidak ada langganan ditambahkan.

## Validasi

`python3 -m unittest -v` menjalankan tes lama dan tes v2 tanpa notifikasi sungguhan. Workflow `Scanner Upgrade Tests` menguji branch/PR. Workflow `Telegram Connection Check` memanggil getMe/getChat dan mengirim satu pesan uji yang jelas bukan sinyal. Log sukses mencatat username bot dan message_id tanpa nilai secret. Rerun attempt >1 tidak mengirim ulang; pengujian manual baru merupakan run baru.

Referensi API: [DexScreener](https://docs.dexscreener.com/api/reference), [GeckoTerminal](https://api.geckoterminal.com/docs/index.html), [Trades](https://docs.coingecko.com/reference/pool-trades-contract-address), [Telegram](https://core.telegram.org/bots/api), [X](https://docs.x.com/x-api/users/get-posts), [Solana signatures](https://solana.com/docs/rpc/http/getsignaturesforaddress), [Solana transaction](https://solana.com/docs/rpc/http/gettransaction).
