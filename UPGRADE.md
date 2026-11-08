# Scanner v2.2 — ALERT ONLY

## Perbaikan vault dan bukti jadwal v2.2

Masalah yang diperbaiki: jumlah 10 akun token terbesar sebelumnya mencakup vault LP. Vault dapat berisi banyak token tanpa menjadi dompet pemilik besar. V2.2 menampilkan angka sebelum dan sesudah koreksi dan hanya mengecualikan vault yang **terbukti** di chain.

- Mendukung layout PumpSwap, Raydium CPMM, Raydium CLMM (termasuk seed index baru), dan Raydium AMM v4. Program owner, discriminator/ukuran layout, pasangan mint, pointer vault dan authority wajib cocok. PDA diverifikasi memakai seed/bump yang tersimpan; CPMM juga harus cocok dengan authority resmi SDK. Label `dexId`, nama, metadata atau flag `isLP` tidak memberi pengecualian.
- Akun vault wajib milik program token mint yang sama, berisi mint yang sama, authority sesuai pool, initialized, tidak dibekukan, tidak mempunyai delegate, dan tidak mempunyai close authority asing. Ekstensi akun Token-2022 hanya menerima ImmutableOwner untuk pengecualian ini; ekstensi lain tetap dihitung.
- Dua query membaca 20 akun token terbesar serta batch mint/pool/akun token. Query bukti memakai `finalized` dan `minContextSlot`; jarak maksimal 40 slot. Suplai harus tetap sama. Angka top10 dan token vault yang dikeluarkan memakai snapshot query terbesar yang sama; perubahan saldo akibat trade saat query bukti berlangsung tidak dicampur ke angka tersebut. Slot snapshot dan slot bukti tercatat terpisah. Perubahan suplai, akun hilang, tipe/mint tidak cocok, atau RPC gagal membatalkan pengecualian parsial.
- Batas top10 tetap **30% dari seluruh suplai**, setelah hanya vault terbukti dikeluarkan. Akun lain, termasuk vault protokol yang belum didukung, tetap dihitung. Pemeriksaan ini bukan 10 pemilik unik. Authority non-vault yang terlihat pada sampel dikelompokkan; >15% suplai pada satu pemilik teramati ditolak. Sampel 20 akun tidak membuktikan konsentrasi semua pemilik di seluruh chain.
- Pool Raydium dengan status swap nonaktif ditolak. Bukti vault **bukan** bukti LP terkunci, LP dibakar, bebas rug pull, atau kemampuan menjual semua wallet. Gerbang mint/freeze, ekstensi, RugCheck, market, pembeli, dan komunitas tetap berlaku.
- Protokol/layout tak dikenal tidak mendapat pengecualian. Karena itu pool sehat di protokol yang belum didukung tetap mungkin ditolak secara konservatif. Tidak ada pengecualian berdasarkan dugaan.

Audit operasional menemukan workflow `screen.yml` berstatus `active`, tetapi tidak ada run terjadwal baru pada interval yang diperiksa setelah 21.31 WIT 8 November 2026. Status aktif sendiri tidak membuktikan jadwal bekerja. Cron diperbarui ke daftar menit eksplisit setiap lima menit di luar menit 0: `2,7,12,17,22,27,32,37,42,47,52,57 * * * *` (UTC). Perubahan konfigurasi ini **tidak boleh dilaporkan sebagai jadwal pulih sebelum ada run ber-event `schedule`**.

`last_scan.trigger`, `run_id`, `scan_history` (maksimal 100 observasi/7 hari), serta artifact `operations.json` membedakan run `push`, manual, dan `schedule`. Jeda scan >15 menit diberi peringatan di ringkasan Actions. Riwayat digabung dan dipulihkan bersama state. Tidak dibuat loop pemicu workflow tanpa batas atau layanan berbayar.

Backup: `backup/scanner-v21-before-vault-fix-20261108`. Pengujian mencakup empat layout dan kedua sisi mint, PDA contoh resmi PumpSwap, vault palsu, authority salah, delegate, freeze, Token-2022, RPC terputus/slot tidak konsisten, pergeseran saldo saat trade, konsentrasi pemilik, status swap, dan gerbang keamanan setelah koreksi. `vault_audit.py` hanya membaca contoh pool mainnet dari dokumentasi resmi; hasil `unavailable` tidak dianggap bukti berhasil. Tidak ada pesan atau transaksi dari audit ini.

Referensi layout: [PumpSwap IDL](https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump_amm.json), [PumpSwap pool](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md), [Raydium program IDs](https://github.com/raydium-io/raydium-sdk-V2/blob/master/src/common/programId.ts), [CPMM layout](https://github.com/raydium-io/raydium-sdk-V2/blob/master/src/raydium/cpmm/layout.ts), [CPMM state](https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/states/pool.rs), [CLMM state](https://github.com/raydium-io/raydium-clmm/blob/master/programs/amm/src/states/pool.rs), [AMM v4 layout](https://github.com/raydium-io/raydium-sdk-V2/blob/master/src/raydium/liquidity/layout.ts), [RPC largest accounts](https://solana.com/docs/rpc/http/gettokenlargestaccounts), [RPC multiple accounts](https://solana.com/docs/rpc/http/getmultipleaccounts).

## Perbaikan deteksi dini v2.1

Audit feed langsung sebelum perubahan menemukan 101 pool, dengan 70 penolakan data pasar; 62 pool tidak memiliki data likuiditas DexScreener. Data ini adalah sampel saat audit, bukan angka tetap atau ukuran profit.

- GeckoTerminal sekarang merupakan sumber pasar independen. Pool yang belum terindeks lengkap di DexScreener tetap dapat diperiksa memakai satu snapshot GeckoTerminal: mint, alamat pool, waktu pembuatan, LP, harga, volume dan transaksi. Snapshot finansial dua sumber tidak dicampur; konflik mint ditolak dan konflik umur menahan STRONG SIGNAL. Jalur DexScreener tetap dipakai.
- Market cap yang kosong tidak diganti diam-diam. Bila FDV tersedia, EARLY WATCH boleh memakai rasio LP/FDV >=8% dengan label **FDV, MC belum tersedia**. MC dan FDV bukan hal yang sama. STRONG SIGNAL tetap memerlukan market cap dari penyedia. LP/volume/harga kosong tidak diisi angka palsu.
- Pool menjanjikan disimpan hingga umur 24 jam, maksimal 200 pool, dan dirotasi untuk pemeriksaan ulang setelah keluar dari halaman terbaru. Ambang masuk daftar pantauan LP $5.000 dan volume 5m $500 **bukan** ambang pengiriman alert; gerbang pengiriman tetap LP $10.000, volume $1.500, BUY 12, rasio 1,5 dan skor 60.
- Mint yang terbukti berumur >24 jam ditolak pada kedua tingkat sinyal, meskipun pool baru. Mint belum terverifikasi hanya boleh EARLY WATCH dengan peringatan. Mint yang waktunya bertentangan dengan umur pool ditolak. Harga 24 jam >+200% ditolak untuk menghindari mengejar lonjakan yang sudah terjadi; batas harga 5m/1j tetap berlaku.
- Sampel pembeli dengan konsentrasi volume, putaran beli-jual, nominal berulang, atau flag anomali penyedia menahan kedua tingkat sinyal. Alamat unik tetap bukan bukti manusia.
- Tautan sosial baru ditampilkan sebagai terverifikasi apabila akun dapat dibaca **dan** mint yang sama ditemukan dalam profil/posting. Tautan metadata, nama mirip, dan akun yang sekadar ada bukan verifikasi proyek.
- Anggaran GeckoTerminal maksimal sembilan permintaan per 60 detik, termasuk kegagalan, disimpan antar-proses. Batas ini tidak menjamin bebas 429. Tidak ada paket berbayar diaktifkan.
- Laporan Actions menunjukkan sumber data, field kosong, penolakan, antrean pantauan, dan jarak waktu dari scan sebelumnya. Statistik harga setelah sinyal dipisahkan menurut EARLY WATCH/STRONG SIGNAL; median hanya memakai observasi nyata. Titik terlewat tetap `missed`, kenaikan/penurunan terbaik yang **teramati** bukan nilai tertinggi/terendah seluruh tick dan bukan profit trading.

Backup tambahan: `backup/scanner-v2-before-early-discovery-20261108`. Tes v2.1 mencakup feed mandiri, fallback refresh, identitas/umur konflik, label FDV, anggaran API setelah restart, daftar pantauan 24 jam, mint lama, sampel pembeli mencurigakan, serta statistik tanpa data rekaan. Seluruh 27 tes lama tetap dipertahankan.

Kenaikan ribuan persen tidak dapat diprediksi atau dijamin oleh skor ini. Belum ada bukti backtest atau profit nyata. Ketiadaan API X masih menahan STRONG SIGNAL; EARLY WATCH tetap dapat berjalan dengan keterbatasan ditulis jelas.

## Dasar scanner v2 (tetap berlaku kecuali perubahan di atas)

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

**EARLY WATCH**: market >=60 dan mint/freeze serta ekstensi sudah lolos. Penarikan LP, flag bahaya RugCheck yang diketahui, dan top10 akun >30% tetap menolak kandidat. V2.2 hanya mengeluarkan vault LP dengan bukti on-chain seperti dijelaskan di atas; vault lain tetap dihitung. Bukti distribusi, RugCheck, mint age, komunitas, atau pembeli yang belum tersedia ditulis sebagai risiko; status ini bukan rekomendasi beli.

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

Cron v2.2 memakai daftar menit setiap lima menit yang ditulis di bagian operasional di atas. Satu job menjalankan tiga putaran dengan jeda 65 detik, batas 12 menit. Jeda mengikuti cache dan batas API gratis. GitHub Actions dapat terlambat, mengantre atau melewatkan jadwal; bukan layanan pemantauan 24/7 tepat per menit. Feed gratis punya cakupan dan rate limit; tidak mencakup semua peluncuran. Tidak ada langganan ditambahkan.

## Validasi

`python3 -m unittest -v` menjalankan tes lama dan tes v2 tanpa notifikasi sungguhan. Workflow `Scanner Upgrade Tests` menguji branch/PR. Workflow `Telegram Connection Check` memanggil getMe/getChat dan mengirim satu pesan uji yang jelas bukan sinyal. Log sukses mencatat username bot dan message_id tanpa nilai secret. Rerun attempt >1 tidak mengirim ulang; pengujian manual baru merupakan run baru.

Referensi API: [DexScreener](https://docs.dexscreener.com/api/reference), [GeckoTerminal](https://api.geckoterminal.com/docs/index.html), [Trades](https://docs.coingecko.com/reference/pool-trades-contract-address), [Telegram](https://core.telegram.org/bots/api), [X](https://docs.x.com/x-api/users/get-posts), [Solana signatures](https://solana.com/docs/rpc/http/getsignaturesforaddress), [Solana transaction](https://solana.com/docs/rpc/http/gettransaction).
