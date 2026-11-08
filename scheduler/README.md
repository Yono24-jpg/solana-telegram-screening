# MAIL Solana Scheduler

Worker terpisah bernama `mail-solana-scheduler` memanggil **hanya** workflow `screen.yml`, branch `main`, repositori `Yono24-jpg/solana-telegram-screening`. Cron: `*/5 * * * *` dalam UTC (setiap lima menit juga dalam WIT). Kode Python, scanner Cloudflare lama, Telegram, tombol ON/OFF, dan pengaturan trading tidak diubah oleh pemasangan ini.

## Akses terbatas dan secrets

Buat **fine-grained personal access token** pada akun `Yono24-jpg`:

- Resource owner: `Yono24-jpg`.
- Repository access: **Only select repositories**, hanya `solana-telegram-screening`.
- Repository permissions: **Actions: Read and write**. Metadata Read ditambahkan GitHub secara otomatis. Tidak perlu Contents Write, Administration, atau akses seluruh repositori.
- Masa berlaku: 30 hari; rotasi sebelum berakhir. Token kedaluwarsa akan gagal dengan status izin, bukan mengganti token atau memperluas akses sendiri.

Untuk jalur deploy GitHub Actions opsional, simpan melalui GitHub Settings → Secrets and variables → Actions dengan nama **`SCHEDULER_GITHUB_TOKEN`**. Pada pemasangan produksi langsung melalui koneksi Cloudflare, token cukup tersimpan sebagai secret Worker **`GITHUB_TOKEN`**. Jangan menaruh nilai token pada kode, issue, PR, artifact, atau percakapan. Token koneksi ChatGPT dan `GITHUB_TOKEN` sementara milik runner tidak diekspor untuk layanan jangka panjang.

GitHub membatasi izin Actions pada tingkat repositori, bukan pada satu nama workflow. Karena itu pemilihan satu repositori harus benar saat token dibuat. Prefiks token fine-grained dan akun pemilik diperiksa oleh deploy; daftar izin dan pilihan repositori tidak dapat dibuktikan dari prefiks. Worker sendiri mengunci URL, ref, dan body permintaan tanpa parameter target dari pengguna.

Jalur deploy GitHub Actions opsional memerlukan `CLOUDFLARE_API_TOKEN` yang aktif, tanpa mencetak nilainya. Token CI lama terdeteksi tidak aktif; hal ini tidak menghambat Worker produksi yang telah dipasang lewat koneksi Cloudflare. Bila token Cloudflare memerlukan pemilihan akun, tambahkan `CLOUDFLARE_ACCOUNT_ID` untuk akun yang sama. Token Cloudflare perlu izin membaca akun dan mengelola Workers Scripts/Cron/Durable Objects yang dipakai. Tidak dibuat subscription atau layanan berbayar baru.

Pada Worker, token GitHub disimpan sebagai secret **`GITHUB_TOKEN`**. Secret admin **`SCHEDULER_ADMIN_TOKEN`** dibuat dalam memori deploy untuk pengujian, disimpan hanya sebagai secret Worker, tidak ditulis ke file atau log. Worker tidak menerima secret Telegram atau private key.

## Pencegahan pemicu ganda

- Satu Durable Object SQLite dengan nama tetap membuat reservasi atomik per slot lima menit, sebelum permintaan dispatch dikirim. State bertahan setelah restart dan deploy. Riwayat sekitar 24 jam dibatasi; tick yang terlambat >10 menit atau berada di masa depan ditolak.
- Cooldown 4 menit 55 detik mencegah pemicu berdekatan di batas dua slot dan memberi toleransi jitter cron beberapa detik.
- Sebelum POST, workflow harus aktif dan identitasnya tepat. Run scanner yang sedang antre/berjalan atau baru dimulai dalam periode cooldown menahan dispatch tambahan. Data/API pemeriksaan yang gagal tidak dianggap aman untuk memicu.
- Gangguan jaringan sesudah reservasi POST diberi `dispatch_unknown_no_retry`. Tidak ada pengulangan otomatis untuk slot yang sama. Ini dapat melewatkan satu putaran, tetapi menghindari pengiriman POST berulang saat hasilnya belum jelas.
- HTTP publik hanya menyediakan `/health`. `/admin/tick` dan `/admin/status` membutuhkan secret admin; tidak ada `force`, target repositori bebas, atau tombol pemicu publik.

Cron GitHub dan watchdog lama tetap ada. Reservasi ini mencegah duplikasi **antar-panggilan Worker**, bukan penguncian atomik terhadap pemicu GitHub yang independen. Ada kemungkinan race bila cron GitHub mulai sesudah pemeriksaan API. Concurrency dan ledger anti-alert-ganda yang sudah ada tetap berlaku; tidak ada klaim exactly-once untuk seluruh pemicu atau Telegram. Menghapus jadwal lama tidak dilakukan diam-diam.

## Pemasangan dan bukti

Workflow `.github/workflows/mail-solana-scheduler.yml`:

1. Menjalankan tes scheduler (termasuk SQLite workerd nyata), tes Python lama, dan validasi bundle Wrangler tanpa deploy.
2. Pada push/PR dan pilihan manual **checks**: hanya tes, tanpa membaca secrets atau mengunggah Worker. Default ini tidak bergantung pada token CI lama.
3. Audit dan deploy hanya dijalankan melalui **Run workflow** dengan pilihan **audit** atau **deploy**. Keduanya memerlukan secrets CI sendiri. Deploy memeriksa token GitHub dan target akun sebelum menulis hanya Worker scheduler. Jika token GitHub belum tersedia, berhenti sebelum menulis Worker.
4. Memanggil dua tick terautentikasi secara bersamaan, memastikan paling banyak satu dispatch diterima dan perlindungan duplikasi terlihat.
5. Menunggu riwayat dari **cron Cloudflare sungguhan**, dispatch GitHub yang diterima, serta run scanner baru dengan hasil **success**. HTTP 204 sendiri tidak membuktikan scanner selesai. Tindakan manual tidak dicatat sebagai cron.

Artifact `mail-scheduler-<run_id>/deployment.json` memuat status aktual, outcome aman, dan URL run yang teramati. `verified_real_cron_dispatch_and_scanner_success` hanya diberikan setelah ketiga bukti tersedia. Perubahan cron Cloudflare dapat memerlukan waktu propagasi; verifier menunggu hingga 20 menit. Bila lewat batas, deploy dilaporkan belum terverifikasi dan cron tetap dapat berjalan; jangan menyebutnya berhasil 24 jam.

Jalankan `MAIL Solana Scheduler` → **Run workflow** pada `main`; default **checks** hanya menjalankan tes. Pilih **audit/deploy** hanya setelah secrets CI untuk akun dan Worker yang benar sudah disiapkan. Worker produksi yang aktif tidak memerlukan workflow deploy ini berjalan berkala. Tidak ada pesan tes Telegram tambahan dari scheduler; scanner lama tetap dapat mengirim kandidat yang benar-benar lolos seperti biasa.

Pengujian lokal: `npm ci` lalu `npm test` dari folder ini. `npx wrangler deploy --dry-run` memvalidasi bundle saja. `python3 scheduler/deploy.py audit` dari root memeriksa akses tanpa mutasi Cloudflare.

Referensi: [workflow dispatch dan izin Actions](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/), [SQLite Durable Objects](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/), [secret Worker](https://developers.cloudflare.com/workers/configuration/secrets/).
