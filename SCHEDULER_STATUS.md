# Verifikasi mail-solana-scheduler — 9 November 2026 WIT

Pemeriksaan produksi berhasil mencocokkan cron Cloudflare dengan dua run scanner otomatis. Ini bukti pada interval yang diamati, bukan jaminan uptime 24 jam.

| Log Cloudflare (WIT, 9 Nov) | Outcome | GitHub run | Hasil |
|---|---|---|---|
| 04:06:02.748 | dispatch_accepted, HTTP 204 | [42513300907](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/42513300907) | success |
| 04:11:03.777 | dispatch_accepted, HTTP 204 | [42513745681](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/42513745681) | success |

Kedua log bertipe **scheduled**, cron `*/5 * * * *`, dengan slot berbeda 5980549 dan 5980550. Selisih penerimaan aktual sekitar lima menit satu detik. Event GitHub bernama `workflow_dispatch` karena dipanggil dari cron Cloudflare; bukan event native `schedule` GitHub.

## Konfigurasi dan token

Worker aktif dengan `SCHEDULER_ENABLED=true`. Secret `GITHUB_TOKEN` dan `SCHEDULER_ADMIN_TOKEN` tersimpan sebagai secret_text. Namespace SQLite `SchedulerCoordinator` terikat dan satu objek mempunyai data tersimpan. Logs serta traces aktif. Nilai secret tidak dibaca atau dicetak. Token GitHub terbukti dapat membaca workflow/run dan melakukan dispatch HTTP 204; pemilihan seluruh izin/repository pada saat token dibuat tidak dapat disimpulkan hanya dari keberhasilan dispatch.

Source produksi cocok persis dengan `scheduler/worker.mjs` yang telah lulus 22 tes, termasuk konkurensi runtime workerd SQLite dan pemulihan reservasi setelah restart. Tidak ditemukan pola token inline pada source yang diunduh. Tidak ada perubahan terhadap source Worker produksi saat audit ini.

## Anti-duplikasi dan batas bukti

Reservasi per slot dibuat dalam transaksi Durable Object sebelum POST. Cooldown, pemeriksaan run aktif/terbaru, dan larangan mengulang POST dengan hasil ambigu tetap berlaku. Dua slot yang diperiksa masing-masing menghasilkan satu run GitHub; tidak terlihat run ganda pada interval tersebut.

Tes konkurensi/restart membuktikan perilaku pada runtime lokal; audit ini tidak menyebutnya sebagai pengiriman puluhan request ke produksi. Cron/watchdog GitHub yang independen masih mungkin berlomba sesudah pemeriksaan API. Concurrency workflow dan ledger Telegram lama tetap tersedia; tidak ada klaim exactly-once lintas semua pemicu.

## Scanner dan Telegram

Kedua run menjalankan 118 tes Python dengan hasil lulus dan masing-masing tiga scan sukses. Enam putaran memeriksa 119–141 pool per putaran (pool dapat berulang). Tiap putaran menyimpan state. Tidak ada kandidat lolos dan `sent=0` pada semua putaran; tidak dibuat sinyal atau pesan tes tambahan.

Bot yang terverifikasi dari getMe adalah `@SolHawkHunter917Bot`; getChat/getUpdates juga sukses ke tujuan bertipe channel. Ini bukti koneksi, bukan bukti pengiriman alert baru. Ledger tetap memuat dua alert lama; tidak digunakan untuk mengklaim kiriman baru.

## Galat dan perbaikan

Query log Cloudflare untuk 15 menit hingga 04:14:58 WIT tidak menemukan event galat. Run pemasangan scheduler lama yang gagal tetap ada dalam riwayat: token Cloudflare pada GitHub Actions lama tidak aktif. Produksi sekarang memakai koneksi Cloudflare dan token yang tersimpan langsung di Worker.

Workflow pemasangan diperbaiki: push/PR menjalankan tes saja; audit/deploy menjadi pilihan manual eksplisit. Default `checks` tidak memakai secrets dan tidak mencoba menimpa Worker produksi dengan kredensial CI lama. Jika jalur deploy CI dipakai kelak, secrets CI tetap harus diperbarui untuk akun dan Worker yang benar.

Bot Python, scanner Cloudflare lama, jadwal scanner/watchdog lama, secrets Telegram, dan mode ALERT ONLY tidak diubah. Tidak ada trading otomatis.
