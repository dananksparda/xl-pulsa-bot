"""Bot Telegram cek pulsa & kuota XL (myXL) — webhook, siap deploy di Render free tier.

Sumber API XL: https://github.com/purplemashu/me-cli-sunset
Modul klien XL di folder xlclient/ adalah salinan minimal dari repo tersebut
(ciam.py, engsel.py, encrypt.py, crypto_helper.py) — hanya bagian login OTP,
profil, pulsa, dan kuota yang dipakai bot ini.

Cara kerja:
- /login 628xxxx -> bot minta OTP ke nomor itu (SMS dari XL)
- /otp 123456   -> bot tukar OTP jadi token, disimpan per chat id
- /cek          -> pulsa + masa aktif + ringkasan kuota
- /paket        -> detail semua paket/kuota aktif
- /logout       -> hapus sesi

Token disimpan di sessions.json. PERHATIAN: filesystem Render free tier itu
ephemeral — tiap restart/deploy, file ini hilang dan pengguna harus /login lagi.
Itu trade-off hosting gratis; kalau mau sesi awet, pakai Render Disk (berbayar)
atau simpan token di database eksternal.
"""

import html
import json
import os
import threading
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from xlclient.ciam import get_new_token, get_otp, submit_otp
from xlclient.engsel import get_balance, get_my_packages, get_profile

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
XL_API_KEY = "Noir1"  # sama seperti ensure_api_key() di me-cli-sunset

SESSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.json")
_lock = threading.Lock()
_pending_otp = {}  # chat_id -> {"number": str, "subscriber_id": str}

# Sesi cadangan dari environment variable — supaya bot tetap bisa /cek tanpa
# OTP setelah Render restart (sessions.json di free tier ikut terhapus).
# Isi sekali setelah login pertama (lihat perintah /token):
#   XL_NUMBER=628xxxxxxxxxx  XL_REFRESH_TOKEN=...  XL_SUBSCRIBER_ID=... (opsional)
ENV_NUMBER = os.getenv("XL_NUMBER", "").strip()
ENV_REFRESH_TOKEN = os.getenv("XL_REFRESH_TOKEN", "").strip()
ENV_SUBSCRIBER_ID = os.getenv("XL_SUBSCRIBER_ID", "").strip()

app = Flask(__name__)


# ---------- penyimpanan sesi ----------

def load_sessions():
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_sessions(sessions):
    tmp = SESSIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)
    os.replace(tmp, SESSIONS_FILE)


# ---------- Telegram API ----------

def send_message(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"[sendMessage gagal] {e}")


# ---------- format ----------

def fmt_rupiah(n):
    try:
        return "Rp " + f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp -"


def fmt_bytes(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    for unit, div in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def fmt_date(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return "-"


# ---------- XL ----------

def refresh_session(session):
    """Tukar refresh token jadi token baru. Raise ValueError kalau gagal."""
    tokens = get_new_token(
        XL_API_KEY,
        session["tokens"]["refresh_token"],
        session.get("subscriber_id", ""),
    )
    if not tokens or "access_token" not in tokens:
        raise ValueError("Token tidak bisa diperbarui, silakan /login lagi.")
    session["tokens"] = tokens
    session["last_refresh"] = int(time.time())
    return session


def get_session(chat_id):
    with _lock:
        sessions = load_sessions()
        session = sessions.get(str(chat_id))
    if not session and ENV_NUMBER and ENV_REFRESH_TOKEN:
        # Tidak ada sesi tersimpan (mis. Render baru restart): pulihkan dari env.
        print("[sesi] memulihkan sesi dari XL_REFRESH_TOKEN (env)")
        session = {
            "number": int(ENV_NUMBER),
            "subscriber_id": ENV_SUBSCRIBER_ID,
            "subscription_type": "PREPAID",
            "tokens": {"refresh_token": ENV_REFRESH_TOKEN},
            "last_refresh": 0,
        }
    if not session:
        return None, "Kamu belum login. Kirim /login 628xxxxxxxxxx dulu."
    try:
        if int(time.time()) - int(session.get("last_refresh", 0)) > 300:
            session = refresh_session(session)
            with _lock:
                sessions = load_sessions()
                sessions[str(chat_id)] = session
                save_sessions(sessions)
    except Exception as e:
        print(f"[refresh gagal] {e}")
        return None, "Sesi sudah kedaluwarsa. Silakan /login lagi."
    return session, None


def build_cek_text(session):
    id_token = session["tokens"]["id_token"]
    balance = get_balance(XL_API_KEY, id_token)
    if not balance:
        return "Gagal mengambil pulsa. Coba lagi sebentar, atau /login ulang."
    lines = [
        f"📱 <b>{html.escape(str(session['number']))}</b> ({html.escape(session.get('subscription_type', ''))})",
        f"💰 Pulsa: <b>{fmt_rupiah(balance.get('remaining'))}</b>",
        f"📅 Aktif sampai: <b>{fmt_date(balance.get('expired_at'))}</b>",
        "",
        "<b>Kuota:</b>",
    ]
    data = get_my_packages(XL_API_KEY, id_token)
    quotas = (data or {}).get("quotas", []) if isinstance(data, dict) else []
    if not quotas:
        lines.append("- (tidak ada paket aktif / gagal memuat)")
    for q in quotas[:10]:
        for b in (q.get("benefits") or [])[:6]:
            name = html.escape(str(b.get("name", q.get("name", ""))))
            if b.get("data_type") == "DATA":
                lines.append(f"• {name}: {fmt_bytes(b.get('remaining'))} / {fmt_bytes(b.get('total'))}")
            elif b.get("data_type") == "VOICE":
                try:
                    lines.append(f"• {name}: {float(b.get('remaining', 0)) / 60:.0f} / {float(b.get('total', 0)) / 60:.0f} menit")
                except (TypeError, ValueError):
                    pass
            elif b.get("data_type") == "TEXT":
                lines.append(f"• {name}: {b.get('remaining')} / {b.get('total')} SMS")
    return "\n".join(lines)


# ---------- command ----------

HELP = (
    "👋 <b>Bot Cek Pulsa XL</b>\n\n"
    "/login 628xxxxxxxxxx — kirim OTP ke nomormu (cukup sekali)\n"
    "/otp 123456 — masukkan kode OTP dari SMS\n"
    "/cek — lihat pulsa, masa aktif & kuota\n"
    "/paket — detail semua paket aktif\n"
    "/token — tampilkan refresh token (untuk disimpan di Render)\n"
    "/logout — hapus sesi login\n\n"
    "OTP hanya perlu sekali saat login pertama. Setelah itu /cek pakai token\n"
    "yang tersimpan — tanpa OTP lagi, sampai tokennya mati."
)


def handle_message(chat_id, text):
    text = (text or "").strip()
    if not text:
        return
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/start":
        send_message(chat_id, HELP)
        return

    if cmd == "/login":
        number = arg.strip().replace("+", "").replace(" ", "").replace("-", "")
        if not number.startswith("628") or len(number) > 14:
            send_message(chat_id, "Nomor tidak valid. Contoh: /login 6281234567890")
            return
        send_message(chat_id, f"⏳ Mengirim OTP ke {html.escape(number)}...")
        try:
            subscriber_id = get_otp(number)
        except Exception as e:
            print(f"[get_otp gagal] {e}")
            subscriber_id = None
        if not subscriber_id:
            send_message(chat_id, "❌ Gagal mengirim OTP. Periksa nomornya dan coba lagi.")
            return
        _pending_otp[str(chat_id)] = {"number": number, "subscriber_id": subscriber_id}
        send_message(chat_id, "📩 OTP sudah dikirim via SMS. Balas dengan /otp 123456")
        return

    if cmd == "/otp":
        pending = _pending_otp.get(str(chat_id))
        if not pending:
            send_message(chat_id, "Tidak ada OTP yang menunggu. Kirim /login 628xxxxxxxxxx dulu.")
            return
        code = arg.strip()
        if len(code) != 6 or not code.isdigit():
            send_message(chat_id, "Kode OTP harus 6 digit. Contoh: /otp 123456")
            return
        send_message(chat_id, "⏳ Memverifikasi OTP...")
        try:
            tokens = submit_otp(XL_API_KEY, "SMS", pending["number"], code)
        except Exception as e:
            print(f"[submit_otp gagal] {e}")
            tokens = None
        if not tokens or "access_token" not in tokens:
            send_message(chat_id, "❌ OTP salah / kedaluwarsa. Kirim /login lagi untuk OTP baru.")
            return
        try:
            profile = get_profile(XL_API_KEY, tokens["access_token"], tokens["id_token"])
            prof = (profile or {}).get("profile", {}) or {}
        except Exception as e:
            print(f"[get_profile gagal] {e}")
            prof = {}
        session = {
            "number": int(pending["number"]),
            "subscriber_id": prof.get("subscriber_id", pending["subscriber_id"]),
            "subscription_type": prof.get("subscription_type", "PREPAID"),
            "tokens": tokens,
            "last_refresh": int(time.time()),
        }
        with _lock:
            sessions = load_sessions()
            sessions[str(chat_id)] = session
            save_sessions(sessions)
        _pending_otp.pop(str(chat_id), None)
        send_message(chat_id, f"✅ Login berhasil! Nomor {html.escape(pending['number'])}.\nKirim /cek untuk lihat pulsa.")
        return

    if cmd == "/cek":
        session, err = get_session(chat_id)
        if err:
            send_message(chat_id, err)
            return
        try:
            send_message(chat_id, build_cek_text(session))
        except Exception as e:
            print(f"[/cek gagal] {e}")
            send_message(chat_id, "❌ Gagal mengambil data. Coba lagi, atau /login ulang.")
        return

    if cmd == "/paket":
        session, err = get_session(chat_id)
        if err:
            send_message(chat_id, err)
            return
        try:
            id_token = session["tokens"]["id_token"]
            data = get_my_packages(XL_API_KEY, id_token)
            quotas = (data or {}).get("quotas", []) if isinstance(data, dict) else []
            if not quotas:
                send_message(chat_id, "Tidak ada paket aktif.")
                return
            out = ["<b>📦 Paket Saya:</b>"]
            for q in quotas:
                out.append(f"\n<b>{html.escape(str(q.get('name', '')))}</b>")
                for b in q.get("benefits") or []:
                    name = html.escape(str(b.get("name", "")))
                    if b.get("data_type") == "DATA":
                        out.append(f"• {name}: {fmt_bytes(b.get('remaining'))} / {fmt_bytes(b.get('total'))}")
                    else:
                        out.append(f"• {name}: {b.get('remaining')} / {b.get('total')}")
            send_message(chat_id, "\n".join(out))
        except Exception as e:
            print(f"[/paket gagal] {e}")
            send_message(chat_id, "❌ Gagal mengambil paket. Coba lagi, atau /login ulang.")
        return

    if cmd == "/token":
        session, err = get_session(chat_id)
        if err:
            send_message(chat_id, err)
            return
        rt = (session.get("tokens") or {}).get("refresh_token", "")
        if not rt:
            send_message(chat_id, "Tidak ada refresh token. Silakan /login dulu.")
            return
        send_message(
            chat_id,
            "🔑 <b>Refresh token</b> untuk nomor "
            f"{html.escape(str(session['number']))}:\n\n<code>{html.escape(rt)}</code>\n\n"
            "Salin ini ke Environment Variables di Render sebagai "
            "<b>XL_REFRESH_TOKEN</b>, plus:\n"
            f"XL_NUMBER=<code>{html.escape(str(session['number']))}</code>\n"
            f"XL_SUBSCRIBER_ID=<code>{html.escape(str(session.get('subscriber_id', '')))}</code>\n\n"
            "Supaya bot tetap bisa /cek tanpa OTP walau Render restart.\n\n"
            "⚠️ Token ini sama kuatnya dengan password — jangan dibagikan ke siapa pun, "
            "dan hapus pesan ini setelah disalin.",
        )
        return

    if cmd == "/logout":
        with _lock:
            sessions = load_sessions()
            sessions.pop(str(chat_id), None)
            save_sessions(sessions)
        _pending_otp.pop(str(chat_id), None)
        send_message(chat_id, "👋 Sesi dihapus. Kirim /login untuk masuk lagi.")
        return

    send_message(chat_id, "Perintah tidak dikenal.\n\n" + HELP)


# ---------- webhook ----------

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": "xl-pulsa-bot"})


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text", "")
    if chat_id and text:
        threading.Thread(target=handle_message, args=(chat_id, text), daemon=True).start()
    return jsonify({"ok": True})


def set_webhook():
    base = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
    if not BOT_TOKEN or not base:
        print("[webhook] BOT_TOKEN / WEBHOOK_URL belum diset, webhook tidak dipasang.")
        return
    url = base.rstrip("/") + "/webhook"
    try:
        r = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": url, "allowed_updates": ["message"]},
            timeout=20,
        )
        print(f"[webhook] setWebhook {url} -> {r.status_code} {r.text[:200]}")
    except requests.RequestException as e:
        print(f"[webhook gagal] {e}")


if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
