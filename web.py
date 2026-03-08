"""
FanBot Web Dashboard
Run: python dashboard.py
Access: http://localhost:5000
"""

import base64
import io
import ipaddress
import json
import os
import re
import secrets
import signal
import subprocess
import sys
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import bcrypt
import pyotp
import qrcode
from flask import Flask, abort, g, jsonify, make_response, redirect, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "bot_config.json"
CONVOS_FILE = BASE_DIR / "conversations_log.json"
SCHED_FILE  = BASE_DIR / "schedule.json"
NOTES_FILE  = BASE_DIR / "notes.json"
PID_FILE           = BASE_DIR / "bot.pid"
BOT_LOG            = BASE_DIR / "bot.log"
AUTH_STATE_FILE    = BASE_DIR / "auth_state.json"
AUTH_RESPONSE_FILE = BASE_DIR / "auth_response.txt"
USERS_FILE         = BASE_DIR / "users.json"
INVITES_FILE       = BASE_DIR / "invites.json"
BREAKS_FILE        = BASE_DIR / "manual_breaks.json"
FCM_TOKENS_FILE    = BASE_DIR / "fcm_tokens.json"

import prompt_conf

_DEFAULT_CONFIG = {
    "system_prompt":            prompt_conf.GUIDE_PROMPT.strip(),
    "window_start_hour":        1,
    "window_end_hour":          23,
    "window_jitter_min_minutes": 10,
    "window_jitter_max_minutes": 75,
    "reply_delay_mode":         "range",
    "reply_delay_min":          3,
    "reply_delay_max":          5,
    "typing_wpm":               40,
    "force_inactive":           False,
    "muted_users":              [],
    "pushbullet_api_key":       "",
    "notify_new_chatter":       True,
    "notify_message_threshold": 5,
    "notify_owner_name":        "Matheesha",
    "timezone":                 "Asia/Colombo",
    "recheck_enabled":          True,
    "recheck_accuracy":         80,
    "reply_temperature":        0.9,
    "reply_max_tokens":         80,
    "recheck_temperature":      0.5,
    "recheck_max_tokens":       100,
    "dashboard_api_key":        "",
    "fcm_service_account":       "",
}

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", secrets.token_hex(32))

# ---------------------------------------------------------------------------
# Tailscale-only access restriction
# ---------------------------------------------------------------------------
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
_PRIVATE_RANGE = ipaddress.ip_network("192.168.0.0/16")


@app.before_request
def _restrict_to_tailscale():
    """Allow Tailscale/loopback addresses, or requests bearing a valid X-API-Key."""
    g.api_key_auth = False

    # Check API key first — allows access from any network if the key is correct
    api_key = read_config().get("dashboard_api_key", "").strip()
    if api_key:
        provided = request.headers.get("X-API-Key", "").strip()
        if provided and secrets.compare_digest(provided, api_key):
            g.api_key_auth = True
            return  # valid key — allow

    # Fall back to network-based check
    raw = request.remote_addr or ""
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        abort(403)
    if not (addr.is_loopback or addr in _TAILSCALE_NET or addr in _PRIVATE_RANGE):
        abort(403)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "page_login"


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "unauthenticated"}), 401
    return redirect(url_for("page_login"))

# ---------------------------------------------------------------------------
# Permission definitions
# ---------------------------------------------------------------------------
ALL_PERMISSIONS = [
    "view_overview",
    "view_conversations",
    "mute_users",
    "view_prompt",
    "edit_prompt",
    "view_config",
    "edit_config",
    "view_analytics",
    "view_notes",
    "edit_notes",
    "bot_control",
    "manage_users",
]

ADMIN_PERMISSIONS = ALL_PERMISSIONS  # admin always gets everything


# ---------------------------------------------------------------------------
# User store helpers
# ---------------------------------------------------------------------------

def _read_users() -> dict:
    try:
        if USERS_FILE.exists():
            with open(USERS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_users(data: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _read_invites() -> dict:
    try:
        if INVITES_FILE.exists():
            with open(INVITES_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_invites(data: dict):
    with open(INVITES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _is_first_user() -> bool:
    return len(_read_users()) == 0


def _read_breaks() -> dict:
    if BREAKS_FILE.exists():
        try:
            with open(BREAKS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_breaks(data: dict):
    with open(BREAKS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _read_fcm_tokens() -> dict:
    try:
        if FCM_TOKENS_FILE.exists():
            with open(FCM_TOKENS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_fcm_tokens(data: dict):
    with open(FCM_TOKENS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Flask-Login User class
# ---------------------------------------------------------------------------

class DashUser(UserMixin):
    def __init__(self, uid: str, record: dict):
        self.id          = uid
        self.username    = record.get("username", uid)
        self.role        = record.get("role", "user")
        self.permissions = record.get("permissions", [])
        if self.role == "admin":
            self.permissions = ADMIN_PERMISSIONS

    def has_perm(self, perm: str) -> bool:
        if self.role == "admin":
            return True
        return perm in self.permissions

    def to_dict(self):
        return {
            "id":          self.id,
            "username":    self.username,
            "role":        self.role,
            "permissions": ADMIN_PERMISSIONS if self.role == "admin" else self.permissions,
        }


@login_manager.user_loader
def load_user(uid: str):
    users = _read_users()
    if uid in users:
        return DashUser(uid, users[uid])
    return None


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def perm_required(perm: str):
    """Decorator: JSON 403 if user lacks a permission.
    API-key-authenticated requests bypass all permission checks.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "api_key_auth", False):
                return fn(*args, **kwargs)
            if not current_user.is_authenticated:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "unauthenticated"}), 401
                return redirect(url_for("page_login"))
            if not current_user.has_perm(perm):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def read_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                return {**_DEFAULT_CONFIG, **json.load(f)}
    except Exception:
        pass
    return _DEFAULT_CONFIG.copy()


def write_config(patch: dict):
    merged = {**read_config(), **patch}
    with open(CONFIG_FILE, "w") as f:
        json.dump(merged, f, indent=2)


def read_convos() -> dict:
    try:
        if CONVOS_FILE.exists():
            with open(CONVOS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"users": {}, "daily_counts": {}, "hourly_counts": {},
            "total_messages": 0, "total_replies": 0}


def read_notes() -> list:
    try:
        if NOTES_FILE.exists():
            with open(NOTES_FILE) as f:
                return json.load(f).get("notes", [])
    except Exception:
        pass
    return []


def write_notes(notes: list):
    with open(NOTES_FILE, "w") as f:
        json.dump({"notes": notes}, f, indent=2)


# ---------------------------------------------------------------------------
# Bot process management
# ---------------------------------------------------------------------------

def _bot_pid() -> int | None:
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except Exception:
        pass
    return None


def is_bot_running() -> bool:
    pid = _bot_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False


def start_bot() -> tuple[bool, str]:
    if is_bot_running():
        return False, "Bot is already running"
    try:
        log_f = open(BOT_LOG, "a")
        proc  = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "telegram-user.py")],
            cwd=str(BASE_DIR),
            stdout=log_f,
            stderr=log_f,
        )
        PID_FILE.write_text(str(proc.pid))
        return True, f"Bot started (PID {proc.pid})"
    except Exception as e:
        return False, str(e)


def stop_bot() -> tuple[bool, str]:
    pid = _bot_pid()
    if pid is None or not is_bot_running():
        PID_FILE.unlink(missing_ok=True)
        return False, "Bot is not running"
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        return True, f"Bot stopped (PID {pid})"
    except Exception as e:
        return False, str(e)


# Seed default config on first run
if not CONFIG_FILE.exists():
    write_config(_DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# API — dashboard auth (login / register / 2FA)
# ---------------------------------------------------------------------------

@app.route("/login")
def page_login():
    if current_user.is_authenticated:
        return redirect("/")
    return _AUTH_HTML


@app.route("/api/dash/register", methods=["POST"])
def api_register():
    data     = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    code     = (data.get("invite_code") or "").strip()

    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required"}), 400
    if not re.match(r'^[a-z0-9_]{3,32}$', username):
        return jsonify({"ok": False, "error": "Username must be 3-32 chars, letters/numbers/underscore only"}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters"}), 400

    users      = _read_users()
    first_user = len(users) == 0

    if not first_user:
        invites = _read_invites()
        if not code or code not in invites:
            return jsonify({"ok": False, "error": "A valid invitation code is required"}), 403
        invite = invites[code]
        if invite.get("used"):
            return jsonify({"ok": False, "error": "This invitation code has already been used"}), 403
        permissions = invite.get("permissions", [])
    else:
        permissions = ADMIN_PERMISSIONS

    if any(u["username"] == username for u in users.values()):
        return jsonify({"ok": False, "error": "Username already taken"}), 409

    hashed  = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    uid     = secrets.token_hex(12)
    totp_secret = pyotp.random_base32()

    users[uid] = {
        "username":    username,
        "password":    hashed,
        "role":        "admin" if first_user else "user",
        "permissions": ADMIN_PERMISSIONS if first_user else permissions,
        "totp_secret": totp_secret,
        "totp_enabled": False,
        "created_at":  datetime.utcnow().isoformat(),
    }
    _write_users(users)

    if not first_user:
        invites[code]["used"] = True
        invites[code]["used_by"] = username
        invites[code]["used_at"] = datetime.utcnow().isoformat()
        _write_invites(invites)

    # Return TOTP provisioning URI so frontend can show QR code for setup
    otp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=username, issuer_name="FanBot Dashboard"
    )
    qr_img  = qrcode.make(otp_uri, box_size=6, border=2)
    buf     = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64  = base64.b64encode(buf.getvalue()).decode()

    return jsonify({
        "ok":         True,
        "uid":        uid,
        "totp_secret": totp_secret,
        "totp_uri":   otp_uri,
        "qr_b64":     qr_b64,
        "is_admin":   first_user,
    })


@app.route("/api/dash/setup-2fa", methods=["POST"])
def api_setup_2fa():
    """Confirm TOTP code to activate 2FA after registration."""
    data  = request.get_json(force=True) or {}
    uid   = (data.get("uid") or "").strip()
    token = (data.get("token") or "").strip()

    users = _read_users()
    if uid not in users:
        return jsonify({"ok": False, "error": "User not found"}), 404

    user = users[uid]
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(token, valid_window=1):
        return jsonify({"ok": False, "error": "Invalid code — check your authenticator app"}), 400

    user["totp_enabled"] = True
    _write_users(users)

    # Log the user in
    dash_user = DashUser(uid, user)
    login_user(dash_user, remember=True)
    return jsonify({"ok": True})


@app.route("/api/dash/login", methods=["POST"])
def api_login():
    data     = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    token    = (data.get("totp") or "").strip()

    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required"}), 400

    users = _read_users()
    uid, record = next(
        ((uid, u) for uid, u in users.items() if u["username"] == username), (None, None)
    )
    if not uid or not bcrypt.checkpw(password.encode(), record["password"].encode()):
        return jsonify({"ok": False, "error": "Invalid username or password"}), 401

    if record.get("totp_enabled"):
        if not token:
            return jsonify({"ok": False, "needs_totp": True}), 200
        totp = pyotp.TOTP(record["totp_secret"])
        if not totp.verify(token, valid_window=1):
            return jsonify({"ok": False, "error": "Invalid 2FA code"}), 401

    dash_user = DashUser(uid, record)
    login_user(dash_user, remember=True)
    return jsonify({"ok": True, "user": dash_user.to_dict()})


@app.route("/api/dash/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/dash/me")
def api_me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": current_user.to_dict()})


# ---------------------------------------------------------------------------
# API — invite codes
# ---------------------------------------------------------------------------

@app.route("/api/invites", methods=["GET"])
@perm_required("manage_users")
def api_invites_get():
    invites = _read_invites()
    result  = []
    for code, inv in invites.items():
        result.append({
            "code":        code,
            "created_by":  inv.get("created_by", ""),
            "created_at":  inv.get("created_at", ""),
            "permissions": inv.get("permissions", []),
            "used":        inv.get("used", False),
            "used_by":     inv.get("used_by", ""),
            "used_at":     inv.get("used_at", ""),
        })
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(result)


@app.route("/api/invites", methods=["POST"])
@perm_required("manage_users")
def api_invites_post():
    data        = request.get_json(force=True) or {}
    permissions = data.get("permissions", [])
    # Validate permissions
    permissions = [p for p in permissions if p in ALL_PERMISSIONS]

    code    = secrets.token_urlsafe(12)
    invites = _read_invites()
    invites[code] = {
        "created_by":  current_user.username,
        "created_at":  datetime.utcnow().isoformat(),
        "permissions": permissions,
        "used":        False,
    }
    _write_invites(invites)
    return jsonify({"ok": True, "code": code, "permissions": permissions})


@app.route("/api/invites/<code>", methods=["DELETE"])
@perm_required("manage_users")
def api_invites_delete(code: str):
    invites = _read_invites()
    if code not in invites:
        return jsonify({"ok": False, "error": "not found"}), 404
    del invites[code]
    _write_invites(invites)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — user management (admin)
# ---------------------------------------------------------------------------

@app.route("/api/users", methods=["GET"])
@perm_required("manage_users")
def api_users_list():
    users  = _read_users()
    result = []
    for uid, u in users.items():
        result.append({
            "id":          uid,
            "username":    u.get("username", ""),
            "role":        u.get("role", "user"),
            "permissions": ADMIN_PERMISSIONS if u.get("role") == "admin" else u.get("permissions", []),
            "totp_enabled": u.get("totp_enabled", False),
            "created_at":  u.get("created_at", ""),
        })
    result.sort(key=lambda x: x["created_at"])
    return jsonify(result)


@app.route("/api/users/<uid>/permissions", methods=["PUT"])
@perm_required("manage_users")
def api_users_set_perms(uid: str):
    users = _read_users()
    if uid not in users:
        return jsonify({"ok": False, "error": "not found"}), 404
    if users[uid].get("role") == "admin":
        return jsonify({"ok": False, "error": "Cannot modify admin permissions"}), 400
    data = request.get_json(force=True) or {}
    perms = [p for p in data.get("permissions", []) if p in ALL_PERMISSIONS]
    users[uid]["permissions"] = perms
    _write_users(users)
    return jsonify({"ok": True})


@app.route("/api/users/<uid>", methods=["DELETE"])
@perm_required("manage_users")
def api_users_delete(uid: str):
    if uid == current_user.id:
        return jsonify({"ok": False, "error": "Cannot delete yourself"}), 400
    users = _read_users()
    if uid not in users:
        return jsonify({"ok": False, "error": "not found"}), 404
    if users[uid].get("role") == "admin":
        admin_count = sum(1 for u in users.values() if u.get("role") == "admin")
        if admin_count <= 1:
            return jsonify({"ok": False, "error": "Cannot delete the last admin"}), 400
    del users[uid]
    _write_users(users)
    return jsonify({"ok": True})


@app.route("/api/dash/change-password", methods=["POST"])
@login_required
def api_change_password():
    data     = request.get_json(force=True) or {}
    old_pass = (data.get("old_password") or "").strip()
    new_pass = (data.get("new_password") or "").strip()

    if not old_pass or not new_pass:
        return jsonify({"ok": False, "error": "Both fields are required"}), 400
    if len(new_pass) < 8:
        return jsonify({"ok": False, "error": "New password must be at least 8 characters"}), 400

    users = _read_users()
    uid   = current_user.id
    if uid not in users:
        return jsonify({"ok": False, "error": "User not found"}), 404

    if not bcrypt.checkpw(old_pass.encode(), users[uid]["password"].encode()):
        return jsonify({"ok": False, "error": "Current password is incorrect"}), 401

    users[uid]["password"] = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt()).decode()
    _write_users(users)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — FCM device token registration
# ---------------------------------------------------------------------------

@app.route("/api/device/register", methods=["POST"])
@perm_required("bot_control")
def api_device_register():
    """Register an Android FCM device token. Idempotent — re-registering updates the record."""
    data  = request.get_json(force=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token is required"}), 400
    label = (data.get("label") or "").strip()[:64]  # optional human-readable device name
    tokens = _read_fcm_tokens()
    tokens[token] = {
        "registered_at": datetime.utcnow().isoformat(),
        "label": label,
    }
    _write_fcm_tokens(tokens)
    return jsonify({"ok": True})


@app.route("/api/device/unregister", methods=["POST"])
@perm_required("bot_control")
def api_device_unregister():
    """Remove an FCM device token."""
    data  = request.get_json(force=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token is required"}), 400
    tokens = _read_fcm_tokens()
    tokens.pop(token, None)
    _write_fcm_tokens(tokens)
    return jsonify({"ok": True})


@app.route("/api/device/tokens", methods=["GET"])
@perm_required("manage_users")
def api_device_tokens():
    """List all registered FCM device tokens (admin)."""
    tokens = _read_fcm_tokens()
    return jsonify([
        {"token": t[:16] + "…", "label": v.get("label", ""), "registered_at": v.get("registered_at", "")}
        for t, v in tokens.items()
    ])


# ---------------------------------------------------------------------------
# Utility: check if any users exist (for frontend first-run detection)
# ---------------------------------------------------------------------------

@app.route("/api/dash/init-status")
def api_init_status():
    return jsonify({"has_users": not _is_first_user()})

@app.route("/api/status")
@perm_required("view_overview")
def api_status():
    convos = read_convos()
    cfg    = read_config()
    today  = date.today().isoformat()

    # Determine current window state from today's schedule file
    window_state = "unknown"
    window_next  = ""
    try:
        if SCHED_FILE.exists():
            with open(SCHED_FILE) as f:
                s = json.load(f)
            _tz_obj = ZoneInfo(cfg.get("timezone", "Asia/Colombo"))

            def _to_local(iso: str) -> datetime:
                dt = datetime.fromisoformat(iso)
                return dt.astimezone(_tz_obj) if dt.tzinfo else dt.replace(tzinfo=_tz_obj)

            now          = datetime.now(_tz_obj)
            window_start = _to_local(s["window_start"])
            window_end   = _to_local(s["window_end"])
            if cfg.get("force_inactive"):
                window_state = "force_inactive"
            elif now < window_start:
                window_state = "before_window"
                window_next  = window_start.strftime("%H:%M")
            elif now > window_end:
                window_state = "after_window"
                window_next  = (window_start + timedelta(days=1)).strftime("%H:%M")
            else:
                in_break = False
                for brk in s.get("breaks", []):
                    bs = _to_local(brk["start"])
                    be = _to_local(brk["end"])
                    if bs <= now <= be:
                        in_break    = True
                        window_next = be.strftime("%H:%M")
                        break
                window_state = "on_break" if in_break else "active"
    except Exception:
        pass

    return jsonify({
        "bot_running":    is_bot_running(),
        "force_inactive": cfg.get("force_inactive", False),
        "total_messages": convos.get("total_messages", 0),
        "total_replies":  convos.get("total_replies", 0),
        "total_users":    len(convos.get("users", {})),
        "messages_today": convos.get("daily_counts", {}).get(today, 0),
        "window_state":   window_state,
        "window_next":    window_next,
        "timezone":       cfg.get("timezone", "Asia/Colombo"),
    })


# ---------------------------------------------------------------------------
# API — bot control
# ---------------------------------------------------------------------------

@app.route("/api/bot/start", methods=["POST"])
@perm_required("bot_control")
def api_bot_start():
    ok, msg = start_bot()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/bot/stop", methods=["POST"])
@perm_required("bot_control")
def api_bot_stop():
    ok, msg = stop_bot()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/bot/restart", methods=["POST"])
@perm_required("bot_control")
def api_bot_restart():
    import time as _t
    if is_bot_running():
        stop_bot()
        _t.sleep(1.2)
    ok, msg = start_bot()
    return jsonify({"ok": ok, "message": ("Bot restarted — " + msg) if ok else msg})


# ---------------------------------------------------------------------------
# API — config
# ---------------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
@perm_required("view_config")
def api_config_get():
    return jsonify(read_config())


@app.route("/api/config", methods=["POST"])
@perm_required("edit_config")
def api_config_post():
    data    = request.get_json(force=True) or {}
    allowed = {"system_prompt", "window_start_hour", "window_end_hour",
               "window_jitter_min_minutes", "window_jitter_max_minutes",
               "reply_delay_mode", "reply_delay_min", "reply_delay_max", "typing_wpm",
               "pushbullet_api_key", "notify_new_chatter",
               "notify_message_threshold", "notify_owner_name",
               "force_inactive", "muted_users",
               "recheck_enabled", "recheck_accuracy",
               "reply_temperature", "reply_max_tokens",
               "recheck_temperature", "recheck_max_tokens",
               "timezone", "dashboard_api_key", "fcm_service_account"}
    patch   = {k: v for k, v in data.items() if k in allowed}
    cur     = read_config()
    # Regenerate daily schedule if window hours changed
    if (patch.get("window_start_hour") != cur.get("window_start_hour") or
            patch.get("window_end_hour") != cur.get("window_end_hour")):
        SCHED_FILE.unlink(missing_ok=True)
    write_config(patch)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — today's schedule
# ---------------------------------------------------------------------------

@app.route("/api/today-schedule")
@perm_required("view_config")
def api_today_schedule():
    if not SCHED_FILE.exists():
        return jsonify({"error": "no_schedule"})
    try:
        with open(SCHED_FILE) as f:
            s = json.load(f)

        def fmt(iso: str) -> str:
            return datetime.fromisoformat(iso).strftime("%H:%M")

        today_str  = s.get("date", date.today().isoformat())
        all_breaks = _read_breaks()
        day_breaks = all_breaks.get(today_str, [])
        return jsonify({
            "date":         today_str,
            "window_start": fmt(s["window_start"]),
            "window_end":   fmt(s["window_end"]),
            "breaks":       day_breaks,
        })
    except Exception as e:
        return jsonify({"error": str(e)})


# ---------------------------------------------------------------------------
# API — manual breaks
# ---------------------------------------------------------------------------

import re as _re

@app.route("/api/breaks/<date_str>", methods=["GET"])
@perm_required("view_config")
def api_get_breaks(date_str):
    try:
        date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid date"}), 400
    return jsonify(_read_breaks().get(date_str, []))


@app.route("/api/breaks/<date_str>", methods=["POST"])
@perm_required("edit_config")
def api_add_break(date_str):
    try:
        date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid date"}), 400
    body  = request.get_json(silent=True) or {}
    start = body.get("start", "").strip()
    end   = body.get("end", "").strip()
    if not _re.match(r"^\d{2}:\d{2}$", start) or not _re.match(r"^\d{2}:\d{2}$", end):
        return jsonify({"ok": False, "error": "start/end must be HH:MM"}), 400
    if start >= end:
        return jsonify({"ok": False, "error": "start must be before end"}), 400
    breaks = _read_breaks()
    day    = breaks.setdefault(date_str, [])
    day.append({"start": start, "end": end})
    day.sort(key=lambda b: b["start"])
    _write_breaks(breaks)
    return jsonify({"ok": True, "breaks": breaks[date_str]})


@app.route("/api/breaks/<date_str>/<int:idx>", methods=["DELETE"])
@perm_required("edit_config")
def api_delete_break(date_str, idx):
    try:
        date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid date"}), 400
    breaks = _read_breaks()
    day    = breaks.get(date_str, [])
    if idx < 0 or idx >= len(day):
        return jsonify({"ok": False, "error": "Index out of range"}), 400
    day.pop(idx)
    if not day:
        breaks.pop(date_str, None)
    else:
        breaks[date_str] = day
    _write_breaks(breaks)
    return jsonify({"ok": True, "breaks": breaks.get(date_str, [])})


# ---------------------------------------------------------------------------
# API — conversations
# ---------------------------------------------------------------------------

@app.route("/api/conversations")
@perm_required("view_conversations")
def api_conversations():
    convos = read_convos()
    muted  = read_config().get("muted_users", [])
    rows   = []
    for uid, info in convos.get("users", {}).items():
        last_msg = ""
        for m in reversed(info.get("messages", [])):
            if m.get("role") == "user":
                c = m.get("content", "")
                last_msg = c[:100] + ("…" if len(c) > 100 else "")
                break
        rows.append({
            "user_id":       int(uid),
            "name":          info.get("name", uid),
            "username":      info.get("username", ""),
            "message_count": info.get("message_count", 0),
            "reply_count":   info.get("reply_count", 0),
            "last_active":   info.get("last_active", ""),
            "first_seen":    info.get("first_seen", ""),
            "last_message":  last_msg,
            "muted":         int(uid) in muted,
        })
    rows.sort(key=lambda r: r["last_active"], reverse=True)
    return jsonify(rows)


@app.route("/api/conversations/<int:user_id>/toggle-mute", methods=["POST"])
@perm_required("mute_users")
def api_toggle_mute(user_id: int):
    cfg   = read_config()
    muted = list(cfg.get("muted_users", []))
    if user_id in muted:
        muted.remove(user_id)
        now_muted = False
    else:
        muted.append(user_id)
        now_muted = True
    write_config({"muted_users": muted})
    return jsonify({"ok": True, "muted": now_muted})


# ---------------------------------------------------------------------------
# API — auth (Telegram login code / 2FA password flow)
# ---------------------------------------------------------------------------

@app.route("/api/auth/status")
@perm_required("bot_control")
def api_auth_status():
    try:
        if AUTH_STATE_FILE.exists():
            with open(AUTH_STATE_FILE) as f:
                state = json.load(f)
            if state.get("step"):
                return jsonify(state)
    except Exception:
        pass
    return jsonify({"step": None, "phone": ""})


@app.route("/api/auth/submit", methods=["POST"])
@perm_required("bot_control")
def api_auth_submit():
    data  = request.get_json(force=True) or {}
    value = str(data.get("value", "")).strip()
    if not value:
        return jsonify({"ok": False, "error": "empty"})
    try:
        AUTH_RESPONSE_FILE.write_text(value)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# API — notes
# ---------------------------------------------------------------------------

@app.route("/api/notes", methods=["GET"])
@perm_required("view_notes")
def api_notes_get():
    notes = read_notes()
    notes.sort(key=lambda n: (n.get("date", ""), n.get("time", "")))
    return jsonify(notes)


@app.route("/api/notes", methods=["POST"])
@perm_required("edit_notes")
def api_notes_post():
    body    = request.get_json(force=True, silent=True) or {}
    d       = (body.get("date") or "").strip()
    t       = (body.get("time") or "").strip()
    title   = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not d or not content:
        return jsonify({"ok": False, "error": "date and content are required"}), 400
    notes = read_notes()
    note  = {
        "id":         secrets.token_hex(8),
        "date":       d,
        "time":       t,
        "title":      title,
        "content":    content,
        "created_at": datetime.now(ZoneInfo(read_config().get("timezone", "Asia/Colombo"))).isoformat(),
    }
    notes.append(note)
    write_notes(notes)
    return jsonify({"ok": True, "note": note})


@app.route("/api/notes/<note_id>", methods=["PUT"])
@perm_required("edit_notes")
def api_notes_put(note_id: str):
    body  = request.get_json(force=True, silent=True) or {}
    notes = read_notes()
    for n in notes:
        if n["id"] == note_id:
            if "date"    in body: n["date"]    = (body["date"]    or "").strip()
            if "time"    in body: n["time"]    = (body["time"]    or "").strip()
            if "title"   in body: n["title"]   = (body["title"]   or "").strip()
            if "content" in body: n["content"] = (body["content"] or "").strip()
            write_notes(notes)
            return jsonify({"ok": True, "note": n})
    return jsonify({"ok": False, "error": "not found"}), 404


@app.route("/api/notes/<note_id>", methods=["DELETE"])
@perm_required("edit_notes")
def api_notes_delete(note_id: str):
    notes  = read_notes()
    before = len(notes)
    notes  = [n for n in notes if n["id"] != note_id]
    if len(notes) == before:
        return jsonify({"ok": False, "error": "not found"}), 404
    write_notes(notes)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — analytics
# ---------------------------------------------------------------------------

@app.route("/api/analytics")
@perm_required("view_analytics")
def api_analytics():
    convos = read_convos()
    today  = date.today()

    # Last 14 days
    daily_counts = convos.get("daily_counts", {})
    daily_labels, daily_values = [], []
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        daily_labels.append(d[5:])          # MM-DD
        daily_values.append(daily_counts.get(d, 0))

    # Top chatters
    users       = convos.get("users", {})
    top_chatters = sorted(
        [{"name": v.get("name", k), "count": v.get("message_count", 0)}
         for k, v in users.items()],
        key=lambda x: x["count"], reverse=True
    )[:8]

    # Hourly distribution
    hourly      = convos.get("hourly_counts", {})
    hourly_labels = [f"{h:02d}:00" for h in range(24)]
    hourly_values = [hourly.get(str(h), 0) for h in range(24)]

    # Summary stats
    total_msgs    = convos.get("total_messages", 0)
    total_replies = convos.get("total_replies", 0)
    active_days   = sum(1 for v in daily_counts.values() if v > 0)
    avg_per_day   = round(total_msgs / active_days, 1) if active_days else 0
    top_user      = top_chatters[0] if top_chatters else {"name": "—", "count": 0}
    peak_h        = hourly_values.index(max(hourly_values)) if any(hourly_values) else None

    # New users today
    new_today = sum(
        1 for u in users.values()
        if u.get("first_seen", "")[:10] == today.isoformat()
    )

    return jsonify({
        "daily_labels":  daily_labels,
        "daily_values":  daily_values,
        "top_chatters":  top_chatters,
        "hourly_labels": hourly_labels,
        "hourly_values": hourly_values,
        "summary": {
            "total_messages":  total_msgs,
            "total_replies":   total_replies,
            "total_users":     len(users),
            "avg_per_day":     avg_per_day,
            "top_user":        top_user["name"],
            "top_user_count":  top_user["count"],
            "peak_hour":       f"{peak_h:02d}:00" if peak_h is not None else "—",
            "response_rate":   round(total_replies / total_msgs * 100, 1) if total_msgs else 0,
            "new_today":       new_today,
        },
    })


# ---------------------------------------------------------------------------
# Auth / Login HTML
# ---------------------------------------------------------------------------

_AUTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FanBot — Sign In</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#08090d;--surface:#10121a;--surface2:#181b27;--border:#222540;--accent:#a855f7;--accent2:#ec4899;--text:#f0f2f8;--muted:#5a6480;--success:#34d399;--danger:#f87171;--warn:#fbbf24;--r:12px}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;font-size:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:40px 36px;width:420px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.5)}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:28px}
.brand-dot{width:10px;height:10px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 12px var(--accent)}
.brand-name{font-size:16px;font-weight:700;letter-spacing:-.3px}
h2{font-size:22px;font-weight:800;margin-bottom:6px}
.sub{color:var(--muted);font-size:13px;margin-bottom:28px;line-height:1.6}
.label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px}
.inp{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;color:var(--text);font-size:14px;outline:none;transition:border-color .2s;margin-bottom:14px}
.inp:focus{border-color:var(--accent)}
.inp::placeholder{color:var(--muted)}
.btn{width:100%;padding:13px;border-radius:10px;border:none;cursor:pointer;font-size:14px;font-weight:700;transition:.18s all;margin-top:4px}
.btn:active{transform:scale(.98)}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 2px 16px rgba(168,85,247,.3)}
.btn-primary:hover{opacity:.88}
.btn-ghost{background:var(--surface2);color:var(--muted);border:1px solid var(--border);margin-top:12px}
.btn-ghost:hover{color:var(--text);border-color:var(--accent)}
.err{color:var(--danger);font-size:12px;min-height:20px;margin-top:8px;text-align:center}
.ok-msg{color:var(--success);font-size:12px;min-height:20px;margin-top:8px;text-align:center}
.divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:var(--muted);font-size:12px}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--border)}
.qr-wrap{text-align:center;margin:16px 0}
.qr-wrap img{border-radius:10px;border:3px solid var(--border)}
.secret-box{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-family:monospace;font-size:13px;letter-spacing:2px;word-break:break-all;text-align:center;color:var(--accent);margin:10px 0 16px}
.perm-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:10px 0 18px}
.perm-item{display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;cursor:pointer;transition:.15s;font-size:12px;font-weight:500}
.perm-item:hover{border-color:var(--accent);color:var(--text)}
.perm-item input[type=checkbox]{accent-color:var(--accent);width:14px;height:14px;flex-shrink:0}
.tab-btns{display:flex;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:3px;margin-bottom:28px}
.tab-btn{flex:1;padding:8px;border:none;border-radius:8px;background:none;color:var(--muted);font-size:13px;font-weight:600;cursor:pointer;transition:.15s}
.tab-btn.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.hidden{display:none}
</style>
</head>
<body>
<div class="card">
  <div class="brand"><span class="brand-dot"></span><span class="brand-name">FanBot Panel</span></div>

  <!-- Tab toggle (only shown when users exist) -->
  <div class="tab-btns" id="tab-toggle">
    <button class="tab-btn active" onclick="showTab('login')">Sign In</button>
    <button class="tab-btn" onclick="showTab('register')">Register</button>
  </div>

  <!-- ── Login form ── -->
  <div id="pane-login">
    <h2>Welcome back</h2>
    <div class="sub" id="login-sub">Sign in to your dashboard account</div>
    <div class="label">Username</div>
    <input class="inp" id="l-user" type="text" placeholder="username" autocomplete="username" autocapitalize="none">
    <div class="label">Password</div>
    <input class="inp" id="l-pass" type="password" placeholder="••••••••" autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()">
    <div id="totp-wrap" class="hidden">
      <div class="label">Authenticator Code</div>
      <input class="inp" id="l-totp" type="text" inputmode="numeric" placeholder="6-digit code" maxlength="6" onkeydown="if(event.key==='Enter')doLogin()">
    </div>
    <button class="btn btn-primary" onclick="doLogin()">Sign In</button>
    <div class="err" id="l-err"></div>
  </div>

  <!-- ── Register form ── -->
  <div id="pane-register" class="hidden">
    <h2 id="reg-title">Create Account</h2>
    <div class="sub" id="reg-sub">Register to access the dashboard</div>
    <div id="invite-row">
      <div class="label">Invitation Code</div>
      <input class="inp" id="r-code" type="text" placeholder="Paste your invitation code" autocomplete="off">
    </div>
    <div class="label">Username</div>
    <input class="inp" id="r-user" type="text" placeholder="3–32 chars, no spaces" autocomplete="username" autocapitalize="none">
    <div class="label">Password</div>
    <input class="inp" id="r-pass" type="password" placeholder="Min 8 characters" autocomplete="new-password">
    <div class="label">Confirm Password</div>
    <input class="inp" id="r-pass2" type="password" placeholder="Repeat password" autocomplete="new-password" onkeydown="if(event.key==='Enter')doRegister()">
    <button class="btn btn-primary" onclick="doRegister()">Create Account</button>
    <div class="err" id="r-err"></div>
  </div>

  <!-- ── 2FA Setup pane (after register) ── -->
  <div id="pane-2fa" class="hidden">
    <h2>Set Up 2FA</h2>
    <div class="sub">Scan this QR code with <strong>Google Authenticator</strong> or any TOTP app, then enter the 6-digit code to confirm.</div>
    <div class="qr-wrap"><img id="qr-img" src="" alt="QR Code" width="180" height="180"></div>
    <div style="font-size:11px;color:var(--muted);text-align:center;margin-bottom:4px">Or enter the secret key manually:</div>
    <div class="secret-box" id="totp-secret-display"></div>
    <div class="label">Verification Code</div>
    <input class="inp" id="setup-code" type="text" inputmode="numeric" placeholder="6-digit code" maxlength="6" onkeydown="if(event.key==='Enter')doSetup2FA()">
    <button class="btn btn-primary" onclick="doSetup2FA()">Verify &amp; Sign In</button>
    <div class="err" id="setup-err"></div>
  </div>
</div>

<script>
let _pendingUid = null;
let _hasUsers   = false;

async function init() {
  const r = await fetch('/api/dash/init-status').then(x=>x.json()).catch(()=>null);
  _hasUsers = r?.has_users ?? false;
  if (!_hasUsers) {
    // First run — go straight to register, hide tab toggle
    document.getElementById('tab-toggle').style.display = 'none';
    document.getElementById('reg-title').textContent    = 'Create Admin Account';
    document.getElementById('reg-sub').textContent      = 'You are the first user — you will become the admin.';
    document.getElementById('invite-row').style.display = 'none';
    showTab('register');
  }
}
init();

function showTab(t) {
  ['login','register','2fa'].forEach(p => {
    document.getElementById('pane-'+p).classList.toggle('hidden', p !== t);
  });
  document.querySelectorAll('.tab-btn').forEach((b,i) => {
    b.classList.toggle('active', (i===0&&t==='login')||(i===1&&t==='register'));
  });
}

async function doLogin() {
  const user  = document.getElementById('l-user').value.trim();
  const pass  = document.getElementById('l-pass').value;
  const totp  = document.getElementById('l-totp').value.trim();
  const errEl = document.getElementById('l-err');
  errEl.textContent = '';
  if (!user || !pass) { errEl.textContent = 'Enter username and password'; return; }
  const r = await fetch('/api/dash/login', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({username: user, password: pass, totp: totp}),
  }).then(x=>x.json()).catch(()=>null);
  if (!r) { errEl.textContent = 'Network error'; return; }
  if (r.ok) { window.location.href = '/'; return; }
  if (r.needs_totp) {
    document.getElementById('totp-wrap').classList.remove('hidden');
    document.getElementById('l-totp').focus();
    errEl.textContent = 'Enter your authenticator code';
    return;
  }
  errEl.textContent = r.error || 'Login failed';
}

async function doRegister() {
  const code  = document.getElementById('r-code').value.trim();
  const user  = document.getElementById('r-user').value.trim();
  const pass  = document.getElementById('r-pass').value;
  const pass2 = document.getElementById('r-pass2').value;
  const errEl = document.getElementById('r-err');
  errEl.textContent = '';
  if (pass !== pass2) { errEl.textContent = 'Passwords do not match'; return; }
  if (pass.length < 8) { errEl.textContent = 'Password must be at least 8 characters'; return; }
  const body = {username: user, password: pass};
  if (_hasUsers) body.invite_code = code;
  const r = await fetch('/api/dash/register', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  }).then(x=>x.json()).catch(()=>null);
  if (!r) { errEl.textContent = 'Network error'; return; }
  if (!r.ok) { errEl.textContent = r.error || 'Registration failed'; return; }
  _pendingUid = r.uid;
  document.getElementById('qr-img').src = 'data:image/png;base64,' + r.qr_b64;
  document.getElementById('totp-secret-display').textContent = r.totp_secret;
  showTab('2fa');
  document.getElementById('pane-2fa').classList.remove('hidden');
  // also hide unused panes explicitly
  document.getElementById('pane-login').classList.add('hidden');
  document.getElementById('pane-register').classList.add('hidden');
}

async function doSetup2FA() {
  const token = document.getElementById('setup-code').value.trim();
  const errEl = document.getElementById('setup-err');
  errEl.textContent = '';
  if (!token || token.length < 6) { errEl.textContent = 'Enter the 6-digit code from your app'; return; }
  const r = await fetch('/api/dash/setup-2fa', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({uid: _pendingUid, token}),
  }).then(x=>x.json()).catch(()=>null);
  if (!r) { errEl.textContent = 'Network error'; return; }
  if (!r.ok) { errEl.textContent = r.error || '2FA setup failed'; return; }
  window.location.href = '/';
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FanBot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#08090d;
  --surface:#10121a;
  --surface2:#181b27;
  --border:#222540;
  --accent:#a855f7;
  --accent2:#ec4899;
  --text:#f0f2f8;
  --muted:#5a6480;
  --success:#34d399;
  --danger:#f87171;
  --warn:#fbbf24;
  --r:12px;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;line-height:1.5}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ── Navbar ─────────────────────────────────────────── */
.navbar{display:flex;align-items:center;justify-content:space-between;padding:0 28px;height:58px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:200;backdrop-filter:blur(10px)}
.brand{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:700;letter-spacing:-.3px}
.brand-dot{width:9px;height:9px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 10px var(--accent)}
.nav-right{display:flex;align-items:center;gap:10px}
.nav-row{display:contents}
.nav-clock{display:flex;flex-direction:column;align-items:flex-end;padding:0 6px;border-right:1px solid var(--border);margin-right:4px}
.nav-clock-time{font-size:12px;font-weight:700;letter-spacing:.2px;font-variant-numeric:tabular-nums;white-space:nowrap}
.nav-clock-tz{font-size:10px;color:var(--muted);font-weight:500;letter-spacing:.3px;margin-top:1px}
.nav-hamburger{display:none;background:none;border:none;cursor:pointer;padding:6px 8px;color:var(--text);font-size:22px;line-height:1;flex-shrink:0;border-radius:7px;transition:.15s}
.nav-hamburger:hover{background:var(--surface2)}
.nav-sep{width:1px;height:24px;background:var(--border);margin:0 4px}

/* ── Pills ───────────────────────────────────────────── */
.pill{display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.6px}
.pill-online{background:rgba(52,211,153,.12);color:var(--success);border:1px solid rgba(52,211,153,.25)}
.pill-offline{background:rgba(248,113,113,.1);color:var(--danger);border:1px solid rgba(248,113,113,.2)}
.pill-paused{background:rgba(251,191,36,.1);color:var(--warn);border:1px solid rgba(251,191,36,.2)}

/* ── Buttons ─────────────────────────────────────────── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:8px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:.18s all;white-space:nowrap}
.btn:active{transform:scale(.97)}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 2px 12px rgba(168,85,247,.3)}
.btn-primary:hover{opacity:.88;box-shadow:0 4px 20px rgba(168,85,247,.4)}
.btn-danger{background:rgba(248,113,113,.12);color:var(--danger);border:1px solid rgba(248,113,113,.25)}
.btn-danger:hover{background:rgba(248,113,113,.22)}
.btn-ghost{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-sm{padding:5px 12px;font-size:12px;border-radius:7px}

/* ── Tab bar ─────────────────────────────────────────── */
.tabbar{display:flex;padding:0 28px;background:var(--surface);border-bottom:1px solid var(--border);overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tabbar::-webkit-scrollbar{display:none}
.tabbar button{padding:14px 18px;background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);font-size:13px;font-weight:500;cursor:pointer;transition:.15s;margin-bottom:-1px;white-space:nowrap;flex-shrink:0}
.tabbar button:hover{color:var(--text)}
.tabbar button.active{color:var(--accent);border-bottom-color:var(--accent)}

/* ── Layout ──────────────────────────────────────────── */
.page{padding:28px;max-width:1380px;margin:0 auto}
.tab{display:none}.tab.active{display:block}

/* ── Cards ───────────────────────────────────────────── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:22px}
.card-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.9px;margin-bottom:18px}

/* ── Stat cards ──────────────────────────────────────── */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:22px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px 22px;position:relative;overflow:hidden}
.stat::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.stat-label{font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px}
.stat-value{font-size:30px;font-weight:800;line-height:1;letter-spacing:-1px}
.stat-sub{font-size:12px;color:var(--muted);margin-top:7px}

/* ── Grid helpers ────────────────────────────────────── */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.mb{margin-bottom:14px}

/* ── Conversation list ───────────────────────────────── */
.convo-list{display:flex;flex-direction:column;gap:6px}
.convo-item{display:flex;align-items:center;gap:14px;padding:14px 18px;background:var(--surface);border:1px solid var(--border);border-radius:10px;transition:.15s}
.convo-item:hover{border-color:rgba(168,85,247,.4);background:var(--surface2)}
.convo-item.muted-item{opacity:.45}
.avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;flex-shrink:0;color:#fff}
.convo-info{flex:1;min-width:0}
.convo-name{font-weight:600;font-size:13px;display:flex;align-items:center;gap:6px}
.convo-handle{color:var(--muted);font-weight:400}
.convo-preview{font-size:12px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:420px}
.convo-right{text-align:right;flex-shrink:0}
.convo-time{font-size:11px;color:var(--muted)}
.convo-count{font-size:12px;color:var(--accent);font-weight:700;margin-top:3px}
.convo-actions{display:flex;align-items:center;gap:8px;margin-left:10px;flex-shrink:0}

/* ── Toggle switch ───────────────────────────────────── */
.toggle{position:relative;display:inline-block;width:44px;height:24px;cursor:pointer;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.tslider{position:absolute;inset:0;background:var(--border);border-radius:12px;transition:.25s}
.tslider::before{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.25s;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.toggle input:checked+.tslider{background:linear-gradient(135deg,var(--accent),var(--accent2))}
.toggle input:checked+.tslider::before{transform:translateX(20px)}

/* ── Prompt editor ───────────────────────────────────── */
.prompt-wrap{position:relative}
.prompt-editor{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:16px;color:var(--text);font-size:13px;font-family:inherit;resize:vertical;min-height:420px;line-height:1.7;outline:none;transition:border-color .2s}
.prompt-editor:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(168,85,247,.1)}
.char-count{position:absolute;bottom:10px;right:14px;font-size:11px;color:var(--muted);pointer-events:none}

/* ── Schedule rows ───────────────────────────────────── */
.sched-row{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;margin-bottom:8px}
.sched-label{font-weight:600;font-size:13px}
.sched-sub{font-size:12px;color:var(--muted);margin-top:3px}
.num-input{background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 12px;width:82px;font-size:14px;font-weight:600;text-align:center;outline:none;transition:.2s}
.seg-ctrl{display:flex;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;flex-shrink:0}
.seg-ctrl label{padding:7px 18px;font-size:13px;font-weight:600;cursor:pointer;user-select:none;transition:.15s;color:var(--muted);white-space:nowrap}
.seg-ctrl input[type=radio]{display:none}
.seg-ctrl label:has(input:checked){background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.num-input:focus{border-color:var(--accent)}
.num-input-lg{background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 12px;width:240px;font-size:11px;font-family:monospace;text-align:left;outline:none;transition:.2s}
.num-input-lg:focus{border-color:var(--accent)}
.num-input-md{background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 12px;width:160px;font-size:14px;font-weight:600;text-align:left;outline:none;transition:.2s}
.num-input-md:focus{border-color:var(--accent)}

/* ── Chart containers ────────────────────────────────── */
.chart-wrap{position:relative;height:260px}
.chart-wrap-sm{position:relative;height:190px}

/* ── Status badge inside overview ────────────────────── */
.status-row{display:flex;align-items:center;gap:10px;padding:12px 0;border-bottom:1px solid var(--border)}
.status-row:last-child{border-bottom:none;padding-bottom:0}
.status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-green{background:var(--success);box-shadow:0 0 6px var(--success)}
.dot-red{background:var(--danger);box-shadow:0 0 6px var(--danger)}
.dot-yellow{background:var(--warn);box-shadow:0 0 6px var(--warn)}

/* ── Toast ───────────────────────────────────────────── */
#toast{position:fixed;bottom:28px;right:28px;padding:12px 20px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);font-size:13px;font-weight:500;z-index:9999;opacity:0;transform:translateY(12px);transition:.25s;pointer-events:none}
#toast.show{opacity:1;transform:translateY(0)}
#toast.ok{border-left:3px solid var(--success)}
#toast.err{border-left:3px solid var(--danger)}

/* ── Empty state ─────────────────────────────────────── */
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
.empty-icon{font-size:44px;margin-bottom:12px}

/* ── User management ─────────────────────────────────── */
.user-row{display:flex;align-items:center;gap:14px;padding:14px 18px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;flex-wrap:wrap}
.user-row .user-info{flex:1;min-width:0}
.user-row .user-name{font-weight:600;font-size:13px}
.user-row .user-meta{font-size:12px;color:var(--muted);margin-top:3px}
.user-role-badge{display:inline-flex;align-items:center;padding:2px 10px;border-radius:6px;font-size:11px;font-weight:700;letter-spacing:.4px}
.role-admin{background:rgba(168,85,247,.15);color:var(--accent);border:1px solid rgba(168,85,247,.3)}
.role-user{background:rgba(90,100,128,.12);color:var(--muted);border:1px solid rgba(90,100,128,.25)}
.perm-tag{display:inline-flex;align-items:center;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:600;background:rgba(168,85,247,.1);color:var(--accent);border:1px solid rgba(168,85,247,.2);margin:2px}
.invite-row{display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;flex-wrap:wrap}
.invite-code{font-family:monospace;font-size:13px;letter-spacing:1px;color:var(--text);flex-shrink:0}
.invite-used{opacity:.45;text-decoration:line-through}
.perm-check-item{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;cursor:pointer;transition:.15s;font-size:12px;font-weight:500;user-select:none}
.perm-check-item:hover{border-color:var(--accent);color:var(--text)}
.perm-check-item input[type=checkbox]{accent-color:var(--accent);width:14px;height:14px;flex-shrink:0}

/* ── Responsive ──────────────────────────────────────── */
@media(max-width:820px){
  .g2,.g3{grid-template-columns:1fr}
  .stats{grid-template-columns:repeat(2,1fr)}
  .page{padding:16px}
  .convo-preview{max-width:200px}
  .chart-wrap{height:220px}
  .chart-wrap-sm{height:170px}
}
@media(max-width:600px){
  .navbar{padding:0 14px;height:50px;position:relative}
  .brand{font-size:13px}
  .brand-dot{width:7px;height:7px}
  .nav-hamburger{display:flex;align-items:center;justify-content:center}
  .nav-right{
    display:none;
    position:absolute;
    top:50px;left:0;right:0;
    flex-direction:column;
    align-items:stretch;
    gap:0;
    background:var(--surface);
    border-bottom:2px solid var(--border);
    box-shadow:0 8px 32px rgba(0,0,0,.55);
    padding:10px 16px 14px;
    z-index:190;
  }
  .nav-right.open{display:flex}
  .nav-row{
    display:flex;
    align-items:center;
    gap:8px;
    padding:10px 0;
    border-bottom:1px solid var(--border);
    flex-wrap:wrap;
  }
  .nav-row:last-child{border-bottom:none;padding-bottom:0}
  .nav-sep{display:none}
  .nav-clock{border-right:none;padding:0;margin:0;align-items:flex-start}
}
@media(max-width:560px){
  .btn{padding:6px 12px;font-size:12px}
  .tabbar{padding:0 4px}
  .tabbar button{padding:12px 13px;font-size:12px}
  .page{padding:12px}
  .stats{grid-template-columns:1fr 1fr}
  .stat{padding:16px 14px}
  .stat-value{font-size:24px}
  .sched-row{flex-direction:column;align-items:flex-start;gap:10px}
  .num-input,.num-input-lg,.num-input-md{width:100%;text-align:left}
  .convo-item{flex-wrap:wrap}
  .convo-right{flex:1;text-align:right}
  .convo-actions{margin-left:0;width:100%;justify-content:flex-end;padding-top:4px;border-top:1px solid var(--border)}
  .convo-preview{max-width:100%}
  .card{padding:14px}
  .chart-wrap{height:180px}
  .chart-wrap-sm{height:140px}
  .prompt-editor{min-height:320px}
}
@media(max-width:380px){
  .stats{grid-template-columns:1fr}
  .stat-value{font-size:22px}
}
</style>
</head>
<body>

<!-- ───────────────── Navbar ───────────────── -->
<nav class="navbar">
  <div class="brand">
    <span class="brand-dot"></span>
    FanBot Panel
  </div>
  <div class="nav-right" id="nav-right">
    <div class="nav-row">
      <div class="nav-clock">
        <div class="nav-clock-time" id="nav-time">——:——:——</div>
        <div class="nav-clock-tz" id="nav-tz-label">Loading…</div>
      </div>
      <span id="status-pill" class="pill pill-offline">OFFLINE</span>
    </div>
    <div class="nav-row">
      <button class="btn btn-ghost btn-sm" id="restart-btn" onclick="restartBot()" title="Stop then restart the bot">↺ Restart</button>
      <button id="bot-btn" class="btn btn-primary" onclick="toggleBot()">Start Bot</button>
    </div>
    <div class="nav-row">
      <span id="nav-username" style="font-size:12px;color:var(--muted);font-weight:600;flex:1"></span>
      <div class="nav-sep"></div>
      <button class="btn btn-ghost btn-sm" onclick="openChangePassModal()" title="Change password">🔑</button>
      <button class="btn btn-ghost btn-sm" onclick="doLogout()" title="Sign out">Sign Out</button>
    </div>
  </div>
  <button class="nav-hamburger" id="nav-hamburger" onclick="toggleNavMenu()" aria-label="Menu">☰</button>
</nav>

<!-- ───────────────── Tab bar ──────────────── -->
<div class="tabbar" id="main-tabbar">
  <button class="active" id="tab-btn-overview" onclick="switchTab('overview',this)">Home</button>
  <button id="tab-btn-conversations" onclick="switchTab('conversations',this)">Conversations</button>
  <button id="tab-btn-prompt" onclick="switchTab('prompt',this)">Prompt</button>
  <button id="tab-btn-schedule" onclick="switchTab('schedule',this)">Configuration</button>
  <button id="tab-btn-analytics" onclick="switchTab('analytics',this)">Analytics</button>
  <button id="tab-btn-notes" onclick="switchTab('notes',this)">Notes</button>
  <button id="tab-btn-users" onclick="switchTab('users',this)" style="display:none">Users</button>
</div>

<div class="page">

  <!-- ═══════════════════ OVERVIEW ═══════════════════ -->
  <div id="tab-overview" class="tab active">
    <div class="stats">
      <div class="stat">
        <div class="stat-label">Total Messages</div>
        <div class="stat-value" id="s-total">—</div>
        <div class="stat-sub">all time received</div>
      </div>
      <div class="stat">
        <div class="stat-label">Conversations</div>
        <div class="stat-value" id="s-users">—</div>
        <div class="stat-sub">unique chatters</div>
      </div>
      <div class="stat">
        <div class="stat-label">Today</div>
        <div class="stat-value" id="s-today">—</div>
        <div class="stat-sub">messages today</div>
      </div>
      <div class="stat">
        <div class="stat-label">Replies Sent</div>
        <div class="stat-value" id="s-replies">—</div>
        <div class="stat-sub" id="s-rate">—</div>
      </div>
    </div>

    <div class="g2">
      <div class="card">
        <div class="card-title">Bot Status</div>
        <div id="ov-bot-status" style="color:var(--muted)">Loading…</div>
      </div>
      <div class="card">
        <div class="card-title">Today's Active Window</div>
        <div id="ov-schedule">Loading…</div>
      </div>
    </div>
  </div>

  <!-- ═══════════════════ CONVERSATIONS ═══════════════════ -->
  <div id="tab-conversations" class="tab">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
      <span style="font-size:16px;font-weight:700">Recent Conversations</span>
      <span style="font-size:12px;color:var(--muted)">Toggle to pause/resume AI replies per chat</span>
    </div>
    <div id="convo-list" class="convo-list">
      <div class="empty"><div class="empty-icon">💬</div>No conversations yet</div>
    </div>
  </div>

  <!-- ═══════════════════ PROMPT ═══════════════════ -->
  <div id="tab-prompt" class="tab">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:18px">
      <div>
        <div style="font-size:16px;font-weight:700">System Prompt</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">Changes apply on the next message — no restart needed</div>
      </div>
      <button class="btn btn-primary" onclick="savePrompt()">Save Prompt</button>
    </div>
    <div class="card" style="padding:16px">
      <div class="card-title">Nadia's Persona &amp; Instructions</div>
      <div class="prompt-wrap">
        <textarea id="prompt-editor" class="prompt-editor" oninput="updateCharCount()" placeholder="Enter system prompt…"></textarea>
        <div class="char-count" id="char-count">0 chars</div>
      </div>
    </div>
  </div>

  <!-- ═══════════════════ SCHEDULE ═══════════════════ -->
  <div id="tab-schedule" class="tab">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:18px">
      <div>
        <div style="font-size:16px;font-weight:700">Schedule &amp; Window</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">Changes to window hours regenerate tomorrow's schedule</div>
      </div>
      <button class="btn btn-primary" onclick="saveSchedule()">Save Settings</button>
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Bot Timezone</div>
        <div class="sched-sub">IANA timezone name — e.g. Asia/Colombo, America/New_York, Europe/London. Restart the bot to apply.</div>
      </div>
      <input type="text" class="num-input-lg" id="bot-timezone" placeholder="Asia/Colombo" autocomplete="off" spellcheck="false">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Force Inactive Mode</div>
        <div class="sched-sub">Override schedule — bot goes silent immediately, no replies sent</div>
      </div>
      <label class="toggle">
        <input type="checkbox" id="force-inactive" onchange="saveSchedule()">
        <span class="tslider"></span>
      </label>
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Window Start Hour</div>
        <div class="sched-sub">Earliest hour the bot begins replying (0–23, 24h)</div>
      </div>
      <input type="number" class="num-input" id="win-start" min="0" max="23" value="1">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Window End Hour</div>
        <div class="sched-sub">Latest hour the bot stops replying (0–23, 24h)</div>
      </div>
      <input type="number" class="num-input" id="win-end" min="0" max="23" value="23">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Jitter Min (minutes)</div>
        <div class="sched-sub">Minimum random shift applied to window start/end each day</div>
      </div>
      <input type="number" class="num-input" id="win-jitter-min" min="0" max="180" value="10">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Jitter Max (minutes)</div>
        <div class="sched-sub">Maximum random shift applied to window start/end each day</div>
      </div>
      <input type="number" class="num-input" id="win-jitter-max" min="0" max="180" value="75">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Reply Delay Mode</div>
        <div class="sched-sub">Fixed time range, or auto-calculate delay from typing speed (WPM)</div>
      </div>
      <div class="seg-ctrl">
        <label><input type="radio" name="delay-mode" id="delay-mode-range" value="range" onchange="updateDelayMode()"> Range</label>
        <label><input type="radio" name="delay-mode" id="delay-mode-wpm" value="wpm" onchange="updateDelayMode()"> WPM</label>
      </div>
    </div>

    <div id="delay-range-section">
      <div class="sched-row">
        <div>
          <div class="sched-label">Reply Delay Min (seconds)</div>
          <div class="sched-sub">Shortest pause before sending a reply after the AI responds</div>
        </div>
        <input type="number" class="num-input" id="reply-delay-min" min="0" max="120" value="3">
      </div>
      <div class="sched-row">
        <div>
          <div class="sched-label">Reply Delay Max (seconds)</div>
          <div class="sched-sub">Longest pause before sending a reply after the AI responds</div>
        </div>
        <input type="number" class="num-input" id="reply-delay-max" min="0" max="120" value="5">
      </div>
    </div>

    <div id="delay-wpm-section" style="display:none;margin-bottom:4px">
      <div class="sched-row" style="margin-bottom:18px">
        <div>
          <div class="sched-label">Typing Speed (WPM)</div>
          <div class="sched-sub">Delay = time to type the reply at this speed (±15% jitter). Typical human: 35–55 WPM</div>
        </div>
        <input type="number" class="num-input" id="typing-wpm" min="1" max="300" value="40">
      </div>
    </div>

    <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.9px;margin:22px 0 10px;padding:0 2px">🔔 Pushbullet Notifications</div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Pushbullet API Key</div>
        <div class="sched-sub">From pushbullet.com/account — leave blank to disable all notifications</div>
      </div>
      <input type="text" class="num-input-lg" id="pb-api-key" autocomplete="off" placeholder="o.XXXXXXXXXXXXXXXXX">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">FCM Service Account JSON</div>
        <div class="sched-sub">Path to your Firebase service account JSON file, or paste the raw JSON — enables Android push notifications</div>
      </div>
      <input type="text" class="num-input-lg" id="fcm-server-key" autocomplete="off" placeholder="/path/to/serviceAccount.json">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Your Name</div>
        <div class="sched-sub">Used in notification messages ("Hey [name], …")</div>
      </div>
      <input type="text" class="num-input-md" id="notify-owner" placeholder="Matheesha">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Notify on First Message</div>
        <div class="sched-sub">Push alert when a brand-new user messages for the first time</div>
      </div>
      <label class="toggle">
        <input type="checkbox" id="notify-new-chatter" checked>
        <span class="tslider"></span>
      </label>
    </div>

    <div class="sched-row" style="margin-bottom:18px">
      <div>
        <div class="sched-label">Message Count Alert</div>
        <div class="sched-sub">Push alert when a chat reaches this many messages (0 = off)</div>
      </div>
      <input type="number" class="num-input" id="notify-threshold" min="0" max="9999" value="5">
    </div>

    <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.9px;margin:22px 0 10px;padding:0 2px">🤖 AI Model Settings</div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Enable Message Rechecking</div>
        <div class="sched-sub">Run a second AI pass to verify each reply follows the guidelines before sending</div>
      </div>
      <label class="toggle">
        <input type="checkbox" id="recheck-enabled" checked onchange="saveSchedule()">
        <span class="tslider"></span>
      </label>
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Guideline Accuracy (%)</div>
        <div class="sched-sub">Minimum % of guidelines a reply must follow to pass the recheck (1–100)</div>
      </div>
      <input type="number" class="num-input" id="recheck-accuracy" min="1" max="100" value="80">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Reply Temperature</div>
        <div class="sched-sub">Creativity of reply generation — higher = more varied, lower = more consistent (0.0–2.0)</div>
      </div>
      <input type="number" class="num-input" id="reply-temperature" min="0" max="2" step="0.05" value="0.9">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Reply Max Tokens</div>
        <div class="sched-sub">Maximum reply length in tokens (~¾ of a word per token)</div>
      </div>
      <input type="number" class="num-input" id="reply-max-tokens" min="10" max="4096" value="80">
    </div>

    <div class="sched-row">
      <div>
        <div class="sched-label">Recheck Temperature</div>
        <div class="sched-sub">Creativity of the recheck AI — lower values are more reliable for verification (0.0–2.0)</div>
      </div>
      <input type="number" class="num-input" id="recheck-temperature" min="0" max="2" step="0.05" value="0.5">
    </div>

    <div class="sched-row" style="margin-bottom:18px">
      <div>
        <div class="sched-label">Recheck Max Tokens</div>
        <div class="sched-sub">Maximum length of the recheck AI's verdict response in tokens</div>
      </div>
      <input type="number" class="num-input" id="recheck-max-tokens" min="10" max="4096" value="100">
    </div>

    <div class="card" style="margin-top:10px">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px">
        <div class="card-title" style="margin-bottom:0">Break Scheduler</div>
        <input type="date" id="break-date" class="num-input" style="width:160px" oninput="loadBreaks(this.value)">
      </div>
      <div id="break-list" style="margin-bottom:12px;min-height:24px"></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <input type="time" id="break-start" class="num-input" style="width:115px">
        <span style="color:var(--muted);font-size:13px">→</span>
        <input type="time" id="break-end" class="num-input" style="width:115px">
        <button class="btn btn-primary" style="padding:6px 14px;font-size:13px" onclick="addBreak()">+ Add Break</button>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:10px">Breaks apply to today and any future dates. The bot picks them up live — no restart needed.</div>
    </div>
  </div>

  <!-- ═══════════════════ ANALYTICS ═══════════════════ -->
  <div id="tab-analytics" class="tab">
    <div class="stats" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:22px">
      <div class="stat">
        <div class="stat-label">Top Chatter</div>
        <div class="stat-value" style="font-size:20px;word-break:break-word" id="an-top">—</div>
        <div class="stat-sub" id="an-top-count">— messages</div>
      </div>
      <div class="stat">
        <div class="stat-label">Peak Hour</div>
        <div class="stat-value" id="an-peak">—</div>
        <div class="stat-sub">most active time</div>
      </div>
      <div class="stat">
        <div class="stat-label">Response Rate</div>
        <div class="stat-value" id="an-rate">—</div>
        <div class="stat-sub">replies ÷ received</div>
      </div>
      <div class="stat">
        <div class="stat-label">Avg / Active Day</div>
        <div class="stat-value" id="an-avg">—</div>
        <div class="stat-sub">messages per day</div>
      </div>
      <div class="stat">
        <div class="stat-label">New Today</div>
        <div class="stat-value" id="an-new">—</div>
        <div class="stat-sub">first-time chatters</div>
      </div>
    </div>

    <div class="g2 mb">
      <div class="card">
        <div class="card-title">Messages — Last 14 Days</div>
        <div class="chart-wrap"><canvas id="ch-daily"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">Top Chatters</div>
        <div class="chart-wrap"><canvas id="ch-top"></canvas></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Activity by Hour of Day</div>
      <div class="chart-wrap-sm"><canvas id="ch-hourly"></canvas></div>
    </div>
  </div>

  <!-- ═══════════════════ NOTES ═══════════════════ -->
  <div id="tab-notes" class="tab">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px">
      <div>
        <div style="font-size:18px;font-weight:700">Notes</div>
        <div style="color:var(--muted);font-size:12px;margin-top:4px">Day-specific instructions the AI will follow — keep private plans here</div>
      </div>
      <button class="btn btn-primary" onclick="openNoteModal()">+ Add Note</button>
    </div>
    <div id="notes-list"><div style="color:var(--muted);padding:20px">Loading…</div></div>
  </div>

  <!-- ═══════════════════ USERS ═══════════════════ -->
  <div id="tab-users" class="tab">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px">
      <div>
        <div style="font-size:18px;font-weight:700">Users &amp; Invites</div>
        <div style="color:var(--muted);font-size:12px;margin-top:4px">Manage dashboard users and generate invitation codes</div>
      </div>
      <button class="btn btn-primary" onclick="openInviteModal()">+ Generate Invite</button>
    </div>

    <div class="card mb">
      <div class="card-title">Dashboard Users</div>
      <div id="users-list"><div style="color:var(--muted)">Loading…</div></div>
    </div>

    <div class="card">
      <div class="card-title">Invitation Codes</div>
      <div id="invites-list"><div style="color:var(--muted)">Loading…</div></div>
    </div>
  </div>

</div><!-- /page -->

<!-- ─── Invite Modal ─────────────────────────────────────── -->
<div id="invite-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;width:520px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto">
    <div style="font-size:20px;font-weight:800;margin-bottom:6px">Generate Invite Code</div>
    <div style="color:var(--muted);font-size:13px;margin-bottom:22px">Select the permissions this invite code will grant to the new user.</div>
    <div class="card-title" style="margin-bottom:10px">Grant Permissions</div>
    <div id="invite-perms-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:22px"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-ghost" onclick="document.getElementById('invite-modal').style.display='none'">Cancel</button>
      <button class="btn btn-primary" onclick="createInvite()">Generate</button>
    </div>
  </div>
</div>

<!-- ─── Invite Result Modal ──────────────────────────────── -->
<div id="invite-result-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:600;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;width:440px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.6);text-align:center">
    <div style="font-size:36px;margin-bottom:10px">🎟️</div>
    <div style="font-size:18px;font-weight:800;margin-bottom:8px">Invite Code Created</div>
    <div style="color:var(--muted);font-size:13px;margin-bottom:20px">Share this code with the person you want to invite. It expires after one use.</div>
    <div id="invite-code-display" style="background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px 16px;font-family:monospace;font-size:16px;letter-spacing:2px;word-break:break-all;color:var(--accent);margin-bottom:16px"></div>
    <button class="btn btn-primary" style="width:100%;justify-content:center" onclick="copyInviteCode()">Copy Code</button>
    <button class="btn btn-ghost" style="width:100%;justify-content:center;margin-top:10px" onclick="document.getElementById('invite-result-modal').style.display='none'">Close</button>
  </div>
</div>

<!-- ─── Edit Permissions Modal ───────────────────────────── -->
<div id="edit-perms-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;width:520px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto">
    <div style="font-size:20px;font-weight:800;margin-bottom:6px">Edit Permissions</div>
    <div style="color:var(--muted);font-size:13px;margin-bottom:4px" id="edit-perms-subtitle">Editing user permissions</div>
    <input type="hidden" id="edit-perms-uid">
    <div id="edit-perms-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:18px 0 22px"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-ghost" onclick="document.getElementById('edit-perms-modal').style.display='none'">Cancel</button>
      <button class="btn btn-primary" onclick="saveUserPerms()">Save</button>
    </div>
  </div>
</div>

<!-- ─── Change Password Modal ────────────────────────────── -->
<div id="chpass-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:600;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;width:400px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.6)">
    <div style="font-size:20px;font-weight:800;margin-bottom:6px">Change Password</div>
    <div style="color:var(--muted);font-size:13px;margin-bottom:22px">Update your dashboard login password</div>
    <div class="sched-label" style="margin-bottom:6px">Current Password</div>
    <input type="password" id="cp-old" autocomplete="current-password" placeholder="••••••••"
      style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:11px 13px;color:var(--text);font-size:14px;outline:none;transition:.2s;margin-bottom:14px"
      onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
    <div class="sched-label" style="margin-bottom:6px">New Password</div>
    <input type="password" id="cp-new" autocomplete="new-password" placeholder="Min 8 characters"
      style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:11px 13px;color:var(--text);font-size:14px;outline:none;transition:.2s;margin-bottom:14px"
      onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
    <div class="sched-label" style="margin-bottom:6px">Confirm New Password</div>
    <input type="password" id="cp-new2" autocomplete="new-password" placeholder="Repeat new password"
      style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:11px 13px;color:var(--text);font-size:14px;outline:none;transition:.2s;margin-bottom:4px"
      onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'"
      onkeydown="if(event.key==='Enter')doChangePass()">
    <div id="cp-err" style="color:var(--danger);font-size:12px;min-height:20px;margin-bottom:10px"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-ghost" onclick="closeChangePassModal()">Cancel</button>
      <button class="btn btn-primary" onclick="doChangePass()">Update Password</button>
    </div>
  </div>
</div>

<!-- ─── Note Modal ───────────────────────────────────────── -->
<div id="note-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;width:520px;max-width:94vw;box-shadow:0 24px 64px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto">
    <div style="font-size:20px;font-weight:800;margin-bottom:20px" id="note-modal-title">Add Note</div>
    <input type="hidden" id="note-edit-id">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
      <div>
        <div class="sched-label" style="margin-bottom:6px">Date</div>
        <input type="date" id="note-date" class="input" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font-size:14px;outline:none;transition:.2s" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
      </div>
      <div>
        <div class="sched-label" style="margin-bottom:6px">Time <span style="color:var(--muted);font-weight:400">(optional)</span></div>
        <input type="time" id="note-time" class="input" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font-size:14px;outline:none;transition:.2s" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
      </div>
    </div>
    <div style="margin-bottom:14px">
      <div class="sched-label" style="margin-bottom:6px">Title <span style="color:var(--muted);font-weight:400">(optional)</span></div>
      <input type="text" id="note-title" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font-size:14px;outline:none;transition:.2s" placeholder="e.g. Trip to Bali" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
    </div>
    <div style="margin-bottom:22px">
      <div class="sched-label" style="margin-bottom:6px">Note / Instructions</div>
      <textarea id="note-content" style="width:100%;height:150px;resize:vertical;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font-size:13px;font-family:inherit;line-height:1.6;outline:none;transition:.2s" placeholder="Describe what you'll be doing and any private instructions for the AI (e.g. I'm on vacation in Bali — don't tell anyone, just say I'm busy if asked)" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'"></textarea>
    </div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-ghost" onclick="closeNoteModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveNote()">Save Note</button>
    </div>
  </div>
</div>

<!-- ─── Auth Modal ───────────────────────────────────────── -->
<div id="auth-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(6px)">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:40px 36px;width:400px;max-width:92vw;box-shadow:0 24px 64px rgba(0,0,0,.6)">
    <div style="font-size:24px;font-weight:800;margin-bottom:8px">🔐 Telegram Login</div>
    <div id="auth-subtitle" style="color:var(--muted);font-size:13px;margin-bottom:28px;line-height:1.7">Enter the code sent to your Telegram</div>
    <input id="auth-input" type="text" autocomplete="one-time-code"
      style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px 16px;color:var(--text);font-size:22px;letter-spacing:8px;text-align:center;outline:none;margin-bottom:16px;transition:.2s;font-weight:700"
      placeholder="· · · · ·"
      onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'"
      onkeydown="if(event.key==='Enter')submitAuth()">
    <button class="btn btn-primary" style="width:100%;justify-content:center;padding:14px;font-size:14px" onclick="submitAuth()">Confirm</button>
    <div id="auth-error" style="color:var(--danger);font-size:12px;margin-top:10px;text-align:center;min-height:18px"></div>
  </div>
</div>

<div id="toast"></div>

<script>
// ──────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────
// ──────────────────────────────────────────────────────────
// User / permissions context injected by server
// ──────────────────────────────────────────────────────────
const ME = window.__USER__ || {role:'user', permissions:[], username:''};
const IS_ADMIN = ME.role === 'admin';
function hasPerm(p) { return IS_ADMIN || ME.permissions.includes(p); }

const PERM_LABELS = {
  view_overview:     'View Overview',
  view_conversations:'View Conversations',
  mute_users:        'Mute/Unmute Users',
  view_prompt:       'View Prompt',
  edit_prompt:       'Edit Prompt',
  view_config:       'View Configuration',
  edit_config:       'Edit Configuration',
  view_analytics:    'View Analytics',
  view_notes:        'View Notes',
  edit_notes:        'Edit Notes',
  bot_control:       'Bot Control',
  manage_users:      'Manage Users',
};

// Apply permission-gating to tabs and controls
function applyPermissions() {
  // Navbar username
  const nu = document.getElementById('nav-username');
  if (nu) nu.textContent = ME.username || '';

  // Show/hide tabs
  const tabMap = {
    overview:      'view_overview',
    conversations: 'view_conversations',
    prompt:        'view_prompt',
    schedule:      'view_config',
    analytics:     'view_analytics',
    notes:         'view_notes',
    users:         'manage_users',
  };
  Object.entries(tabMap).forEach(([tab, perm]) => {
    const btn = document.getElementById('tab-btn-' + tab);
    if (btn) btn.style.display = hasPerm(perm) ? '' : 'none';
  });

  // Bot control buttons
  if (!hasPerm('bot_control')) {
    const bb = document.getElementById('bot-btn');
    const rb = document.getElementById('restart-btn');
    if (bb) bb.style.display = 'none';
    if (rb) rb.style.display = 'none';
  }
}

// ──────────────────────────────────────────────────────────
// Sign out
// ──────────────────────────────────────────────────────────
async function doLogout() {
  await fetch('/api/dash/logout', {method:'POST'});
  window.location.href = '/login';
}

// ──────────────────────────────────────────────────────────
// Mobile nav dropdown
// ──────────────────────────────────────────────────────────
function toggleNavMenu() {
  const nr  = document.getElementById('nav-right');
  const btn = document.getElementById('nav-hamburger');
  const open = nr.classList.toggle('open');
  btn.textContent = open ? '✕' : '☰';
}

function closeNavMenu() {
  const nr  = document.getElementById('nav-right');
  const btn = document.getElementById('nav-hamburger');
  nr.classList.remove('open');
  btn.textContent = '☰';
}

// Close dropdown when tapping outside
document.addEventListener('click', e => {
  const nr  = document.getElementById('nav-right');
  const btn = document.getElementById('nav-hamburger');
  if (nr && nr.classList.contains('open') && !nr.contains(e.target) && e.target !== btn) {
    closeNavMenu();
  }
});

// ──────────────────────────────────────────────────────────
// Change password
// ──────────────────────────────────────────────────────────
function openChangePassModal() {
  document.getElementById('cp-old').value  = '';
  document.getElementById('cp-new').value  = '';
  document.getElementById('cp-new2').value = '';
  document.getElementById('cp-err').textContent = '';
  document.getElementById('chpass-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('cp-old').focus(), 80);
}

function closeChangePassModal() {
  document.getElementById('chpass-modal').style.display = 'none';
}

async function doChangePass() {
  const oldP = document.getElementById('cp-old').value;
  const newP = document.getElementById('cp-new').value;
  const newP2 = document.getElementById('cp-new2').value;
  const errEl = document.getElementById('cp-err');
  errEl.textContent = '';
  if (!oldP || !newP || !newP2) { errEl.textContent = 'All fields are required'; return; }
  if (newP !== newP2)            { errEl.textContent = 'New passwords do not match'; return; }
  if (newP.length < 8)           { errEl.textContent = 'New password must be at least 8 characters'; return; }
  const r = await api('/dash/change-password', 'POST', {old_password: oldP, new_password: newP});
  if (r?.ok) {
    toast('✓ Password updated', 'ok');
    closeChangePassModal();
  } else {
    errEl.textContent = r?.error || 'Failed to update password';
  }
}

let botRunning = false;
const charts   = {};
let navTz      = 'Asia/Colombo';

// ──────────────────────────────────────────────────────────
// Navbar clock
// ──────────────────────────────────────────────────────────
function updateClock() {
  try {
    const now = new Date();
    const d = new Intl.DateTimeFormat('en-US',{timeZone:navTz,weekday:'short',month:'short',day:'numeric'}).format(now);
    const t = new Intl.DateTimeFormat('en-US',{timeZone:navTz,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true}).format(now);
    document.getElementById('nav-time').textContent = d + '  ' + t;
    document.getElementById('nav-tz-label').textContent = navTz;
  } catch(e) {
    document.getElementById('nav-time').textContent = new Date().toLocaleTimeString();
    document.getElementById('nav-tz-label').textContent = navTz;
  }
}
setInterval(updateClock, 1000);
updateClock();

// ──────────────────────────────────────────────────────────
// Tab switching
// ──────────────────────────────────────────────────────────
function switchTab(name, el) {
  closeNavMenu();
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tabbar button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (el) el.classList.add('active');
  if (name === 'conversations') loadConversations();
  if (name === 'analytics')     loadAnalytics();
  if (name === 'prompt')        loadPrompt();
  if (name === 'schedule')      loadSchedule();
  if (name === 'notes')         loadNotes();
  if (name === 'users')         loadUsersTab();
}

// ──────────────────────────────────────────────────────────
// Toast
// ──────────────────────────────────────────────────────────
function toast(msg, type='ok') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className   = 'show ' + type;
  el.id          = 'toast';
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = ''; el.id = 'toast'; }, 3000);
}

// ──────────────────────────────────────────────────────────
// API helper
// ──────────────────────────────────────────────────────────
async function api(path, method='GET', body=null) {
  try {
    const opts = { method, headers: {'Content-Type':'application/json'} };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch('/api' + path, opts);
    return await r.json();
  } catch(e) { return null; }
}

// ──────────────────────────────────────────────────────────
// Status polling
// ──────────────────────────────────────────────────────────
async function refreshStatus() {
  const s = await api('/status');
  if (!s) return;
  botRunning = s.bot_running;

  const pill = document.getElementById('status-pill');
  const btn  = document.getElementById('bot-btn');

  if (s.bot_running && s.force_inactive) {
    pill.className   = 'pill pill-paused';
    pill.textContent = 'PAUSED';
  } else if (s.bot_running) {
    pill.className   = 'pill pill-online';
    pill.textContent = 'ONLINE';
  } else {
    pill.className   = 'pill pill-offline';
    pill.textContent = 'OFFLINE';
  }
  btn.textContent = s.bot_running ? 'Stop Bot' : 'Start Bot';
  btn.className   = s.bot_running ? 'btn btn-danger' : 'btn btn-primary';

  // Overview stats
  document.getElementById('s-total').textContent   = s.total_messages.toLocaleString();
  document.getElementById('s-users').textContent   = s.total_users.toLocaleString();
  document.getElementById('s-today').textContent   = s.messages_today.toLocaleString();
  document.getElementById('s-replies').textContent = s.total_replies.toLocaleString();
  document.getElementById('s-rate').textContent    = s.total_messages
    ? Math.round(s.total_replies / s.total_messages * 100) + '% reply rate' : '—';

  navTz = s.timezone || 'Asia/Colombo';
  updateClock();

  // Overview bot status card
  const running = s.bot_running;
  const paused  = s.force_inactive;
  const ws      = s.window_state;
  const wNext   = s.window_next;
  const wsLabel = {
    active:         ['dot-green',  'Active Window',     'Replying normally — within active window'],
    on_break:       ['dot-yellow', 'On Break',          `Paused — break ends at ${wNext}`],
    before_window:  ['dot-yellow', 'Before Window',     `Waiting — window opens at ${wNext}`],
    after_window:   ['dot-yellow', 'After Window',      'Outside window — resumes tomorrow'],
    force_inactive: ['dot-yellow', 'Force Inactive',    '⚠️ Override is ON — no replies being sent'],
    unknown:        ['dot-red',    'No Schedule',       'Schedule not generated yet'],
  }[ws] || ['dot-red', 'Unknown', ''];
  const runDot  = running ? (paused || ws === 'force_inactive' ? 'dot-yellow' : ws === 'active' ? 'dot-green' : 'dot-yellow') : 'dot-red';
  const runLabel = running ? (paused ? 'Running — Force Inactive' : 'Running') : 'Stopped';
  document.getElementById('ov-bot-status').innerHTML = `
    <div class="status-row">
      <span class="status-dot ${runDot}"></span>
      <span style="font-weight:600">${runLabel}</span>
    </div>
    ${running ? `
    <div class="status-row">
      <span class="status-dot ${wsLabel[0]}"></span>
      <span style="font-weight:600">${wsLabel[1]}</span>
    </div>
    <div class="status-row">
      <span class="status-dot" style="background:transparent"></span>
      <span style="color:var(--muted);font-size:12px">${wsLabel[2]}</span>
    </div>` : `
    <div class="status-row">
      <span class="status-dot" style="background:transparent"></span>
      <span style="color:var(--muted);font-size:12px">Press Start Bot in the top-right to begin</span>
    </div>`}
  `;
}

async function refreshScheduleOverview() {
  try {
    const d = await fetch('/api/today-schedule').then(r=>r.json());
    const el = document.getElementById('ov-schedule');
    if (d.error) {
      el.innerHTML = '<span style="color:var(--muted);font-size:13px">No schedule yet — generated on first bot run</span>';
    } else {
      el.innerHTML = `
        <div class="status-row">
          <span class="status-dot dot-green"></span>
          <span><strong>${d.window_start}</strong> — <strong>${d.window_end}</strong></span>
        </div>
        <div class="status-row">
          <span class="status-dot" style="background:transparent"></span>
          <span style="color:var(--muted);font-size:12px">${d.breaks.length} break(s) · ${d.date}</span>
        </div>`;
    }
  } catch(e) {}
}

setInterval(refreshStatus, 5000);
refreshStatus();
refreshScheduleOverview();
applyPermissions();

// ──────────────────────────────────────────────────────────
// Bot toggle
// ──────────────────────────────────────────────────────────
async function toggleBot() {
  const wasRunning = botRunning;
  const btn = document.getElementById('bot-btn');
  btn.disabled = true;
  const r = await api(botRunning ? '/bot/stop' : '/bot/start', 'POST');
  btn.disabled = false;
  if (r) {
    toast(r.message, r.ok ? 'ok' : 'err');
    setTimeout(refreshStatus, 900);
    if (!wasRunning && r.ok) {
      // Poll for auth prompt quickly after bot starts
      setTimeout(checkAuthStatus, 1500);
      setTimeout(checkAuthStatus, 3500);
    }
  }
}

async function restartBot() {
  const btn = document.getElementById('restart-btn');
  btn.disabled = true;
  btn.textContent = '↺ Restarting…';
  const r = await api('/bot/restart', 'POST');
  btn.disabled = false;
  btn.textContent = '↺ Restart';
  if (r) {
    toast(r.message, r.ok ? 'ok' : 'err');
    setTimeout(refreshStatus, 1200);
    if (r.ok) {
      setTimeout(checkAuthStatus, 2500);
      setTimeout(checkAuthStatus, 4500);
    }
  }
}

// ──────────────────────────────────────────────────────────
// Conversations
// ──────────────────────────────────────────────────────────
async function loadConversations() {
  const list = document.getElementById('convo-list');
  list.innerHTML = '<div style="color:var(--muted);padding:20px">Loading…</div>';
  const data = await api('/conversations');
  if (!data || data.length === 0) {
    list.innerHTML = '<div class="empty"><div class="empty-icon">💬</div>No conversations yet</div>';
    return;
  }
  list.innerHTML = data.map(u => {
    const initials = (u.name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase();
    const ago      = u.last_active ? timeAgo(u.last_active) : '—';
    const handle   = u.username ? ` <span class="convo-handle">@${esc(u.username)}</span>` : '';
    const tgLink   = u.username ? `<a href="https://t.me/${esc(u.username)}" target="_blank" class="btn btn-ghost btn-sm">Open ↗</a>` : '';
    return `<div class="convo-item ${u.muted?'muted-item':''}" id="ci-${u.user_id}">
      <div class="avatar">${initials}</div>
      <div class="convo-info">
        <div class="convo-name">${esc(u.name)}${handle}</div>
        <div class="convo-preview">${esc(u.last_message||'No messages yet')}</div>
      </div>
      <div class="convo-right">
        <div class="convo-time">${ago}</div>
        <div class="convo-count">${u.message_count} msg${u.message_count===1?'':'s'}</div>
      </div>
      <div class="convo-actions">
        ${tgLink}
        <label class="toggle" title="${u.muted?'Resume replies':'Pause replies'}">
          <input type="checkbox" ${u.muted?'':'checked'} onchange="toggleMute(${u.user_id},this)">
          <span class="tslider"></span>
        </label>
      </div>
    </div>`;
  }).join('');
}

async function toggleMute(uid, el) {
  const r = await api('/conversations/' + uid + '/toggle-mute', 'POST');
  if (!r?.ok) { el.checked = !el.checked; toast('Failed', 'err'); return; }
  const item = document.getElementById('ci-' + uid);
  if (item) item.classList.toggle('muted-item', r.muted);
  toast(r.muted ? 'Replies paused' : 'Replies resumed', 'ok');
}

// ──────────────────────────────────────────────────────────
// Prompt editor
// ──────────────────────────────────────────────────────────
async function loadPrompt() {
  const cfg = await api('/config');
  if (!cfg) return;
  const ta = document.getElementById('prompt-editor');
  ta.value = cfg.system_prompt || '';
  updateCharCount();
}

function updateCharCount() {
  const len = document.getElementById('prompt-editor').value.length;
  document.getElementById('char-count').textContent = len.toLocaleString() + ' chars';
}

async function savePrompt() {
  const p = document.getElementById('prompt-editor').value.trim();
  if (!p) { toast('Prompt cannot be empty', 'err'); return; }
  const r = await api('/config', 'POST', { system_prompt: p });
  toast(r?.ok ? '✓ Prompt saved — active immediately' : 'Save failed', r?.ok ? 'ok' : 'err');
}

// ──────────────────────────────────────────────────────────
// Schedule
// ──────────────────────────────────────────────────────────
async function loadSchedule() {
  const cfg = await api('/config');
  if (!cfg) return;
  document.getElementById('force-inactive').checked    = cfg.force_inactive || false;
  document.getElementById('win-start').value            = cfg.window_start_hour ?? 1;
  document.getElementById('win-end').value              = cfg.window_end_hour ?? 23;
  document.getElementById('win-jitter-min').value       = cfg.window_jitter_min_minutes ?? 10;
  document.getElementById('win-jitter-max').value       = cfg.window_jitter_max_minutes ?? 75;
  const delayMode = cfg.reply_delay_mode ?? 'range';
  document.getElementById('delay-mode-range').checked = delayMode === 'range';
  document.getElementById('delay-mode-wpm').checked   = delayMode === 'wpm';
  document.getElementById('reply-delay-min').value      = cfg.reply_delay_min ?? 3;
  document.getElementById('reply-delay-max').value      = cfg.reply_delay_max ?? 5;
  document.getElementById('typing-wpm').value           = cfg.typing_wpm ?? 40;
  updateDelayMode();
  document.getElementById('pb-api-key').value           = cfg.pushbullet_api_key ?? '';
  document.getElementById('fcm-server-key').value        = cfg.fcm_service_account ?? '';
  document.getElementById('notify-owner').value         = cfg.notify_owner_name ?? 'Matheesha';
  document.getElementById('notify-new-chatter').checked = cfg.notify_new_chatter ?? true;
  document.getElementById('notify-threshold').value     = cfg.notify_message_threshold ?? 5;
  document.getElementById('recheck-enabled').checked    = cfg.recheck_enabled ?? true;
  document.getElementById('recheck-accuracy').value     = cfg.recheck_accuracy ?? 80;
  document.getElementById('reply-temperature').value    = cfg.reply_temperature ?? 0.9;
  document.getElementById('reply-max-tokens').value     = cfg.reply_max_tokens ?? 80;
  document.getElementById('recheck-temperature').value  = cfg.recheck_temperature ?? 0.5;
  document.getElementById('recheck-max-tokens').value   = cfg.recheck_max_tokens ?? 100;
  document.getElementById('bot-timezone').value         = cfg.timezone ?? 'Asia/Colombo';
  // Initialise break scheduler to today
  const todayStr = new Date().toISOString().slice(0,10);
  const breakDateEl = document.getElementById('break-date');
  breakDateEl.value = breakDateEl.value || todayStr;
  loadBreaks(breakDateEl.value);
}

// ──────────────────────────────────────────────────────────
// Break Scheduler
// ──────────────────────────────────────────────────────────
async function loadBreaks(dateStr) {
  const el = document.getElementById('break-list');
  if (!dateStr) { el.innerHTML = ''; return; }
  const breaks = await fetch('/api/breaks/' + dateStr).then(r=>r.json()).catch(()=>[]);
  if (!Array.isArray(breaks) || breaks.length === 0) {
    el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">No breaks scheduled for this date.</div>';
    return;
  }
  el.innerHTML = breaks.map((b, i) => `
    <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--border)">
      <span style="font-size:13px;flex:1">⏸ <strong>${esc(b.start)}</strong> → <strong>${esc(b.end)}</strong></span>
      <button class="btn" style="padding:3px 10px;font-size:12px;background:var(--danger,#e53e3e);color:#fff;border:none;border-radius:6px;cursor:pointer" onclick="deleteBreak('${esc(dateStr)}',${i})">Remove</button>
    </div>`).join('');
}

async function addBreak() {
  const dateStr = document.getElementById('break-date').value;
  const start   = document.getElementById('break-start').value;
  const end     = document.getElementById('break-end').value;
  if (!dateStr) { toast('Select a date first', 'err'); return; }
  if (!start || !end) { toast('Enter start and end times', 'err'); return; }
  if (start >= end) { toast('Start must be before end', 'err'); return; }
  const r = await api('/breaks/' + dateStr, 'POST', { start, end });
  if (r?.ok) {
    toast('Break added', 'ok');
    loadBreaks(dateStr);
    refreshScheduleOverview();
  } else {
    toast(r?.error || 'Failed to add break', 'err');
  }
}

async function deleteBreak(dateStr, idx) {
  const r = await api('/breaks/' + dateStr + '/' + idx, 'DELETE');
  if (r?.ok) {
    toast('Break removed', 'ok');
    loadBreaks(dateStr);
    refreshScheduleOverview();
  } else {
    toast(r?.error || 'Failed', 'err');
  }
}

function updateDelayMode() {
  const isWpm = document.getElementById('delay-mode-wpm').checked;
  document.getElementById('delay-range-section').style.display = isWpm ? 'none' : '';
  document.getElementById('delay-wpm-section').style.display   = isWpm ? '' : 'none';
}

async function saveSchedule() {
  const jMin = parseInt(document.getElementById('win-jitter-min').value);
  const jMax = parseInt(document.getElementById('win-jitter-max').value);
  const dMin = parseFloat(document.getElementById('reply-delay-min').value);
  const dMax = parseFloat(document.getElementById('reply-delay-max').value);
  const delayMode = document.getElementById('delay-mode-wpm').checked ? 'wpm' : 'range';
  const tz = document.getElementById('bot-timezone').value.trim() || 'Asia/Colombo';
  if (jMin > jMax) { toast('Jitter min must be ≤ max', 'err'); return; }
  if (delayMode === 'range' && dMin > dMax) { toast('Reply delay min must be ≤ max', 'err'); return; }
  try { Intl.DateTimeFormat(undefined, { timeZone: tz }); }
  catch(e) { toast('Invalid timezone — use IANA format e.g. Asia/Colombo', 'err'); return; }
  const r = await api('/config', 'POST', {
    force_inactive:             document.getElementById('force-inactive').checked,
    window_start_hour:          parseInt(document.getElementById('win-start').value),
    window_end_hour:            parseInt(document.getElementById('win-end').value),
    window_jitter_min_minutes:  jMin,
    window_jitter_max_minutes:  jMax,
    reply_delay_mode:           delayMode,
    reply_delay_min:            dMin,
    reply_delay_max:            dMax,
    typing_wpm:                 parseInt(document.getElementById('typing-wpm').value) || 40,
    pushbullet_api_key:         document.getElementById('pb-api-key').value.trim(),
    fcm_service_account:         document.getElementById('fcm-server-key').value.trim(),
    notify_owner_name:          document.getElementById('notify-owner').value.trim() || 'Matheesha',
    notify_new_chatter:         document.getElementById('notify-new-chatter').checked,
    notify_message_threshold:   parseInt(document.getElementById('notify-threshold').value) || 0,
    recheck_enabled:             document.getElementById('recheck-enabled').checked,
    recheck_accuracy:            parseInt(document.getElementById('recheck-accuracy').value) || 80,
    reply_temperature:           parseFloat(document.getElementById('reply-temperature').value) || 0.9,
    reply_max_tokens:            parseInt(document.getElementById('reply-max-tokens').value) || 80,
    recheck_temperature:         parseFloat(document.getElementById('recheck-temperature').value) || 0.5,
    recheck_max_tokens:          parseInt(document.getElementById('recheck-max-tokens').value) || 100,
    timezone:                    tz,
  });
  toast(r?.ok ? '✓ Saved — window hours take effect tomorrow' : 'Save failed', r?.ok ? 'ok' : 'err');
  setTimeout(refreshStatus, 400);
  loadBreaks(document.getElementById('break-date').value);
  refreshScheduleOverview();
}

// ──────────────────────────────────────────────────────────
// Analytics
// ──────────────────────────────────────────────────────────
Chart.defaults.color           = '#5a6480';
Chart.defaults.borderColor     = '#222540';
Chart.defaults.font.family     = '-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
Chart.defaults.font.size       = 11;

async function loadAnalytics() {
  const d = await api('/analytics');
  if (!d) return;
  const s = d.summary;

  document.getElementById('an-top').textContent       = s.top_user   || '—';
  document.getElementById('an-top-count').textContent = s.top_user_count + ' messages';
  document.getElementById('an-peak').textContent      = s.peak_hour  || '—';
  document.getElementById('an-rate').textContent      = s.response_rate + '%';
  document.getElementById('an-avg').textContent       = s.avg_per_day;
  document.getElementById('an-new').textContent       = s.new_today;

  // Daily messages line chart
  if (charts.daily) charts.daily.destroy();
  charts.daily = new Chart(document.getElementById('ch-daily'), {
    type: 'line',
    data: {
      labels: d.daily_labels,
      datasets: [{
        label: 'Messages',
        data: d.daily_values,
        borderColor: '#a855f7',
        backgroundColor: 'rgba(168,85,247,.08)',
        borderWidth: 2,
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#a855f7',
        pointRadius: 3,
        pointHoverRadius: 5,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#1a1d30' } },
        y: { grid: { color: '#1a1d30' }, beginAtZero: true, ticks: { precision: 0 } },
      }
    }
  });

  // Top chatters horizontal bar
  if (charts.top) charts.top.destroy();
  const bgColors = d.top_chatters.map((_,i) => `hsl(${270+i*18},65%,${60-i*3}%)`);
  charts.top = new Chart(document.getElementById('ch-top'), {
    type: 'bar',
    data: {
      labels: d.top_chatters.map(c=>c.name),
      datasets: [{
        label: 'Messages',
        data: d.top_chatters.map(c=>c.count),
        backgroundColor: bgColors,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#1a1d30' }, ticks: { precision: 0 } },
        y: { grid: { display: false } },
      }
    }
  });

  // Hourly distribution bar
  if (charts.hourly) charts.hourly.destroy();
  const maxH = Math.max(...d.hourly_values, 1);
  charts.hourly = new Chart(document.getElementById('ch-hourly'), {
    type: 'bar',
    data: {
      labels: d.hourly_labels,
      datasets: [{
        label: 'Messages',
        data: d.hourly_values,
        backgroundColor: d.hourly_values.map(v => v === maxH && v > 0 ? '#ec4899' : 'rgba(168,85,247,.35)'),
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: '#1a1d30' }, beginAtZero: true, ticks: { precision: 0 } },
      }
    }
  });
}

// ──────────────────────────────────────────────────────────
// Utilities
// ──────────────────────────────────────────────────────────
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function timeAgo(iso) {
  try {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return Math.floor(diff/60)   + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600)  + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
  } catch { return '—'; }
}

// ──────────────────────────────────────────────────────────
// Notes
// ──────────────────────────────────────────────────────────
let _notes = [];

async function loadNotes() {
  const list = document.getElementById('notes-list');
  list.innerHTML = '<div style="color:var(--muted);padding:20px">Loading…</div>';
  const data = await api('/notes');
  _notes = data || [];
  if (!_notes.length) {
    list.innerHTML = '<div class="empty"><div class="empty-icon">📝</div>No notes yet — add one to give the AI day-specific instructions</div>';
    return;
  }
  const todayStr = new Date().toISOString().slice(0,10);
  // Group by date
  const byDate = {};
  _notes.forEach(n => {
    const d = n.date || '';
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(n);
  });
  list.innerHTML = Object.entries(byDate)
    .sort(([a],[b]) => a < b ? -1 : 1)
    .map(([d, notes]) => {
      let dateLabel = d;
      try { dateLabel = new Date(d + 'T12:00:00').toLocaleDateString('en-US', {weekday:'long',year:'numeric',month:'long',day:'numeric'}); } catch {}
      const isToday   = d === todayStr;
      const isFuture  = d > todayStr;
      const isPast    = d < todayStr;
      const badge = isToday
        ? '<span style="background:rgba(52,211,153,.15);color:var(--success);border:1px solid rgba(52,211,153,.3);padding:2px 9px;border-radius:6px;font-size:11px;font-weight:700">TODAY</span>'
        : isFuture
        ? '<span style="background:rgba(168,85,247,.12);color:var(--accent);border:1px solid rgba(168,85,247,.3);padding:2px 9px;border-radius:6px;font-size:11px;font-weight:700">UPCOMING</span>'
        : '<span style="background:rgba(90,100,128,.12);color:var(--muted);border:1px solid rgba(90,100,128,.2);padding:2px 9px;border-radius:6px;font-size:11px;font-weight:600">PAST</span>';
      return `<div class="card" style="margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
          <span style="font-weight:700;font-size:14px">${esc(dateLabel)}</span>${badge}
        </div>
        ${notes.map(n => `
          <div style="display:flex;gap:12px;align-items:flex-start;padding:12px;background:var(--surface2);border-radius:10px;margin-bottom:8px;flex-wrap:wrap">
            <div style="flex:1;min-width:0">
              ${(n.time || n.title) ? `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap">
                ${n.time ? `<span style="font-size:11px;color:var(--accent);font-weight:700;background:rgba(168,85,247,.1);padding:2px 7px;border-radius:5px">⏰ ${esc(n.time)}</span>` : ''}
                ${n.title ? `<span style="font-weight:600;font-size:13px">${esc(n.title)}</span>` : ''}
              </div>` : ''}
              <div style="color:var(--muted);font-size:12px;line-height:1.65;white-space:pre-wrap">${esc(n.content)}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0;padding-top:2px">
              <button class="btn btn-ghost btn-sm" onclick="editNote('${n.id}')">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteNote('${n.id}')">Delete</button>
            </div>
          </div>`).join('')}
      </div>`;
    }).join('');
}

function openNoteModal(id) {
  const modal = document.getElementById('note-modal');
  document.getElementById('note-modal-title').textContent = id ? 'Edit Note' : 'Add Note';
  document.getElementById('note-edit-id').value = id || '';
  if (!id) {
    // Default to today
    document.getElementById('note-date').value    = new Date().toISOString().slice(0,10);
    document.getElementById('note-time').value    = '';
    document.getElementById('note-title').value   = '';
    document.getElementById('note-content').value = '';
  }
  modal.style.display = 'flex';
}

function editNote(id) {
  const n = _notes.find(x => x.id === id);
  if (!n) return;
  document.getElementById('note-date').value    = n.date    || '';
  document.getElementById('note-time').value    = n.time    || '';
  document.getElementById('note-title').value   = n.title   || '';
  document.getElementById('note-content').value = n.content || '';
  openNoteModal(id);
}

function closeNoteModal() {
  document.getElementById('note-modal').style.display = 'none';
}

async function saveNote() {
  const d = document.getElementById('note-date').value.trim();
  const c = document.getElementById('note-content').value.trim();
  if (!d) { toast('Please select a date', 'err'); return; }
  if (!c) { toast('Note content cannot be empty', 'err'); return; }
  const payload = {
    date:    d,
    time:    document.getElementById('note-time').value.trim(),
    title:   document.getElementById('note-title').value.trim(),
    content: c,
  };
  const editId = document.getElementById('note-edit-id').value;
  let r;
  if (editId) {
    r = await api('/notes/' + editId, 'PUT', payload);
  } else {
    r = await api('/notes', 'POST', payload);
  }
  if (r?.ok) {
    toast(editId ? '✓ Note updated' : '✓ Note saved', 'ok');
    closeNoteModal();
    loadNotes();
  } else {
    toast(r?.error || 'Save failed', 'err');
  }
}

async function deleteNote(id) {
  if (!confirm('Delete this note?')) return;
  const r = await api('/notes/' + id, 'DELETE');
  if (r?.ok) { toast('Note deleted', 'ok'); loadNotes(); }
  else        toast('Delete failed', 'err');
}

// ──────────────────────────────────────────────────────────
// Auth modal
// ──────────────────────────────────────────────────────────
let _authStep = null;

async function checkAuthStatus() {
  const s = await api('/auth/status');
  if (!s || !s.step) {
    if (_authStep) hideAuthModal();
    _authStep = null;
    return;
  }
  if (s.step !== _authStep) {
    _authStep = s.step;
    showAuthModal(s.step, s.phone);
  }
}

function showAuthModal(step, phone) {
  const modal = document.getElementById('auth-modal');
  const inp   = document.getElementById('auth-input');
  const sub   = document.getElementById('auth-subtitle');
  modal.style.display = 'flex';
  if (step === 'code') {
    sub.innerHTML       = `A verification code was sent to <strong>${esc(phone || 'your Telegram')}</strong>. Enter it below:`;
    inp.type            = 'text';
    inp.inputMode       = 'numeric';
    inp.style.letterSpacing = '8px';
    inp.placeholder     = '· · · · ·';
  } else {
    sub.textContent     = 'This account has 2-step verification enabled. Enter your cloud password:';
    inp.type            = 'password';
    inp.inputMode       = '';
    inp.style.letterSpacing = '4px';
    inp.placeholder     = 'Cloud password';
  }
  inp.value = '';
  document.getElementById('auth-error').textContent = '';
  setTimeout(() => inp.focus(), 120);
}

function hideAuthModal() {
  document.getElementById('auth-modal').style.display = 'none';
  document.getElementById('auth-input').value = '';
  document.getElementById('auth-error').textContent = '';
}

async function submitAuth() {
  const inp = document.getElementById('auth-input');
  const val = inp.value.trim();
  if (!val) { document.getElementById('auth-error').textContent = 'Please enter a value'; return; }
  document.getElementById('auth-error').textContent = '';
  inp.disabled = true;
  const r = await api('/auth/submit', 'POST', { value: val });
  inp.disabled = false;
  if (r?.ok) {
    toast('Submitted — authenticating…', 'ok');
    hideAuthModal();
    _authStep = null;
  } else {
    document.getElementById('auth-error').textContent = 'Submission failed — try again';
    inp.focus();
  }
}

setInterval(checkAuthStatus, 2000);
checkAuthStatus();

// ──────────────────────────────────────────────────────────
// Users & Invites tab
// ──────────────────────────────────────────────────────────
const ALL_PERMS = Object.keys(PERM_LABELS);

async function loadUsersTab() {
  loadUsersList();
  loadInvitesList();
}

let _usersMap = {};

async function loadUsersList() {
  const el = document.getElementById('users-list');
  if (!el) return;
  el.innerHTML = '<div style="color:var(--muted)">Loading…</div>';
  const data = await api('/users');
  _usersMap = {};
  if (data) data.forEach(u => _usersMap[u.id] = u);
  if (!data || !data.length) {
    el.innerHTML = '<div style="color:var(--muted)">No users found</div>';
    return;
  }
  el.innerHTML = data.map(u => {
    const roleBadge = u.role === 'admin'
      ? '<span class="user-role-badge role-admin">ADMIN</span>'
      : '<span class="user-role-badge role-user">USER</span>';
    const permsHtml = u.role === 'admin'
      ? '<span style="color:var(--muted);font-size:12px">All permissions</span>'
      : (u.permissions.length
          ? u.permissions.map(p => `<span class="perm-tag">${esc(PERM_LABELS[p]||p)}</span>`).join('')
          : '<span style="color:var(--muted);font-size:12px">No permissions</span>');
    const isSelf  = u.id === ME.id;
    const isAdmin = u.role === 'admin';
    const editBtn = (!isAdmin && !isSelf)
      ? `<button class="btn btn-ghost btn-sm" onclick="openEditPermsModal('${esc(u.id)}')">Edit Perms</button>`
      : '';
    const delBtn = !isSelf
      ? `<button class="btn btn-danger btn-sm" onclick="deleteUser('${esc(u.id)}','${esc(u.username)}')">Remove</button>`
      : '';
    return `<div class="user-row">
      <div class="avatar" style="width:38px;height:38px;font-size:13px">${esc((u.username||'?')[0].toUpperCase())}</div>
      <div class="user-info">
        <div class="user-name">${esc(u.username)} ${roleBadge}${isSelf?' <span style="color:var(--muted);font-size:11px">(you)</span>':''}</div>
        <div style="margin-top:5px;flex-wrap:wrap;display:flex;gap:2px">${permsHtml}</div>
      </div>
      <div style="display:flex;gap:6px;flex-shrink:0">${editBtn}${delBtn}</div>
    </div>`;
  }).join('');
}

async function deleteUser(uid, username) {
  if (!confirm(`Remove user "${username}"? This cannot be undone.`)) return;
  const r = await api('/users/' + uid, 'DELETE');
  if (r?.ok) { toast('User removed', 'ok'); loadUsersList(); }
  else toast(r?.error || 'Delete failed', 'err');
}

function openEditPermsModal(uid) {
  const u = _usersMap[uid];
  if (!u) return;
  document.getElementById('edit-perms-uid').value = uid;
  document.getElementById('edit-perms-subtitle').textContent = `Editing: ${u.username}`;
  const currentPerms = u.permissions || [];
  const grid = document.getElementById('edit-perms-grid');
  grid.innerHTML = ALL_PERMS.map(p => `
    <label class="perm-check-item">
      <input type="checkbox" value="${p}" ${currentPerms.includes(p)?'checked':''}>
      ${esc(PERM_LABELS[p]||p)}
    </label>`).join('');
  document.getElementById('edit-perms-modal').style.display = 'flex';
}

async function saveUserPerms() {
  const uid   = document.getElementById('edit-perms-uid').value;
  const perms = [...document.querySelectorAll('#edit-perms-grid input:checked')].map(i=>i.value);
  const r     = await api('/users/' + uid + '/permissions', 'PUT', {permissions: perms});
  if (r?.ok) {
    toast('Permissions updated', 'ok');
    document.getElementById('edit-perms-modal').style.display = 'none';
    loadUsersList();
  } else toast(r?.error || 'Save failed', 'err');
}

async function loadInvitesList() {
  const el = document.getElementById('invites-list');
  if (!el) return;
  el.innerHTML = '<div style="color:var(--muted)">Loading…</div>';
  const data = await api('/invites');
  if (!data || !data.length) {
    el.innerHTML = '<div style="color:var(--muted)">No invite codes yet — generate one above</div>';
    return;
  }
  el.innerHTML = data.map(inv => {
    const usedBadge = inv.used
      ? `<span style="background:rgba(248,113,113,.12);color:var(--danger);border:1px solid rgba(248,113,113,.2);padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700">USED${inv.used_by?' by '+esc(inv.used_by):''}</span>`
      : `<span style="background:rgba(52,211,153,.12);color:var(--success);border:1px solid rgba(52,211,153,.2);padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700">ACTIVE</span>`;
    const permsHtml = inv.permissions.length
      ? inv.permissions.map(p=>`<span class="perm-tag">${esc(PERM_LABELS[p]||p)}</span>`).join('')
      : '<span style="color:var(--muted);font-size:11px">No permissions</span>';
    const delBtn = !inv.used
      ? `<button class="btn btn-danger btn-sm" onclick="deleteInvite('${esc(inv.code)}')">Revoke</button>`
      : '';
    return `<div class="invite-row">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
          <span class="invite-code ${inv.used?'invite-used':''}">${esc(inv.code)}</span>
          ${usedBadge}
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:2px">${permsHtml}</div>
        <div style="color:var(--muted);font-size:11px;margin-top:4px">Created by ${esc(inv.created_by)} · ${inv.created_at ? new Date(inv.created_at+'Z').toLocaleString() : '—'}</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
        ${!inv.used?`<button class="btn btn-ghost btn-sm" onclick="copyText('${esc(inv.code)}')">Copy</button>`:''}
        ${delBtn}
      </div>
    </div>`;
  }).join('');
}

function openInviteModal() {
  const grid = document.getElementById('invite-perms-grid');
  grid.innerHTML = ALL_PERMS.map(p => `
    <label class="perm-check-item">
      <input type="checkbox" value="${p}">
      ${esc(PERM_LABELS[p]||p)}
    </label>`).join('');
  document.getElementById('invite-modal').style.display = 'flex';
}

async function createInvite() {
  const perms = [...document.querySelectorAll('#invite-perms-grid input:checked')].map(i=>i.value);
  const r     = await api('/invites', 'POST', {permissions: perms});
  if (!r?.ok) { toast(r?.error || 'Failed', 'err'); return; }
  document.getElementById('invite-modal').style.display     = 'none';
  document.getElementById('invite-code-display').textContent = r.code;
  document.getElementById('invite-result-modal').style.display = 'flex';
  loadInvitesList();
}

async function deleteInvite(code) {
  if (!confirm('Revoke this invite code?')) return;
  const r = await api('/invites/' + code, 'DELETE');
  if (r?.ok) { toast('Invite revoked', 'ok'); loadInvitesList(); }
  else toast(r?.error || 'Failed', 'err');
}

let _inviteCodeToCopy = '';
function copyInviteCode() {
  const code = document.getElementById('invite-code-display').textContent;
  copyText(code);
  toast('Code copied!', 'ok');
}

function copyText(text) {
  navigator.clipboard?.writeText(text).catch(()=>{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  });
  toast('Copied!', 'ok');
}
</script>
</body>
</html>"""


@app.route("/")
@login_required
def dashboard():
    import json as _json
    user_data = _json.dumps(current_user.to_dict())
    # Inject user context before </head>
    injected = DASHBOARD_HTML.replace(
        "</head>",
        f'<script>window.__USER__={user_data};</script>\n</head>',
        1,
    )
    return injected


if __name__ == "__main__":
    print("🎀  FanBot Dashboard  →  http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
