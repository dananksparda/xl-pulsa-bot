---
title: XL Pulsa Bot
emoji: 📱
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Bot Telegram Cek Pulsa XL

Bot Telegram untuk cek pulsa, masa aktif, dan kuota nomor XL — pakai API myXL
dari [me-cli-sunset](https://github.com/purplemashu/me-cli-sunset). Dibuat untuk
dijalankan sebagai webhook di **Hugging Face Spaces (gratis)** atau
Render free tier.

## Perintah

| Perintah | Fungsi |
|---|---|
| `/login 628xxxxxxxxxx` | Kirim OTP via SMS ke nomor XL |
| `/otp 123456` | Masukkan kode OTP, simpan sesi |
| `/cek` | Pulsa + masa aktif + ringkasan kuota |
| `/paket` | Detail semua paket aktif |
| `/token` | Tampilkan refresh token (untuk disimpan sebagai Secret) |
| `/logout` | Hapus sesi login |

Satu akun Telegram = satu nomor XL.

## OTP cuma sekali

API XL tidak bisa dicek tanpa login — OTP wajib, tapi **hanya sekali** saat
login pertama. Setelah itu `/cek` memakai refresh token yang tersimpan, tanpa
OTP lagi. Satu-satunya masalah: di Render gratis, `sessions.json` ikut
terhapus tiap restart, jadi bot akan minta OTP lagi.

Supaya tidak perlu OTP lagi setelah restart:

1. Login sekali seperti biasa (`/login` → `/otp`).
2. Kirim `/token` ke bot — bot menampilkan refresh token saat ini.
3. Di Space Settings → Variables and secrets, tambahkan ketiganya sebagai
   **Secret**: `XL_NUMBER`, `XL_REFRESH_TOKEN`, dan `XL_SUBSCRIBER_ID`
   (ketiganya ditampilkan oleh perintah `/token`).
4. Restart Space (Factory reboot). Setelah itu, walau Space restart, bot
   memulihkan sesi dari Secret dan `/cek` tetap jalan tanpa OTP.

Catatan: tiap refresh, XL bisa mengeluarkan refresh token baru — bot menyimpan
yang baru di `sessions.json`, tapi nilai di environment variable tetap yang
lama. Kalau suatu hari `/cek` gagal total, ulangi langkah 2–3 dengan token
terbaru (atau `/login` ulang sekali).

## 1. Buat bot Telegram

1. Chat [@BotFather](https://t.me/BotFather) di Telegram → `/newbot`
2. Ikuti langkahnya, salin token yang diberikan (format `123456:ABC...`).
   Token ini = `BOT_TOKEN`.

## 2. Ambil variabel API XL

Sesuai README repo sumber: buka channel Telegram
[@alyxcli](https://t.me/alyxcli), salin environment variables yang dibagikan di
sana, dan isi ke `.env` (salin dari `.env.example`):

```
BASE_API_URL, BASE_CIAM_URL, BASIC_AUTH, UA, API_KEY,
AES_KEY_ASCII, AX_FP_KEY, XDATA_KEY, AX_API_SIG_KEY, ENCRYPTED_FIELD_KEY
```

Saya tidak bisa mengambil nilai-nilai ini untukmu — nilainya hanya dibagikan
di channel itu dan harus kamu salin sendiri.

## 3. Deploy ke Hugging Face Spaces (gratis, tanpa kartu)

1. Daftar/login di [huggingface.co](https://huggingface.co) (bisa pakai akun GitHub).
2. **New Space** → nama `xl-pulsa-bot`, SDK **Docker**, hardware **CPU basic (gratis)**.
3. Upload semua file folder ini ke Space (atau push via git).
4. Di Space **Settings → Variables and secrets**, tambahkan sebagai **Secret**:
   `BOT_TOKEN`, `WEBHOOK_URL` (URL Space-mu, mis.
   `https://dananksparda-xl-pulsa-bot.hf.space`), dan semua variabel API XL
   dari langkah 2.
5. Tunggu build selesai (status Running), lalu buka
   `https://&lt;space-mu&gt;.hf.space/setwebhook` di browser — halaman itu
   memasang webhook ke Telegram.
6. Chat bot-mu di Telegram, kirim `/start`.

## 3b. Deploy ke Render (gratis, tapi minta kartu)

1. Push folder ini ke repo GitHub milikmu.
2. Buka [dashboard.render.com](https://dashboard.render.com) → **New +** →
   **Web Service** → pilih repo ini. Atau pakai **New + → Blueprint** dan
   pilih repo ini (file `render.yaml` sudah disiapkan).
3. Pilih plan **Free** — Render tetap meminta kartu untuk verifikasi identitas
   sebelum service dibuat, walau gratis.
4. Di **Environment Variables**, isi `BOT_TOKEN` dan semua variabel API XL
   dari langkah 2.
5. Deploy. Render memberi URL seperti `https://xl-pulsa-bot.onrender.com`.
   Bot otomatis memasang webhook ke URL itu saat start (pakai
   `RENDER_EXTERNAL_URL` bawaan Render).
6. Chat bot-mu di Telegram, kirim `/start`.

## Catatan penting

- **Space gratis tidur kalau lama tidak dipakai.** Pesan pertama setelah
  tidur bisa telat sampai Space bangun. Telegram akan mengirim ulang update
  yang gagal, jadi perintah biasanya tetap diproses — hanya lambat di awal.
- **Sesi login tidak awet di free tier — kecuali pakai trik Secret.** Token XL
  disimpan di `sessions.json` di disk Space, dan disk Space gratis itu
  ephemeral: tiap restart/rebuild, file hilang. Kalau `XL_REFRESH_TOKEN`
  (plus `XL_NUMBER` dan `XL_SUBSCRIBER_ID`) diisi sebagai Secret,
  bot memulihkan sesi dari sana dan `/cek` tetap jalan tanpa OTP — lihat
  bagian "OTP cuma sekali" di atas.
- **`ax.fp` ikut terhapus tiap restart.** File fingerprint ini dibuat ulang
  otomatis saat bot jalan, tapi fingerprint baru bisa membuat sesi XL lama
  tidak dikenali — kalau `/cek` gagal setelah restart, `/login` ulang sekali,
  lalu perbarui Secret dengan `/token` yang baru.
- **Ini klien tidak resmi** yang memakai API internal aplikasi myXL. XL bisa
  mengubah API-nya sewaktu-waktu (bot jadi error) atau membatasi akun yang
  login dari klien tidak resmi. Pakai untuk nomor sendiri, jangan untuk
  layanan komersial, dan jangan bagikan token/OTP ke siapa pun.
- Jangan pernah commit `.env`, `sessions.json`, atau `ax.fp` ke GitHub
  (sudah ada di `.gitignore`).

## Jalankan lokal (opsional)

```bash
cp .env.example .env   # lalu isi
pip install -r requirements.txt
python bot.py          # jalan di http://localhost:5000
```

Untuk menerima update Telegram secara lokal, set `WEBHOOK_URL` ke URL publik
(misalnya via ngrok) lalu restart — atau ganti webhook dengan polling
sementara untuk tes.
