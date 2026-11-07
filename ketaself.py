#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KetaSelf Ultra v4.2 — Modern Telegram Selfbot & Interactive Inline Panel
========================================================================
Updated for the Latest Telegram Bot API & MTProto Features:
- Modern Telegram HTML UI: Expandable Blockquotes (<blockquote expandable>),
  Spoiler tags (<tg-spoiler>), Copyable badges, and Custom Emoji (<tg-emoji>) support.
- LinkPreviewOptions & Message Effect IDs support.
- Full Anti-Crash / FloodWait Resilience across all background loops and handlers.
- Expanded Feature Set:
    1. Timed Media & View-Once Auto-Saver (Photos, Videos, Voice, Video Notes)
    2. Anti-Delete & Anti-Edit Logger (Text + Media Backup in Saved Messages)
    3. Anti-Scam, Fake Account Detector & Advanced User Profiler (.check / .whois)
    4. Smart Secretary (Auto-Reply) with Offline Detection, Cooldown & Custom Exceptions
    5. Live Profile Clock (Name + Bio) with 5 Unicode Font Styles + Bio Rotator
    6. Continuous Online / Fake Action Simulation (Typing, Voice, Game, Video)
    7. Restricted Channel / Group Content Downloader (.dl) + Direct Link Saver
    8. Enemy / Auto-Roast Mode & Friend Auto-Love / Reaction Mode (.addenemy, .addfriend)
    9. Instant Text Translator, Calculator, Font Styler, and Text Animations
   10. Multi-Target Scheduled Auto-Messenger & Chat Backup / Cleanup Tools
   11. v4: Protected / linkless / private-channel downloader (albums, ranges, topics,
       comments, invite-join, live watch mode, progress bar, attribute-preserving re-upload)
   12. v4: Premium Emoji Studio (.setpe / .pepack / auto-replace / .emojiid / panel emoji)
   13. v4: Instagram / YouTube / TikTok via third-party downloader bots (zero server download)
   14. v4: One .fetch command, unified quick help, queue, cancellation, quality picker,
       duplicate-in-queue protection, and status summary
   15. v4.2: Telegram-native Rich Messages in inline panel and callback screens:
       structured headings and styled callback buttons (not parse_mode HTML)

Prerequisites:
    pip install -U 'telethon>=1.44' jdatetime python-dotenv aiohttp

Setup:
1. Obtain API_ID and API_HASH from https://my.telegram.org
2. Create a helper bot via @BotFather, copy BOT_TOKEN, and enable Inline Mode (/setinline).
3. Configure via .env file or edit the variables below, then run:
   python3 ketaself.py
"""

import os
import re
import sys
import html
import json
import time
import ast
import operator
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from telethon import TelegramClient, events, functions, types, Button
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, MessageNotModifiedError, RPCError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateStatusRequest
from telethon.tl.functions.messages import SendReactionRequest, SetTypingRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.channels import GetParticipantRequest

from telethon.extensions import html as _tl_html


class ZeroHTML:
    """HTML parse mode that really supports <tg-emoji>, <tg-spoiler>, <a href="emoji/ID">
    and <blockquote expandable> on any Telethon 1.x version."""

    @staticmethod
    def parse(text):
        flags = []

        def _bq(m):
            flags.append(bool(m.group(1)))
            return "<blockquote>"
        text = re.sub(r"<blockquote(\s+expandable)?\s*>", _bq, text)
        text = re.sub(r"<tg-emoji\s+emoji-id=[\"']?(\d+)[\"']?\s*>", r'<a href="emoji/\1">', text)
        text = text.replace("</tg-emoji>", "</a>")
        text = text.replace("<tg-spoiler>", '<a href="spoiler">').replace("</tg-spoiler>", "</a>")
        msg, ents = _tl_html.parse(text)
        out = []
        for e in ents:
            if isinstance(e, types.MessageEntityTextUrl):
                if e.url == "spoiler":
                    e = types.MessageEntitySpoiler(e.offset, e.length)
                elif e.url.startswith("emoji/"):
                    e = types.MessageEntityCustomEmoji(e.offset, e.length, int(e.url[6:]))
            out.append(e)
        bqs = sorted([e for e in out if isinstance(e, types.MessageEntityBlockquote)], key=lambda x: x.offset)
        for e, f in zip(bqs, flags):
            if f:
                try:
                    e.collapsed = True
                except Exception:
                    pass
        return msg, out

    @staticmethod
    def unparse(text, entities):
        return _tl_html.unparse(text, entities)


ZHTML = ZeroHTML()


def input_rich_html(text: str):
    """Build Telegram's native InputRichMessageHTML (not parse_mode HTML)."""
    ctor = getattr(types, "InputRichMessageHTML", None)
    if ctor is None:
        raise RuntimeError("Native Rich Messages need Telethon 1.44+; upgrade with pip install -U 'telethon>=1.44'")
    return ctor(html=text, rtl=True)


def rich_panel_html(text: str, buttons=None) -> str:
    """Translate panel content into Telegram's structured Rich HTML and native Rich buttons."""
    import re as _re
    import html as _html
    out = text
    # Give the main panel and section titles real heading blocks, not merely bold spans.
    out = _re.sub(
        r"🪐\s*<b>Z E R O S E L F</b>\s*<code>ULTRA v[0-9.]+</code>",
        "<h1>🪐 KetaSelf Ultra</h1>", out, count=1
    )
    out = _re.sub(
        r"🪐\s*<b>KetaSelf</b>\s*›\s*(.*?)\n\n",
        r"<h2>🪐 KetaSelf › \1</h2>", out, count=1, flags=_re.S
    )
    rows = []
    for row in buttons or []:
        cells = []
        for wrapped in row:
            button = getattr(wrapped, "button", wrapped)
            label = getattr(wrapped, "text", getattr(button, "text", "Button"))
            data = getattr(wrapped, "data", getattr(button, "data", b""))
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            label = _html.escape(str(label), quote=False)
            data = _html.escape(str(data), quote=True)
            style = "danger" if any(x in str(label).lower() for x in ("بستن", "close", "حذف", "پاک")) else "success"
            cells.append(f'<tg-button type="callback" style="{style}" data="{data}">{label}</tg-button>')
        if cells:
            rows.append('<tg-button-row align="center">' + "".join(cells) + "</tg-button-row>")
    if rows:
        out += "\n" + "\n".join(rows)
    return out


def pipe_text_to_rich_html(text):
    """Convert tabular plain panel text (pipe rows) to native Rich HTML tables.

    Header rows become <th>, data rows become <td>, other lines become <p>.
    Lines that already carry <h2>/<p> tags (e.g. the close message) pass through.
    """
    import html as _html

    out = []
    in_table = False

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</table>")
            in_table = False

    for raw in text.split(chr(10)):
        ln = raw.strip()
        if not ln:
            close_table()
            continue
        if "<h2>" in ln or "<p>" in ln:
            close_table()
            out.append(ln)
            continue
        plain = _html.unescape(re.sub(r"<[^>]+>", "", ln)).strip()
        if not plain:
            continue
        if set(plain) == {"-"}:
            continue
        if " | " in plain:
            cells = [c.strip() for c in plain.split(" | ")]
            if not in_table:
                out.append("<table>")
                in_table = True
            tag = "th" if cells[0] in ("مورد", "دستور", "بخش") else "td"
            out.append("<tr>" + "".join(f"<{tag}>{_html.escape(c, quote=False)}</{tag}>" for c in cells) + "</tr>")
            continue
        close_table()
        out.append(f"<p>{_html.escape(plain, quote=False)}</p>")
    close_table()
    return chr(10).join(out)


async def edit_rich_panel(event, text: str, buttons=None):
    """Show a panel screen as a native Rich Message.

    Callback edits cannot carry Rich tables (Rich is only accepted at inline
    send time), so this delivers the screen as a fresh Rich inline message
    and deletes the old panel message. On any failure it falls back to the
    plain in-place edit, so a panel screen is never lost.
    """
    if buttons:
        buttons = colorize_buttons(buttons)
    try:
        import uuid as _uuid

        key = "panelx" + _uuid.uuid4().hex[:12]
        html = pipe_text_to_rich_html(text)
        PANEL_RICH_CACHE[key] = (html, buttons)
        results = await user_client.inline_query(BOT_USERNAME, key)
        if results:
            await results[0].click(event.chat_id)
            try:
                await event.delete()
            except Exception:
                pass
            return
    except Exception as e:
        logger.error(f"Panel rich delivery failed, falling back to plain edit: {e}")
    try:
        return await event.edit(text, buttons=buttons, parse_mode=ZHTML, link_preview=False)
    except Exception as e:
        logger.error(f"Panel edit failed: {e}")
        raise


try:
    import jdatetime
    HAS_JDATETIME = True
except ImportError:
    HAS_JDATETIME = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# 1. LOGGING & CONFIGURATION
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("KetaSelfUltra")

API_ID = int(os.getenv("API_ID", "12345678"))                    # From https://my.telegram.org
API_HASH = os.getenv("API_HASH", "your_api_hash_here")           # From https://my.telegram.org
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_helper_bot_token_here") # From @BotFather

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")

# --- Railway deploy (2026-11-07): DATA_DIR + shared Gemini pool ---
# DATA_DIR: Railway Volume mount (e.g. /data). Sessions + config + downloads
# live under it so redeploys don't wipe them. Empty = current directory.
DATA_DIR = Path(os.getenv("DATA_DIR", "") or ".")
DB_PATH = DATA_DIR / "ketaself_config.json"
DOWNLOAD_DIR = DATA_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Shared Gemini key pool: one env var, used by BOTH text (.ai) and voice (.tts).
# GEMINI_API_KEYS: keys separated by comma / newline / semicolon. 1-30 keys.
# Never log a key value; logs only ever show the key count / index.
GEMINI_KEYS_MIN = 1
GEMINI_KEYS_MAX = 30
_GEMINI_BAD_UNTIL = {}  # key -> epoch seconds until which the key is skipped
_GEMINI_NEXT_IDX = 0


def _gemini_parse_keys(raw):
    seen = []
    for part in re.split(r"[,;\s]+", raw or ""):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return seen


GEMINI_KEYS = _gemini_parse_keys(os.getenv("GEMINI_API_KEYS", ""))
if GEMINI_KEYS and not (GEMINI_KEYS_MIN <= len(GEMINI_KEYS) <= GEMINI_KEYS_MAX):
    logger.warning("GEMINI_API_KEYS has %d keys (allowed %d-%d); extra keys ignored", len(GEMINI_KEYS), GEMINI_KEYS_MIN, GEMINI_KEYS_MAX)
    GEMINI_KEYS = GEMINI_KEYS[:GEMINI_KEYS_MAX]
if not GEMINI_KEYS and LLM_API_KEY:
    GEMINI_KEYS = [LLM_API_KEY]


def _gemini_next_key():
    """Round-robin next healthy key, or None. Skips keys in cooldown."""
    global _GEMINI_NEXT_IDX
    now = time.time()
    for _ in range(len(GEMINI_KEYS)):
        key = GEMINI_KEYS[_GEMINI_NEXT_IDX % len(GEMINI_KEYS)]
        _GEMINI_NEXT_IDX += 1
        if _GEMINI_BAD_UNTIL.get(key, 0) <= now:
            return key
    return None


def _gemini_mark_bad(key, cooldown_sec=600):
    _GEMINI_BAD_UNTIL[key] = time.time() + cooldown_sec


def _gemini_key_index(key):
    try:
        return GEMINI_KEYS.index(key)
    except ValueError:
        return -1


# Optional SOCKS5 proxy for the MTProto connection (e.g. if you are behind a
# firewall that blocks Telegram). Leave TELEGRAM_PROXY_HOST empty for a direct
# connection (the default). No proxy is used on Railway (RAILWAY_ENVIRONMENT
# is set) or when NO_PROXY=1.
_TELEGRAM_PROXY_HOST = os.getenv("TELEGRAM_PROXY_HOST", "").strip()
_TELEGRAM_PROXY_PORT = int(os.getenv("TELEGRAM_PROXY_PORT", "0") or 0)
_TG_PROXY = None
if not (os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("NO_PROXY") == "1"):
    if _TELEGRAM_PROXY_HOST and _TELEGRAM_PROXY_PORT:
        _TG_PROXY = ("socks5", _TELEGRAM_PROXY_HOST, _TELEGRAM_PROXY_PORT)

# Optional SOCKS5 proxy for yt-dlp / curl / aiohttp calls
# (e.g. "socks5://127.0.0.1:1080"). Empty = direct connection (the default).
HTTP_PROXY_URL = os.getenv("HTTP_PROXY_URL", "").strip()
_HTTP_PROXY_ARGS = ["--proxy", HTTP_PROXY_URL] if HTTP_PROXY_URL else []
_TG_SESSION_DIR = DATA_DIR if os.getenv("DATA_DIR") else Path(".")

# /start attribution on the helper bot ("made by" + GitHub link).
MAKER_NAME = os.getenv("MAKER_NAME", "achhlhzadh9-ctrl")
MAKER_GITHUB_URL = os.getenv("MAKER_GITHUB_URL", "https://github.com/achhlhzadh9-ctrl")
START_TIME = time.time()

DEFAULT_CONFIG: Dict[str, Any] = {
    "prefix": ".",
    "profile": {
        "time_name": False,
        "time_bio": False,
        "base_name": "",
        "base_bio": "🪐 KetaSelf Ultra User",
        "bios_list": [],              # لیست بیوهای چرخشی
        "online_mode": False,
        "fake_action": "none",        # none | typing | voice | game | video
        "font_style": "bold_serif"    # bold_serif | mono | double | script | normal
    },
    "secretary": {
        "enabled": False,
        "text": "سلام! در حال حاضر آفلاین هستم؛ پیامتون ثبت شد و در اولین فرصت پاسخ میدم 🌹",
        "cooldown_sec": 1800,
        "only_when_offline": False,
        "media_reply": True
    },
    "backup": {
        "save_timed_media": True,     # ذخیره خودکار عکس/ویدیو/ویس تایمدار (یک‌بار مصرف)
        "anti_delete_pv": True,       # ذخیره پیام و مدیای حذف‌شده در پی‌وی
        "anti_delete_groups": False,  # ذخیره پیام‌های حذف‌شده در گروه‌ها
        "anti_edit_pv": True,         # گزارش ویرایش پیام در پی‌وی
        "save_restricted": True,      # کشیدن محتوا از کانال‌های قفل‌شده
        "dump_chat": "me",            # مقصد ذخیره‌ها (me = Saved Messages)
        "watch_chats": [],            # چت‌هایی که هر پست جدیدشان خودکار کپی می‌شود
        "dl_footer": True             # افزودن منبع به کپشن
    },
    "social_dl": {
        "auto_link": False,           # لینک اینستا/یوتیوب/تیک‌تاک بفرستی، خودکار تبدیل به ویدیو می‌شود
        "clean_trace": True,          # پاک کردن پیام‌ها در چت ربات دانلودر
        "timeout": 90,
        "quality": "720",
        "bots": {                     # با .setdl عوض کن؛ اولی کار نکرد، بعدی امتحان می‌شود
            "ig": ["@SaveAsBot"],
            "tt": ["@SaveAsBot"],
            "yt": ["@SaveAsBot"],
            "other": []
        }
    },
    "auto_msg": {
        "enabled": False,
        "interval_min": 60,
        "text": "📌 پیام خودکار زمان‌بندی شده",
        "targets": []
    },
    "security": {
        "anti_scam_save": True,       # بررسی خودکار اکانت‌های Scam/Fake و ذخیره گزارش
        "pv_lock": False,             # قفل پی‌وی برای افراد ناشناس
        "anti_spam_pv": True,         # محدودکننده رگباری پی‌وی (موت خودکار اسپمرها)
        "spam_limit": 8,
        "whitelist": [],
        "muted_users": []
    },
    "fun_social": {
        "enemy_mode": True,
        "enemies": [],                # لیست دشمن‌ها (پاسخ خودکار رگباری)
        "enemy_replies": [
            "فشار نخور عزیزم 🥱",
            "صدات از جای گرم درمیاد؟ 😂",
            "فعلاً درگیرم، بعداً بیا بررسیت کنم 🤏",
            "سطحت به این حرفا نمی‌خوره ✨"
        ],
        "friends": [],                # لیست دوستان ویژه (ری‌اکشن خودکار ویژه)
        "friend_emoji": "❤️‍🔥"
    },
    "text_style": {
        "mode": "none",               # none | bold | mono | italic | spoiler | strike | quote
        "auto_english_fix": False
    },
    "animation": {
        "typing_effect": False,
        "effect_speed": 0.05
    },
    "premium": {
        "auto_react_pv": False,
        "react_emoji": "❤️",
        "use_custom_emoji": False,    # جایگزینی خودکار ایموجی معمولی با پریمیوم در پیام‌هایت
        "bot_custom_emoji": True,     # ایموجی پریمیوم در ظاهر پنل (نیازمند یوزرنیم Fragment برای ربات)
        "emoji_map": {},              # ایموجی معمولی → document_id
        "ui_emoji": {}
    }
}


class ConfigManager:
    """Thread-safe persistent JSON configuration with deep schema merging."""

    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _deep_merge(self, default: dict, loaded: dict) -> dict:
        result = json.loads(json.dumps(default))
        for k, v in loaded.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                merged = self._deep_merge(DEFAULT_CONFIG, raw)
                return merged
            except Exception as e:
                logger.error(f"Failed loading config, using defaults: {e}")
        return json.loads(json.dumps(DEFAULT_CONFIG))

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed saving config: {e}")

    def toggle(self, section: str, key: str) -> bool:
        self.data[section][key] = not bool(self.data[section].get(key, False))
        self.save()
        return self.data[section][key]


db = ConfigManager(DB_PATH)

# Sessions: on hosted deploys (Railway / Docker) supply StringSession strings
# via SESSION_STRING / HELPER_SESSION_STRING (see setup_session.py) — no file
# upload needed. Without them, local .session files under DATA_DIR are used.


def _make_client(session_name: str, session_string: str) -> TelegramClient:
    if session_string:
        return TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=_TG_PROXY)
    return TelegramClient(str(_TG_SESSION_DIR / session_name), API_ID, API_HASH, proxy=_TG_PROXY)


user_client = _make_client("ketaself_user", os.getenv("SESSION_STRING", "").strip())
bot_client = _make_client("ketaself_helper", os.getenv("HELPER_SESSION_STRING", "").strip())
# Rich HTML (bold, code, quotes, spoilers, custom emoji) is the default for both clients.
# Individual calls can still pass formatting_entities for Telegram-native entities.
user_client.parse_mode = ZHTML
bot_client.parse_mode = ZHTML

OWNER_ID: Optional[int] = None
BOT_USERNAME: Optional[str] = None

# Runtime Caches
SECRETARY_MEMORY: Dict[int, float] = {}
SPAM_TRACKER: Dict[int, List[float]] = {}
MESSAGE_CACHE: Dict[Tuple[int, int], Dict[str, Any]] = {}
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(1)
DOWNLOAD_JOBS: Dict[int, Dict[str, Any]] = {}
DOWNLOAD_JOB_COUNTER = 0


async def enqueue_download(chat_id: int, status_msg, title: str, work, dedupe_key: str = ""):
    """Queue one transfer at a time, with visible queue position, dedupe and cancellation."""
    global DOWNLOAD_JOB_COUNTER
    if dedupe_key:
        existing = next((j for j in DOWNLOAD_JOBS.values()
                         if j["chat_id"] == chat_id and j.get("dedupe_key") == dedupe_key), None)
        if existing:
            await status_msg.edit(f"ℹ️ این لینک از قبل تو صفه، شماره <code>#{existing['id']}</code>.", parse_mode=ZHTML)
            return existing["id"]
    DOWNLOAD_JOB_COUNTER += 1
    job_id = DOWNLOAD_JOB_COUNTER
    job = {"id": job_id, "chat_id": chat_id, "title": title, "state": "queued", "status": status_msg,
           "dedupe_key": dedupe_key}
    DOWNLOAD_JOBS[job_id] = job

    async def runner():
        try:
            if not DOWNLOAD_SEMAPHORE.locked():
                await status_msg.edit(f"🚀 <b>شروع شد:</b> {esc(title)}", parse_mode=ZHTML)
            else:
                ahead = sum(1 for x in DOWNLOAD_JOBS.values() if x["state"] == "queued" and x["id"] < job_id)
                await status_msg.edit(
                    f"🕒 <b>صف دانلود</b> · جایگاه <code>{ahead + 1}</code>\n{esc(title)}",
                    parse_mode=ZHTML
                )
            async with DOWNLOAD_SEMAPHORE:
                job["state"] = "running"
                await work()
        except asyncio.CancelledError:
            try:
                await status_msg.edit("⏹ دانلود لغو شد.", parse_mode=ZHTML)
            except Exception:
                pass
            raise
        except Exception as e:
            logger.exception("Download job failed")
            try:
                await status_msg.edit(f"❌ <b>دانلود ناموفق:</b> <code>{esc(e)}</code>", parse_mode=ZHTML)
            except Exception:
                pass
        finally:
            DOWNLOAD_JOBS.pop(job_id, None)

    task = asyncio.create_task(runner(), name=f"download-{job_id}")
    job["task"] = task
    return job_id


# ==============================================================================
# 2. UI / UX HELPERS & UNICODE FONTS (LATEST TELEGRAM HTML FEATURES)
# ==============================================================================

FONT_MAPS = {
    "bold_serif": str.maketrans("0123456789:", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗:"),
    "mono":       str.maketrans("0123456789:", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿:"),
    "double":     str.maketrans("0123456789:", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:"),
    "script":     str.maketrans("0123456789:", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵:"),
    "normal":     str.maketrans("0123456789:", "0123456789:")
}

EN_FANCY_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
)

PERSIAN_KEYBOARD_LAYOUT = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./",
    "ضصثقفغعهخحجچشسیبلاتنمکگظطزرذدپو./"
)

def format_clock() -> str:
    now_str = datetime.now().strftime("%H:%M")
    style = db.data["profile"].get("font_style", "bold_serif")
    mapper = FONT_MAPS.get(style, FONT_MAPS["bold_serif"])
    return now_str.translate(mapper)

def get_jalali_date() -> str:
    if HAS_JDATETIME:
        return jdatetime.datetime.now().strftime("%Y/%m/%d")
    return datetime.now().strftime("%Y-%m-%d")

def get_uptime() -> str:
    seconds = int(time.time() - START_TIME)
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

def badge(state: bool) -> str:
    return "🟢 روشن" if state else "🔴 خاموش"

def esc(text: Any) -> str:
    return html.escape(str(text or ""))

def safe_math_eval(expr: str) -> float:
    """Safely evaluates mathematical expressions without eval() security risks."""
    allowed_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
    }
    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.operand))
        raise ValueError("عبارت ریاضی نامعتبر است")
    return _eval(ast.parse(expr, mode="eval").body)


# ==============================================================================
# 3. MODERN INLINE GLASS PANEL BUILDER (TELEGRAM 2026 HTML UI)
# ==============================================================================

SECTION_TITLES = {
    "profile": ("👤", "پروفایل و حضور"), "prefix": ("⌨️", "پیشوند دستورها"),
    "backup": ("🗂", "ذخیره و بازیابی"), "secretary": ("🤖", "منشی خودکار"),
    "automsg": ("📅", "پیام‌های خودکار"), "security": ("🔒", "امنیت و آنتی‌اسکم"),
    "downloader": ("🧲", "دانلودر ضد قفل تلگرام"), "social_dl": ("🌐", "اینستا · یوتیوب · تیک‌تاک"), "music": ("🎵", "موزیک فایندر"),
    "premium": ("💎", "استودیو ایموجی پریمیوم"), "funsocial": ("⚔️", "دشمن و دوست"),
    "animation": ("✨", "انیمیشن ارسال"), "textstyle": ("🎨", "استایل متن"),
    "tools": ("🛠", "ابزارها"), "help": ("📖", "راهنمای بات"), "sub": ("📊", "وضعیت سیستم"),
}


def _dot(v: bool) -> str:
    return "🟢" if v else "⚫️"


MAIN_PANEL_ROWS = [
    ("👤 پروفایل و حضور", "ساعت زنده، بیو، آنلاین دائمی، اکشن چت"),
    ("⌨️ پیشوند دستورها", "عوض کردن پیشوند دستورها"),
    ("🤖 منشی خودکار", "پاسخ خودکار به پیام‌های پی‌وی"),
    ("🗂 ذخیره و بازیابی", "سیو تایمدار و آنتی‌دلیت"),
    ("📅 پیام‌های خودکار", "ارسال دوره‌ای به چت‌های هدف"),
    ("🔒 امنیت", "اسکم، قفل پی‌وی، ضد اسپم"),
    ("🧲 دانلودر", "پست قفل‌شده تلگرام"),
    ("🌐 اینستا و یوتیوب", "دانلود اجتماعی از ربات ثالث"),
    ("🎵 موزیک فایندر", "جستجو و دانلود کامل آهنگ"),
    ("💎 ایموجی پریمیوم", "ایموجی سفارشی و جایگزینی خودکار"),
    ("🛠 ابزارها", "محاسبه، ترجمه، حذف، تگ و..."),
    ("✨ انیمیشن ارسال", "تایپ، قلب، بارگذاری، تاس"),
    ("🎨 استایل متن", "فرمت خودکار پیام‌های خروجی"),
    ("⚔️ دشمن و دوست", "پاسخ و ری‌اکشن خودکار"),
    ("📖 راهنمای سریع", "راهنمای کامل بات"),
    ("📊 وضعیت سیستم", "آپتایم و نسخه"),
]


def tabularize_panel_text(text):
    """Turn a panel section's blockquote/bullet text into ordered pipe-table rows.

    Callback edits cannot carry native Rich tables (Rich is only accepted at
    inline-send time), so sections are tabular plain text: each row on its own
    line, label | value, command | job. Paragraphs are kept as-is.
    """
    import re as _re
    import html as _html

    def plain(s):
        return _html.unescape(_re.sub(r"<[^>]+>", "", s)).strip()

    out = []
    table_kind = None

    def flush():
        nonlocal table_kind
        if table_kind:
            out.append("----------------------------------------")
            table_kind = None

    def start(kind, header):
        nonlocal table_kind
        if table_kind != kind:
            flush()
            out.append(header)
            out.append("----------------------------------------")
            table_kind = kind

    for raw in text.split(chr(10)):
        ln = raw.strip()
        ln = ln.replace("<blockquote>", "").replace("</blockquote>", "").replace("<blockquote expandable>", "").strip()
        if not ln:
            flush()
            continue
        m = _re.match(r"^(.*?)<b>([^<]+):</b>\s*(.*)$", ln)
        if m and plain(m.group(3)):
            prefix = plain(m.group(1))
            label = plain(m.group(2))
            value = plain(m.group(3))
            start("label", "مورد | مقدار")
            out.append(f"{prefix} {label} | {value}" if prefix else f"{label} | {value}")
            continue
        m2 = _re.match(r"^•\s*<code>([^<]+)</code>\s*(?:—|-|–)?\s*(.*)$", ln)
        if m2:
            cmd = plain(m2.group(1))
            desc = plain(m2.group(2))
            start("cmd", "دستور | کار")
            out.append(f"{cmd} | {desc}" if desc else cmd)
            continue
        flush()
        out.append(plain(ln))
    flush()
    return chr(10).join(out)


def build_main_panel_rich():
    rows = [[label, desc] for label, desc in MAIN_PANEL_ROWS]
    return "<h2>🪐 پنل اصلی کتاسلف</h2>" + chr(10) + "<p>بخشی که می‌خوای رو انتخاب کن:</p>" + chr(10) + rich_table(["بخش", "توضیح"], rows)


def colorize_buttons(buttons):
    """Give every panel button a Telethon 1.45 style color.

    primary (blue) = navigation and normal actions, like the rival panel.
    success (green) = a toggle that is ON, or a selected option.
    danger (red) = close, delete/clear, and a toggle that is OFF (matches the
    red dot in its badge). Buttons that are not callback buttons are left alone.
    Re-applying this is idempotent: the style comes from text/data, not the
    previous style, so already-colored buttons keep the same color.
    """
    out = []
    for row in buttons or []:
        new_row = []
        for btn in row:
            try:
                btype = getattr(btn, "type", None)
                data = getattr(btype, "data", None)
                if not isinstance(data, (bytes, bytearray)):
                    new_row.append(btn)
                    continue
                text = getattr(btn, "text", "") or ""
                d = data.decode("utf-8", errors="ignore")
                if d == "menu:close" or "بستن" in text or "✖️" in text:
                    style = "danger"
                elif any(w in text for w in ("پاکسازی", "پاک کردن", "حذف", "ریست")) or d.startswith(("auto:clear", "fun:clear", "dlt:clearwatch", "sec:reset")):
                    style = "danger"
                elif "🟢 روشن" in text:
                    style = "success"
                elif "🔴 خاموش" in text:
                    style = "danger"
                elif text.startswith("🔘"):
                    style = "success"
                else:
                    style = "primary"
                new_row.append(Button.inline(text, bytes(data), style=style))
            except Exception:
                new_row.append(btn)
        out.append(new_row)
    return out


def build_main_panel() -> Tuple[str, list]:
    B = Button.inline
    text = "🪐 <b>پنل اصلی کتاسلف</b>\n\nبخشی که می‌خوای رو انتخاب کن:\n\nبخش | توضیح\n----------------------------------------\n" + chr(10).join(f"{label} | {desc}" for label, desc in MAIN_PANEL_ROWS)
    buttons = [
        [B("👤 پروفایل و حضور", b"menu:profile"), B("⌨️ پیشوند دستورها", b"menu:prefix")],
        [B("🤖 منشی خودکار", b"menu:secretary"), B("🗂 ذخیره و بازیابی", b"menu:backup")],
        [B("📅 پیام‌های خودکار", b"menu:automsg"), B("🔒 امنیت", b"menu:security")],
        [B("🧲 دانلودر", b"menu:downloader"), B("🌐 اینستا و یوتیوب", b"menu:social_dl")],
        [B("🎵 موزیک فایندر", b"menu:music"), B("💎 ایموجی پریمیوم", b"menu:premium")],
        [B("🛠 ابزارها", b"menu:tools"), B("✨ انیمیشن ارسال", b"menu:animation")],
        [B("🎨 استایل متن", b"menu:textstyle"), B("⚔️ دشمن و دوست", b"menu:funsocial")],
        [B("📖 راهنمای سریع", b"menu:help"), B("📊 وضعیت سیستم", b"menu:sub")],
        [B("✖️ بستن پنل", b"menu:close")],
    ]
    return text, colorize_buttons(buttons)


def build_sub_panel(section: str) -> Tuple[str, list]:
    """Wraps every sub panel with a unified header, breadcrumb and nav bar."""
    text, buttons = _build_sub_panel_raw(section)
    text = tabularize_panel_text(text)
    icon, title = SECTION_TITLES.get(section, ("◈", section))
    header = f"{pe('🪐')} <b>KetaSelf</b> › {pe(icon)} <b>{title}</b>\n"
    text = header + "\n" + text + f"\n\n<i>🕐 {datetime.now().strftime('%H:%M:%S')}  ·  v4.2</i>"
    nav = [Button.inline("🏠 خانه", b"menu:main"),
           Button.inline("🔄", f"menu:{section}".encode()),
           Button.inline("✖️ بستن", b"menu:close")]
    clean = [row for row in buttons
             if not (len(row) == 1 and getattr(row[0], "data", None) == b"menu:main")]
    clean.append(nav)
    return text, colorize_buttons(clean)


def _build_sub_panel_raw(section: str) -> Tuple[str, list]:
    p = esc(db.data["prefix"])

    if section == "profile":
        prof = db.data["profile"]
        text = (
            "👤 <b>مدیریت پروفایل، ساعت زنده و اکشن‌ها</b>\n"
            "<blockquote>"
            f"🏷 <b>نام پایه:</b> <code>{esc(prof['base_name'] or 'تنظیم نشده')}</code>\n"
            f"📝 <b>بیو پایه:</b> <code>{esc(prof['base_bio'] or 'تنظیم نشده')}</code>\n"
            f"🎭 <b>اکشن چت:</b> <code>{prof['fake_action']}</code> | <b>فونت:</b> <code>{prof['font_style']}</code>"
            "</blockquote>\n"
            "<blockquote expandable>"
            "💡 <b>دستورات خطی مرتبط:</b>\n"
            f"• <code>{p}setname نام</code> — تنظیم نام اصلی\n"
            f"• <code>{p}setbio متن</code> — تنظیم بیوگرافی پایه\n"
            f"• <code>{p}addbio متن</code> — افزودن بیو به لیست چرخشی\n"
            f"• <code>{p}clearbios</code> — پاکسازی لیست بیوهای چرخشی\n"
            f"• <code>{p}clone</code> (ریپلای) — کپی کامل نام و بیو کاربر"
            "</blockquote>"
        )
        buttons = [
            [
                Button.inline(f"ساعت نام: {badge(prof['time_name'])}", b"toggle:profile:time_name"),
                Button.inline(f"ساعت بیو: {badge(prof['time_bio'])}", b"toggle:profile:time_bio")
            ],
            [
                Button.inline(f"آنلاین دائمی: {badge(prof['online_mode'])}", b"toggle:profile:online_mode"),
                Button.inline(f"فونت ({prof['font_style']})", b"cycle:font")
            ],
            [
                Button.inline("✍️ تایپینگ", b"faction:typing"),
                Button.inline("🎙 ویس", b"faction:voice"),
                Button.inline("🎮 بازی", b"faction:game"),
                Button.inline("⏹ غیرفعال", b"faction:none")
            ],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "prefix":
        text = (
            "⌨️ <b>تنظیم پیشوند دستورات (Command Prefix)</b>\n"
            "<blockquote>"
            f"پیشوند فعلی سلف‌بات شما: <code>{p}</code>\n"
            f"مثال اجرا: <code>{p}ping</code> یا <code>{p}پنل</code>"
            "</blockquote>\n"
            "یکی از نمادهای زیر را به عنوان پیشوند جدید انتخاب کنید:"
        )
        buttons = [
            [
                Button.inline("نقطه ( . )", b"setprefix:."),
                Button.inline("تعجب ( ! )", b"setprefix:!"),
                Button.inline("اسلش ( / )", b"setprefix:/")
            ],
            [
                Button.inline("شارپ ( # )", b"setprefix:#"),
                Button.inline("ستاره ( * )", b"setprefix:*"),
                Button.inline("موج ( ~ )", b"setprefix:~")
            ],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "backup":
        bkp = db.data["backup"]
        text = (
            "🗂 <b>ذخیره خودکار مدیا زماندار و آنتی‌دلیت</b>\n"
            "<blockquote>"
            "🔥 <b>سیو زماندار (View-Once / TTL):</b> عکس‌ها، ویدیوها و ویس‌های تایمدار به محض دریافت در پی‌وی دانلود شده و در <b>Saved Messages</b> ذخیره می‌شوند.\n"
            "🗑 <b>آنتی‌دلیت و آنتی‌ادیت:</b> هر پیام متنی یا فایلی که در پی‌وی دوطرفه پاک یا ویرایش شود، فوری با مشخصات فرستنده برایتان ارسال می‌گردد."
            "</blockquote>\n"
            f"💡 دستور ذخیره دستی با ریپلای: <code>{p}save</code> یا <code>{p}سیو</code>"
        )
        buttons = [
            [Button.inline(f"🔥 سیو خودکار عکس/ویدیو زماندار: {badge(bkp['save_timed_media'])}", b"toggle:backup:save_timed_media")],
            [Button.inline(f"🗑 آنتی‌دلیت پی‌وی (متن + مدیا): {badge(bkp['anti_delete_pv'])}", b"toggle:backup:anti_delete_pv")],
            [Button.inline(f"✏️ گزارش ویرایش پیام (Anti-Edit): {badge(bkp['anti_edit_pv'])}", b"toggle:backup:anti_edit_pv")],
            [Button.inline(f"👥 آنتی‌دلیت گروه‌ها: {badge(bkp['anti_delete_groups'])}", b"toggle:backup:anti_delete_groups")],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "secretary":
        sec = db.data["secretary"]
        text = (
            "🤖 <b>منشی هوشمند خودکار (Auto-Secretary)</b>\n"
            "<blockquote>"
            f"📡 <b>وضعیت منشی:</b> {badge(sec['enabled'])}\n"
            f"⏳ <b>فاصله عدم تکرار:</b> هر <code>{sec['cooldown_sec'] // 60}</code> دقیقه یک‌بار برای هر نفر\n"
            f"💬 <b>متن پاسخ فعلی:</b>\n<i>{esc(sec['text'])}</i>"
            "</blockquote>\n"
            f"💡 تغییر متن منشی: <code>{p}setreply متن جدید شما</code>"
        )
        buttons = [
            [Button.inline(f"وضعیت منشی خودکار: {badge(sec['enabled'])}", b"toggle:secretary:enabled")],
            [Button.inline(f"فقط در زمان آفلاین بودن: {badge(sec['only_when_offline'])}", b"toggle:secretary:only_when_offline")],
            [
                Button.inline("⏱ ۱۵ دقیقه", b"seccd:900"),
                Button.inline("⏱ ۳۰ دقیقه", b"seccd:1800"),
                Button.inline("⏱ ۶۰ دقیقه", b"seccd:3600")
            ],
            [Button.inline("🧹 ریست حافظه منشی", b"sec:reset")],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "security":
        sec = db.data["security"]
        text = (
            "🔒 <b>امنیت، رادار آنتی‌اسکم و قفل پی‌وی</b>\n"
            "<blockquote>"
            "🚨 <b>سیو از اکانت اسکم:</b> به محض پیام دادن اکانت‌های دارای برچسب Scam یا Fake یا بدون نام، مشخصات کامل و آیدی عددی آن‌ها در سیو مسیج ثبت می‌شود.\n"
            "🛡 <b>آنتی‌اسپم پی‌وی:</b> اگر فردی در پی‌وی پیام رگباری بفرستد، خودکار سکوت (Mute) می‌شود."
            "</blockquote>\n"
            "<blockquote expandable>"
            "💡 <b>دستورات امنیتی:</b>\n"
            f"• <code>{p}check</code> یا <code>{p}whois</code> — استعلام کامل اکانت و ذخیره در سیو مسیج\n"
            f"• <code>{p}wl</code> — افزودن کاربر به لیست سفید پی‌وی\n"
            f"• <code>{p}mute</code> / <code>{p}unmute</code> — سکوت یا رفع سکوت کاربر در پی‌وی\n"
            f"• <code>{p}block</code> / <code>{p}unblock</code> — مسدودسازی سریع"
            "</blockquote>"
        )
        buttons = [
            [Button.inline(f"🚨 شناسایی و سیو اکانت اسکم: {badge(sec['anti_scam_save'])}", b"toggle:security:anti_scam_save")],
            [Button.inline(f"🔐 قفل کامل پی‌وی (PV Lock): {badge(sec['pv_lock'])}", b"toggle:security:pv_lock")],
            [Button.inline(f"🛡 ضد اسپم رگباری پی‌وی: {badge(sec['anti_spam_pv'])}", b"toggle:security:anti_spam_pv")],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "automsg":
        am = db.data["auto_msg"]
        text = (
            "📅 <b>ارسال پیام‌های خودکار زمان‌بندی‌شده</b>\n"
            "<blockquote>"
            f"📡 <b>وضعیت:</b> {badge(am['enabled'])}\n"
            f"⏱ <b>فاصله ارسال:</b> هر <code>{am['interval_min']}</code> دقیقه\n"
            f"🎯 <b>تعداد چت‌های هدف:</b> <code>{len(am['targets'])}</code> چت\n"
            f"📝 <b>متن پیام:</b> <code>{esc(am['text'])}</code>"
            "</blockquote>\n"
            f"• افزودن چت فعلی: <code>{p}addauto</code> | حذف چت: <code>{p}delauto</code>\n"
            f"• تغییر متن: <code>{p}setautotext متن دلخواه</code>"
        )
        buttons = [
            [Button.inline(f"ارسال دوره‌ای: {badge(am['enabled'])}", b"toggle:auto_msg:enabled")],
            [
                Button.inline("⏱ ۱۰ دقیقه", b"autoint:10"),
                Button.inline("⏱ ۳۰ دقیقه", b"autoint:30"),
                Button.inline("⏱ ۶۰ دقیقه", b"autoint:60"),
                Button.inline("⏱ ۱۲۰ دقیقه", b"autoint:120")
            ],
            [Button.inline("🗑 پاکسازی لیست چت‌های هدف", b"auto:clear")],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "downloader":
        bk = db.data["backup"]
        text = (
            "<blockquote>"
            "با اکانت خودت (MTProto) هر پستی که <b>می‌بینی</b> رو می‌گیرم، حتی اگه کپی/فوروارد/ذخیره بسته باشه. "
            "پست‌های غیرقفل بدون دانلود (با رفرنس) کپی میشن؛ قفل‌دارها دانلود و با همون کپشن، تامبنیل و مشخصات آپلود میشن."
            "</blockquote>\n"
            f"📥 <b>مقصد:</b> <code>{esc(bk.get('dump_chat', 'me'))}</code> · 👁 <b>رصد:</b> <code>{len(bk.get('watch_chats', []))}</code> چت\n"
            "<blockquote expandable>"
            "<b>🔗 با لینک</b>\n"
            f"• <code>{p}dl https://t.me/c/123/45</code> کانال خصوصی\n"
            f"• <code>{p}dl https://t.me/c/123/10-60</code> بازه (تا ۲۰۰ پست)\n"
            f"• تاپیک، <code>?comment=</code> و چند لینک پشت هم هم ساپورت میشه\n\n"
            "<b>🚫 پست بدون لینک</b> (پی‌وی، گروه معمولی، ربات‌ها)\n"
            f"• ریپلای + <code>{p}dl</code> · آلبوم کامل گرفته میشه\n"
            f"• <code>{p}msgid</code> ریپلای → شماره پیام، بعد <code>{p}dl 120-150</code> تو همون چت\n"
            f"• <code>{p}dlfind کلمه</code> جستجو و ذخیره مدیاهای چت\n\n"
            "<b>🔐 کانال خصوصی</b>\n"
            f"• <code>{p}join https://t.me/+hash</code> عضویت (یا ارسال درخواست)\n"
            f"• <code>{p}watch</code> تو کانال = کپی خودکار هر پست جدید · <code>{p}unwatch</code>\n"
            f"• <code>{p}dump</code> مقصد = همین چت · <code>{p}dump me</code> برگشت به Saved"
            "</blockquote>"
        )
        buttons = [
            [Button.inline(f"منبع در کپشن: {badge(bk.get('dl_footer', True))}", b"dlt:dl_footer")],
            [Button.inline("🗑 پاک کردن لیست رصد", b"dlt:clearwatch"),
             Button.inline("📥 مقصد → Saved", b"dlt:dumpme")],
        ]

    elif section == "social_dl":
        sd = db.data["social_dl"]
        bots = sd["bots"]
        text = (
            "<blockquote>"
            "دانلود روی <b>سرور تو انجام نمیشه</b>: لینک از اکانتت به ربات‌های دانلودر عمومی فرستاده میشه، "
            "اونا دانلود می‌کنن و فایل با رفرنس تلگرام (بدون مصرف پهنای باند تو) برات فرستاده میشه."
            "</blockquote>\n"
            f"📸 <b>Instagram:</b> <code>{esc(' → '.join(bots.get('ig', [])) or '—')}</code>\n"
            f"▶️ <b>YouTube:</b> <code>{esc(' → '.join(bots.get('yt', [])) or '—')}</code>\n"
            f"🎵 <b>TikTok:</b> <code>{esc(' → '.join(bots.get('tt', [])) or '—')}</code>\n"
            f"🎞 <b>کیفیت:</b> <code>{esc(sd.get('quality', '720'))}p</code>\n"
            f"🧩 <b>پشتیبان:</b> <code>{esc(' → '.join(bots.get('other', [])) or '—')}</code>\n"
            "<blockquote expandable>"
            f"• <code>{p}get لینک</code> یا <code>{p}ig</code> / <code>{p}yt</code> / <code>{p}tt</code> (یا ریپلای روی لینک)\n"
            f"• <code>{p}setdl ig @bot1 @bot2</code> ترتیب ربات‌ها (اولی نشد، بعدی)\n"
            "• دانلود خودکار روشن باشه: هر لینکی بفرستی خودش ویدیو میشه\n"
            "• ربات‌هایی که جوین اجباری دارن رد میشن؛ دکمه کیفیت خودکار زده میشه"
            "</blockquote>"
        )
        buttons = [
            [Button.inline(f"دانلود خودکار لینک: {badge(sd['auto_link'])}", b"toggle:social_dl:auto_link")],
            [Button.inline(f"پاکسازی چت ربات: {badge(sd['clean_trace'])}", b"toggle:social_dl:clean_trace")],
            [Button.inline("🎞 480p", b"sdq:480"), Button.inline("720p", b"sdq:720"), Button.inline("1080p", b"sdq:1080"), Button.inline("Max", b"sdq:max")],
            [Button.inline("⏱ 60s", b"sdt:60"), Button.inline("⏱ 90s", b"sdt:90"), Button.inline("⏱ 180s", b"sdt:180")],
        ]

    elif section == "premium":
        prem = db.data["premium"]
        uniq = len(set(prem.get("emoji_map", {}).values()))
        text = (
            "<blockquote>"
            f"{pe('💎')} <b>اکانت پریمیوم:</b> {'✨ بله' if ACCOUNT_PREMIUM else '❌ نه (فقط Saved Messages)'}\n"
            f"🎭 <b>ایموجی‌های ذخیره‌شده:</b> <code>{uniq}</code>\n"
            f"⚡ <b>ری‌اکشن پی‌وی:</b> {badge(prem['auto_react_pv'])} {prem['react_emoji']}"
            "</blockquote>\n"
            "<blockquote expandable>"
            f"• <code>{p}setpe</code> ریپلای روی پیام با ایموجی پریمیوم → ذخیره\n"
            f"• <code>{p}pepack</code> ریپلای → کل پک ایموجی یکجا وارد میشه\n"
            f"• <code>{p}pe متن 🔥</code> ارسال با ایموجی پریمیوم · <code>{p}pemap</code> لیست\n"
            f"• <code>{p}emojiid</code> شناسه ایموجی‌ها · <code>{p}delpe 🔥</code> حذف\n"
            f"• <code>{p}setui</code> ایموجی پریمیوم برای ظاهر پنل\n"
            "⚠️ پنل رو ربات می‌فرسته؛ تلگرام فقط برای ربات‌های دارای یوزرنیم Fragment ایموجی پریمیوم نشون میده."
            "</blockquote>"
        )
        buttons = [
            [Button.inline(f"جایگزینی خودکار: {badge(prem['use_custom_emoji'])}", b"toggle:premium:use_custom_emoji")],
            [Button.inline(f"ایموجی در پنل: {badge(prem['bot_custom_emoji'])}", b"toggle:premium:bot_custom_emoji")],
            [Button.inline(f"ری‌اکشن خودکار پی‌وی: {badge(prem['auto_react_pv'])}", b"toggle:premium:auto_react_pv")],
            [
                Button.inline("❤️", b"react:heart"), Button.inline("🔥", b"react:fire"),
                Button.inline("⚡", b"react:zap"), Button.inline("💎", b"react:gem"),
                Button.inline("👍", b"react:like"), Button.inline("🐳", b"react:whale")
            ],
        ]

    elif section == "funsocial":
        fs = db.data["fun_social"]
        text = (
            "⚔️ <b>مدیریت دشمنان (Auto-Roast) و دوستان ویژه</b>\n"
            "<blockquote>"
            f"🔥 <b>حالت پاسخ خودکار دشمن:</b> {badge(fs['enemy_mode'])}\n"
            f"💀 <b>تعداد دشمنان:</b> <code>{len(fs['enemies'])}</code> نفر\n"
            f"💖 <b>تعداد دوستان ویژه:</b> <code>{len(fs['friends'])}</code> نفر (ری‌اکشن خودکار {fs['friend_emoji']})"
            "</blockquote>\n"
            "<blockquote expandable>"
            "💡 <b>دستورات مدیریت (با ریپلای روی پیام فرد):</b>\n"
            f"• <code>{p}addenemy</code> — افزودن به لیست دشمن\n"
            f"• <code>{p}delenemy</code> — حذف از لیست دشمن\n"
            f"• <code>{p}addfriend</code> — افزودن به لیست دوستان ویژه\n"
            f"• <code>{p}delfriend</code> — حذف از لیست دوستان"
            "</blockquote>"
        )
        buttons = [
            [Button.inline(f"حالت پاسخ به دشمن: {badge(fs['enemy_mode'])}", b"toggle:fun_social:enemy_mode")],
            [
                Button.inline("🧹 پاکسازی لیست دشمنان", b"fun:clearenemies"),
                Button.inline("🧹 پاکسازی لیست دوستان", b"fun:clearfriends")
            ],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "animation":
        anim = db.data["animation"]
        text = (
            "✨ <b>انیمیشن‌های ارسال پیام و افکت‌های متنی</b>\n"
            "<blockquote>"
            f"⌨️ <b>افکت تایپ تدریجی دائمی:</b> {badge(anim['typing_effect'])}\n"
            "در صورت روشن بودن، پیام‌های کوتاه شما کاراکتر به کاراکتر با نشانگر تایپ می‌شوند."
            "</blockquote>\n"
            "💡 <b>دستورات انیمیشن تک‌بار:</b>\n"
            f"• <code>{p}type متن</code> — تایپ سینمایی متن\n"
            f"• <code>{p}heart</code> — انیمیشن تپش قلب رنگی\n"
            f"• <code>{p}load</code> — نوار بارگذاری متحرک ۱۰۰٪\n"
            f"• <code>{p}dice</code> / <code>{p}dart</code> — ارسال تاس یا دارت"
        )
        buttons = [
            [Button.inline(f"افکت تایپ دائمی: {badge(anim['typing_effect'])}", b"toggle:animation:typing_effect")],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "textstyle":
        mode = db.data["text_style"]["mode"]
        text = (
            "🎨 <b>استایل خودکار پیام‌های خروجی</b>\n"
            "<blockquote>"
            f"حالت فعلی: <code>{mode.upper()}</code>\n"
            "با انتخاب هر گزینه، تمام پیام‌های عادی شما به شکل خودکار با آن فرمت تزئین می‌شوند."
            "</blockquote>\n"
            f"💡 ابزار تبدیل کیبورد انگلیسی به فارسی (ریپلای): <code>{p}fa</code>"
        )
        buttons = [
            [
                Button.inline(f"{'🔘' if mode == 'none' else '⚪'} عادی", b"style:none"),
                Button.inline(f"{'🔘' if mode == 'bold' else '⚪'} ضخیم (Bold)", b"style:bold")
            ],
            [
                Button.inline(f"{'🔘' if mode == 'mono' else '⚪'} کد (Mono)", b"style:mono"),
                Button.inline(f"{'🔘' if mode == 'italic' else '⚪'} کج (Italic)", b"style:italic")
            ],
            [
                Button.inline(f"{'🔘' if mode == 'spoiler' else '⚪'} اسپویلر", b"style:spoiler"),
                Button.inline(f"{'🔘' if mode == 'quote' else '⚪'} نقل‌قول (Quote)", b"style:quote")
            ],
            [
                Button.inline(f"{'🔘' if mode == 'strike' else '⚪'} خط‌خورده", b"style:strike"),
                Button.inline(f"{'🔘' if mode == 'fancy' else '⚪'} فونت لاتین", b"style:fancy")
            ],
            [Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]
        ]

    elif section == "help":
        text = f"""<b>راهنمای کامل KetaSelf</b>
پنل با <code>{p}panel</code> باز می‌شود؛ هر بخش یعنی چه:

<b>👤 پروفایل:</b> ساعت زنده روی اسم و بیو، بیوهای چرخشی، آنلاین دائمی، اکشن چت (تایپینگ، ویس، بازی) و فونت ساعت.
<b>🤖 منشی:</b> وقتی آفلاینی، به پیام‌های پی‌وی جواب آماده می‌دهد؛ فاصله‌ی تکرار و فقط-آفلاین بودن قابل تنظیم است.
<b>🔒 امنیت:</b> شناسایی و ذخیره‌ی اکانت اسکم، قفل کامل پی‌وی و ضد اسپم رگباری پی‌وی.
<b>🧲 دانلودر ضد قفل:</b> دانلود پست کانال/گروه قفل‌شده و خصوصی با <code>{p}fetch</code>، عضویت با <code>{p}join</code>، رصد با <code>{p}watch</code> و انتخاب مقصد با <code>{p}dest</code>.
<b>🌐 اجتماعی:</b> دانلود اینستا، یوتیوب و تیک‌تاک از طریق ربات دانلودر ثالث، با انتخاب کیفیت و مهلت.
<b>💎 ایموجی پریمیوم:</b> ایموجی سفارشی در پنل، جایگزینی خودکار ایموجی در پیام‌ها و ری‌اکشن خودکار پی‌وی.
<b>🗂 بکاپ و آنتی‌دلیت:</b> ذخیره‌ی خودکار عکس/ویدیوی تایمدار و پیام‌های حذف یا ویرایش‌شده‌ی پی‌وی در Saved Messages.
<b>📅 خودکار:</b> ارسال دوره‌ای پیام به چت‌های هدف، با فاصله‌ی قابل تنظیم.
<b>✨ انیمیشن:</b> افکت تایپ دائمی هنگام ارسال پیام.
<b>🎨 استایل متن:</b> فرمت خودکار پیام‌های خروجی (عادی، ضخیم، مونو، کج، اسپویلر، نقل‌قول، خط‌خورده، فونت لاتین).
<b>⚔️ دشمن/دوست:</b> پاسخ و ری‌اکشن خودکار به افراد لیست دشمن و دوست.
<b>⌨️ پیشوند:</b> عوض کردن پیشوند دستورها بین . ! / # * ~
<b>🛠 ابزارها:</b> <code>{p}ping</code>، حذف پیام، <code>{p}calc</code>، اصلاح کیبورد با <code>{p}fa</code>، ترجمه با <code>{p}tr</code>، <code>{p}whois</code> و <code>{p}chatinfo</code>.
<b>📊 سیستم:</b> آپتایم، تعداد پیام‌های کش‌شده و نسخه‌ی بات.

<b>🎵 موزیک:</b> <code>{p}music اسم آهنگ</code> جستجوی کامل mp3، یا <code>{p}music لینک</code>.
<b>🧠 هوش مصنوعی:</b> <code>{p}ai سوال</code> پاسخ با سرچ وب، ریپلای با <code>{p}ai خلاصه کن</code> خلاصه پیام، <code>{p}ai واقعی؟</code> راستی‌آزمایی و <code>{p}ai ریچ کن</code> ریچ پیام، <code>{p}rich</code> هم همین کار را می‌کند، <code>{p}tts</code> صوت با احساس و صدای زن/مرد (متن خودت یا پیام ریپلای‌شده).

<b>دستورهای پایه:</b> <code>{p}panel</code> پنل، <code>{p}queue</code> صف دانلود، <code>{p}cancel</code> لغو، <code>{p}status</code> وضعیت، <code>{p}quality 720</code> کیفیت."""
        buttons = [[Button.inline("🚀 دریافت لینک", b"menu:social_dl")]]

    elif section == "music":
        text = f"""🎵 <b>موزیک فایندر + دانلود</b>
<blockquote>
بدون کانال اسپانسر و بدون جوین اجباری.
با <code>{p}music اسم آهنگ + خواننده</code> جستجو کن، از لیست شماره را انتخاب کن تا نسخه‌ی کامل mp3 همان آهنگ فرستاده شود.
یا مستقیم لینک بده: <code>{p}music لینک</code>
</blockquote>"""
        buttons = [[Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]]

    elif section == "tools":
        text = (
            "🛠 <b>جعبه ابزار حرفه‌ای کتاسلف</b>\n"
            "<blockquote expandable>"
            "⚡ <b>مدیریت پیام و چت:</b>\n"
            f"• <code>{p}ping</code> — تست پینگ و آپتایم\n"
            f"• <code>{p}del</code> — حذف پیام ریپلای شده\n"
            f"• <code>{p}purge 30</code> — حذف ۳۰ پیام اخیر چت\n"
            f"• <code>{p}purgeme 20</code> — حذف ۲۰ پیام آخر خودتان\n"
            f"• <code>{p}spam 5 متن</code> — ارسال رگباری پیام\n"
            f"• <code>{p}tagall متن</code> — تگ کردن اعضای گروه\n\n"
            "🧲 <b>دانلودر سریع:</b>\n"
            f"• <code>{p}fetch لینک</code> یا ریپلای روی مدیا/لینک · <code>{p}queue</code> · <code>{p}cancel</code>\n"
            f"• <code>{p}quality 720</code> تنظیم کیفیت · <code>{p}find کلمه</code> جستجو\n\n"
            "🧠 <b>ابزارهای هوشمند:</b>\n"
            f"• <code>{p}calc 25*14+10</code> — ماشین حساب دقیق\n"
            f"• <code>{p}fa</code> (ریپلای) — اصلاح تایپ اشتباه کیبورد انگلیسی به فارسی (مثلاً <code>sghl</code> ← <code>سلام</code>)\n"
            f"• <code>{p}tr fa</code> (ریپلای) — ترجمه فوری پیام به فارسی/انگلیسی\n"
            f"• <code>{p}whois</code> — استخراج شناسنامه کامل کاربر\n"
            f"• <code>{p}chatinfo</code> — آمار کامل گروه یا کانال"
            "</blockquote>"
        )
        buttons = [[Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]]

    else:  # sub / server status
        text = (
            "📊 <b>وضعیت سیستم و اشتراک کتاسلف اولترا</b>\n"
            "<blockquote>"
            "💎 <b>نسخه:</b> <code>KetaSelf Ultra v4.2 (VIP Edition)</code>\n"
            f"⏱ <b>مدت زمان روشن بودن (Uptime):</b> <code>{get_uptime()}</code>\n"
            f"📦 <b>پیام‌های کش شده در حافظه:</b> <code>{len(MESSAGE_CACHE)}</code> پیام\n"
            f"📅 <b>تاریخ سرور:</b> <code>{get_jalali_date()}</code>\n"
            "🔓 <b>اعتبار لایسنس:</b> <code>دائمی و بدون محدودیت</code>"
            "</blockquote>"
        )
        buttons = [[Button.inline("🔙 بازگشت به پنل اصلی", b"menu:main")]]

    return text, buttons


# ==============================================================================
# 4. HELPER BOT HANDLERS (INLINE QUERY & CALLBACKS)
# ==============================================================================

REACT_MAP = {
    "heart": "❤️",
    "fire": "🔥",
    "zap": "⚡",
    "gem": "💎",
    "like": "👍",
    "whale": "🐳"
}

FONT_CYCLE = ["bold_serif", "mono", "double", "script", "normal"]


@bot_client.on(events.NewMessage(pattern=r"^/start(\s|$)"))
async def start_handler(event: events.NewMessage.Event):
    """Public /start on the helper bot: made-by attribution + GitHub link."""
    text = (
        "🪐 <b>KetaSelf</b> — سلف‌بات تلگرام\n"
        f"ساخته شده توسط <a href=\"{MAKER_GITHUB_URL}\">{esc(MAKER_NAME)}</a>"
    )
    await event.reply(text, parse_mode=ZHTML)


@bot_client.on(events.InlineQuery)
async def inline_query_handler(event: events.InlineQuery.Event):
    if OWNER_ID and event.sender_id != OWNER_ID:
        await event.answer([event.builder.article(
            title="⛔ دسترسی محدود", text="⛔ این پنل خصوصی است.", parse_mode=ZHTML
        )], cache_time=5)
        return
    q_inline = (event.text or "").strip().lower()
    if q_inline.startswith("price"):
        html = PRICE_INLINE_CACHE.get("html")
        plain = PRICE_INLINE_CACHE.get("plain")
        if html and time.time() - PRICE_INLINE_CACHE.get("ts", 0) > PRICE_INLINE_TTL:
            html = None
            plain = None
        if not html:
            try:
                crypto2, ir2, dollar2, tgju_date2 = await get_price_data()
                table_lines = ["<b>ارز دیجیتال (تتر زنده)</b>", "ارز | قیمت (دلار) | قیمت (تومان) | تغییر", "----------------------------------------"]
                for sym in ["btc", "eth", "sol", "bnb", "usdt"]:
                    cid, label = PRICE_COINS[sym]
                    info = crypto2.get(cid) or {}
                    if info.get("usd") is not None:
                        chg2 = info.get("usd_24h_change")
                        chg_txt2 = f"{chg2:+.1f}%" if chg2 is not None else "-"
                        toman_txt2 = f"{fmt_toman(float(info['usd']) * dollar2)} تومان" if dollar2 else "-"
                        table_lines.append(f"{pe(PRICE_ICONS.get(sym, EMOJI))} {label} | {fmt_usd(info['usd'])} دلار | {toman_txt2} | {chg_txt2}")
                html = "<h2>قیمت‌های زنده</h2>" + chr(10) + lines_to_rich_table(table_lines)
                plain = chr(10).join(table_lines)
                PRICE_INLINE_CACHE.update({"html": html, "plain": plain, "ts": time.time()})
            except Exception:
                await event.answer([event.builder.article(
                    title="قیمت‌های زنده", text="برای قیمت زنده، اول .price بفرست.", parse_mode=ZHTML
                )], cache_time=5)
                return
        try:
            rich_result = types.InputBotInlineResult(
                id="price", type="article", title="قیمت‌های زنده", description="قیمت ارز دیجیتال، دلار و طلا",
                send_message=types.InputBotInlineMessageRichMessage(
                    rich_message=types.InputRichMessageHTML(html=html, rtl=True)
                ),
            )
            await event.answer([rich_result], cache_time=0)
        except Exception as e:
            logger.error(f"Price rich inline failed: {e}")
            await event.answer([event.builder.article(
                title="قیمت‌های زنده", text=plain or "قیمت‌ها در دسترس نیست.", parse_mode=ZHTML
            )], cache_time=0)
        return
    if q_inline in INLINE_RICH_CACHE:
        cached = INLINE_RICH_CACHE[q_inline]
        try:
            rich_result = types.InputBotInlineResult(
                id=q_inline, type="article", title=cached.get("title", q_inline), description=cached.get("title", q_inline),
                send_message=types.InputBotInlineMessageRichMessage(
                    rich_message=types.InputRichMessageHTML(html=cached["html"], rtl=True)
                ),
            )
            await event.answer([rich_result], cache_time=0)
        except Exception as e:
            logger.error(f"Generic rich inline failed ({q_inline}): {e}")
            await event.answer([event.builder.article(
                title=cached.get("title", q_inline), text=cached.get("plain") or "", parse_mode=ZHTML
            )], cache_time=0)
        return
    if q_inline in ("help", "status", "music"):
        await event.answer([event.builder.article(
            title="KetaSelf", text="برای این پیام، اول دستور مربوطه را بفرست.", parse_mode=ZHTML
        )], cache_time=5)
        return
    if q_inline in PANEL_RICH_CACHE:
        html_c, buttons_c = PANEL_RICH_CACHE.pop(q_inline)
        try:
            markup_c = event.client.build_reply_markup(buttons_c) if buttons_c else None
            rich_c = types.InputBotInlineResult(
                id=q_inline, type="article", title="پنل", description="پنل",
                send_message=types.InputBotInlineMessageRichMessage(
                    rich_message=types.InputRichMessageHTML(html=html_c, rtl=True),
                    reply_markup=markup_c,
                ),
            )
            await event.answer([rich_c], cache_time=0)
        except Exception as e:
            logger.error(f"Panel rich cache answer failed: {e}")
            await event.answer([event.builder.article(
                title="پنل", text="پنل منقضی شده، دوباره .panel بفرست.", parse_mode=ZHTML
            )], cache_time=0)
        return
    text, buttons = build_main_panel()
    try:
        markup = event.client.build_reply_markup(buttons)
        rich_result = types.InputBotInlineResult(
            id="panel", type="article", title="🪐 KetaSelf Ultra · Panel", description="پنل KetaSelf Ultra",
            send_message=types.InputBotInlineMessageRichMessage(
                rich_message=types.InputRichMessageHTML(html=build_main_panel_rich(), rtl=True),
                reply_markup=markup,
            ),
        )
        await event.answer([rich_result], cache_time=0)
    except Exception as e:
        logger.error(f"Panel rich inline failed, falling back to plain: {e}")
        result = event.builder.article(
            title="🪐 KetaSelf Ultra · Panel",
            description="پنل KetaSelf Ultra",
            text=text, buttons=buttons, parse_mode=ZHTML, link_preview=False
        )
        await event.answer([result], cache_time=0)

@bot_client.on(events.CallbackQuery)
async def callback_query_handler(event: events.CallbackQuery.Event):
    if OWNER_ID and event.sender_id != OWNER_ID:
        await event.answer("⛔ این پنل خصوصی است و متعلق به شما نیست!", alert=True)
        return

    data = event.data.decode("utf-8", errors="ignore")

    try:
        if data == "menu:close":
            await edit_rich_panel(
                event,
                "<h2>✅ پنل بسته شد</h2><p>برای باز کردن دوباره بنویس: <code>" + esc(db.data["prefix"]) + "panel</code></p>",
                buttons=None
            )
            return

        if data == "menu:main":
            text, buttons = build_main_panel()
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("menu:"):
            section = data.split(":", 1)[1]
            text, buttons = build_sub_panel(section)
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("toggle:"):
            _, section, key = data.split(":")
            new_state = db.toggle(section, key)
            await event.answer(f"وضعیت به {'🟢 روشن' if new_state else '🔴 خاموش'} تغییر کرد")
            text, buttons = build_sub_panel(section)
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("dlt:"):
            key = data.split(":", 1)[1]
            bk = db.data["backup"]
            if key == "dl_footer":
                bk["dl_footer"] = not bk.get("dl_footer", True)
            elif key == "clearwatch":
                bk["watch_chats"] = []
            elif key == "dumpme":
                bk["dump_chat"] = "me"
            db.save()
            await event.answer("✅ انجام شد")
            text, buttons = build_sub_panel("downloader")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("sdq:"):
            quality = data.split(":", 1)[1]
            db.data["social_dl"]["quality"] = quality
            db.save()
            await event.answer(f"🎞 کیفیت روی {quality} تنظیم شد")
            text, buttons = build_sub_panel("social_dl")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("sdt:"):
            db.data["social_dl"]["timeout"] = int(data.split(":", 1)[1])
            db.save()
            await event.answer(f"⏱ مهلت انتظار: {db.data['social_dl']['timeout']} ثانیه")
            text, buttons = build_sub_panel("social_dl")
            await edit_rich_panel(event, text, buttons)
            return

        if data == "cycle:font":
            curr = db.data["profile"].get("font_style", "bold_serif")
            idx = (FONT_CYCLE.index(curr) + 1) % len(FONT_CYCLE) if curr in FONT_CYCLE else 0
            new_font = FONT_CYCLE[idx]
            db.data["profile"]["font_style"] = new_font
            db.save()
            await event.answer(f"فونت ساعت به {new_font} تغییر یافت ✨")
            text, buttons = build_sub_panel("profile")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("faction:"):
            act = data.split(":", 1)[1]
            db.data["profile"]["fake_action"] = act
            db.save()
            await event.answer(f"اکشن چت روی {act} تنظیم شد 🎭")
            text, buttons = build_sub_panel("profile")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("setprefix:"):
            new_p = data.split(":", 1)[1]
            db.data["prefix"] = new_p
            db.save()
            await event.answer(f"پیشوند دستورات به « {new_p} » تغییر یافت ✅", alert=True)
            text, buttons = build_sub_panel("prefix")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("seccd:"):
            sec_val = int(data.split(":", 1)[1])
            db.data["secretary"]["cooldown_sec"] = sec_val
            db.save()
            await event.answer(f"فاصله زمانی منشی روی {sec_val // 60} دقیقه تنظیم شد ⏱")
            text, buttons = build_sub_panel("secretary")
            await edit_rich_panel(event, text, buttons)
            return

        if data == "sec:reset":
            SECRETARY_MEMORY.clear()
            await event.answer("حافظه موقت منشی پاکسازی شد! 🧹", alert=True)
            return

        if data.startswith("style:"):
            new_style = data.split(":", 1)[1]
            db.data["text_style"]["mode"] = new_style
            db.save()
            await event.answer(f"استایل متن روی {new_style} تنظیم شد 🎨")
            text, buttons = build_sub_panel("textstyle")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("react:"):
            code = data.split(":", 1)[1]
            emoji = REACT_MAP.get(code, "❤️")
            db.data["premium"]["react_emoji"] = emoji
            db.save()
            await event.answer(f"ایموجی ری‌اکشن به {emoji} تغییر یافت 💎")
            text, buttons = build_sub_panel("premium")
            await edit_rich_panel(event, text, buttons)
            return

        if data.startswith("autoint:"):
            minutes = int(data.split(":", 1)[1])
            db.data["auto_msg"]["interval_min"] = minutes
            db.save()
            await event.answer(f"فاصله ارسال خودکار روی {minutes} دقیقه تنظیم شد ⏱")
            text, buttons = build_sub_panel("automsg")
            await edit_rich_panel(event, text, buttons)
            return

        if data == "auto:clear":
            db.data["auto_msg"]["targets"].clear()
            db.save()
            await event.answer("لیست چت‌های پیام خودکار پاکسازی شد 🗑", alert=True)
            text, buttons = build_sub_panel("automsg")
            await edit_rich_panel(event, text, buttons)
            return

        if data == "fun:clearenemies":
            db.data["fun_social"]["enemies"].clear()
            db.save()
            await event.answer("لیست دشمنان پاکسازی شد ✅", alert=True)
            text, buttons = build_sub_panel("funsocial")
            await edit_rich_panel(event, text, buttons)
            return

        if data == "fun:clearfriends":
            db.data["fun_social"]["friends"].clear()
            db.save()
            await event.answer("لیست دوستان ویژه پاکسازی شد ✅", alert=True)
            text, buttons = build_sub_panel("funsocial")
            await edit_rich_panel(event, text, buttons)
            return

    except MessageNotModifiedError:
        pass
    except Exception as e:
        logger.error(f"Callback error: {e}")


# ==============================================================================
# 5. MEDIA SAVER & RESTRICTED CONTENT DOWNLOADER
# ==============================================================================

def is_timed_or_view_once_media(msg: types.Message) -> bool:
    """Detects self-destructing photos, videos, voice notes, or video notes."""
    if not msg or not msg.media:
        return False
    ttl = getattr(msg.media, "ttl_seconds", None)
    if ttl is not None and ttl > 0:
        return True
    # Also check nested document/photo attributes if any
    return False


async def save_media_to_saved_messages(msg: types.Message, reason: str = "سیو مدیا زماندار / ضد محدودیت"):
    """Downloads any media (including view-once & restricted channel posts) and uploads to Saved Messages."""
    try:
        sender = await msg.get_sender()
        sender_name = getattr(sender, "first_name", "") or getattr(sender, "title", "کاربر")
        sender_id = getattr(sender, "id", msg.sender_id or 0)
        username = f"@{sender.username}" if getattr(sender, "username", None) else "ندارد"

        file_path = await user_client.download_media(msg, file=DOWNLOAD_DIR)
        if not file_path:
            if msg.raw_text:
                await user_client.send_message(
                    "me",
                    f"📝 <b>ذخیره متن ({esc(reason)}):</b>\n"
                    f"<blockquote>{esc(msg.raw_text)}</blockquote>\n"
                    f"👤 فرستنده: <code>{esc(sender_name)}</code> (<code>{sender_id}</code>)",
                    parse_mode=ZHTML
                )
            return

        caption = (
            f"🔥 <b>{esc(reason)}</b>\n"
            "<blockquote>"
            f"👤 <b>فرستنده:</b> <a href='tg://user?id={sender_id}'>{esc(sender_name)}</a> (<code>{sender_id}</code>)\n"
            f"🔗 <b>یوزرنیم:</b> {esc(username)}\n"
            f"📅 <b>زمان ثبت:</b> <code>{get_jalali_date()} - {datetime.now().strftime('%H:%M:%S')}</code>"
            "</blockquote>"
        )
        if msg.raw_text:
            caption += f"\n📝 <b>کپشن:</b> <code>{esc(msg.raw_text)}</code>"

        await user_client.send_file("me", file_path, caption=caption, parse_mode=ZHTML)
        try:
            os.remove(file_path)
        except OSError:
            pass
    except Exception as e:
        logger.error(f"Error saving media: {e}")


async def download_from_telegram_link(link: str) -> bool:
    """Parses t.me/c/12345/67 or t.me/channel/67 and downloads restricted content to Saved Messages."""
    m_priv = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    m_pub = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", link)
    try:
        if m_priv:
            chat_id = int(f"-100{m_priv.group(1)}")
            msg_id = int(m_priv.group(2))
        elif m_pub:
            chat_id = m_pub.group(1)
            msg_id = int(m_pub.group(2))
        else:
            return False

        msg = await user_client.get_messages(chat_id, ids=msg_id)
        if msg:
            await save_media_to_saved_messages(msg, reason="دانلود از لینک کانال دارای محدودیت")
            return True
    except Exception as e:
        logger.error(f"Failed downloading link {link}: {e}")
    return False


# ==============================================================================
# 5B. ZEROSELF v4.0 ENGINE — Protected/Linkless Downloader, Private Channels,
#     Premium Emoji Studio, Social Relay Downloader (No Server Download)
# ==============================================================================

ACCOUNT_PREMIUM: bool = False
TG_HOSTS = ("t.me", "telegram.me", "telegram.dog")


def progress_bar(frac: float, width: int = 12) -> str:
    frac = max(0.0, min(1.0, frac or 0.0))
    full = int(round(frac * width))
    return "▰" * full + "▱" * (width - full)


def human_size(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def make_progress(status_msg, title: str):
    """Throttled live progress bar on a status message (edits every ~3s)."""
    state = {"t": 0.0, "start": time.time()}

    async def _cb(current, total):
        if not status_msg or not total:
            return
        now = time.time()
        if now - state["t"] < 3 and current < total:
            return
        state["t"] = now
        speed = current / max(now - state["start"], 0.1)
        try:
            await status_msg.edit(
                f"{title}\n<blockquote>"
                f"<code>{progress_bar(current / total)}</code> <b>{current * 100 / total:.0f}%</b>\n"
                f"📦 <code>{human_size(current)} / {human_size(total)}</code>\n"
                f"🚀 <code>{human_size(speed)}/s</code>"
                "</blockquote>",
                parse_mode=ZHTML
            )
        except Exception:
            pass
    return _cb


def dump_target():
    d = db.data["backup"].get("dump_chat", "me")
    return d if d else "me"


async def resolve_chat(ref):
    """get_entity with a dialogs-scan fallback (fixes 'Could not find the input entity' for -100 ids)."""
    try:
        return await user_client.get_entity(ref)
    except Exception:
        pass
    try:
        async for d in user_client.iter_dialogs():
            if isinstance(ref, int) and d.id == ref:
                return d.entity
            if isinstance(ref, str) and (getattr(d.entity, "username", "") or "").lower() == ref.lower().lstrip("@"):
                return d.entity
    except Exception as e:
        logger.warning(f"Dialog scan failed: {e}")
    return None


def parse_tg_link(link: str) -> Optional[Dict[str, Any]]:
    """Supports: t.me/c/ID/MSG, t.me/c/ID/TOPIC/MSG, t.me/user/MSG, t.me/s/user/MSG,
    ranges (MSG-MSG2), ?comment=N, ?single, t.me/+hash, t.me/joinchat/hash."""
    link = link.strip().strip("<>")
    m = re.search(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/([^\s?#]+)(\?[^\s#]*)?", link)
    if not m:
        return None
    path = [x for x in m.group(1).split("/") if x]
    query = m.group(2) or ""
    if not path:
        return None
    if path[0].startswith("+"):
        return {"kind": "invite", "hash": path[0][1:]}
    if path[0] == "joinchat" and len(path) > 1:
        return {"kind": "invite", "hash": path[1]}
    if path[0] == "s":
        path = path[1:]
    if not path:
        return None

    if path[0] == "c" and len(path) >= 2 and path[1].isdigit():
        chat = int(f"-100{path[1]}")
        rest = path[2:]
    else:
        chat = path[0]
        rest = path[1:]
    if not rest:
        return {"kind": "chat", "chat": chat}

    last = rest[-1]
    rm = re.fullmatch(r"(\d+)(?:-(\d+))?", last)
    if not rm:
        return {"kind": "chat", "chat": chat}
    start = int(rm.group(1))
    end = int(rm.group(2)) if rm.group(2) else start
    if end < start:
        start, end = end, start
    cm = re.search(r"comment=(\d+)", query)
    return {
        "kind": "msg", "chat": chat, "start": start, "end": end,
        "comment": int(cm.group(1)) if cm else None,
    }


async def join_chat_from_link(link_info: Dict[str, Any]) -> Tuple[Any, str]:
    """Joins via invite hash or public username. Returns (entity, status)."""
    try:
        if link_info["kind"] == "invite":
            h = link_info["hash"]
            chk = await user_client(functions.messages.CheckChatInviteRequest(hash=h))
            if isinstance(chk, types.ChatInviteAlready):
                return chk.chat, "already"
            try:
                upd = await user_client(functions.messages.ImportChatInviteRequest(hash=h))
                return (upd.chats[0] if upd.chats else None), "joined"
            except RPCError as e:
                if "INVITE_REQUEST_SENT" in str(e).upper() or e.__class__.__name__ == "InviteRequestSentError":
                    return None, "request"
                if "USER_ALREADY_PARTICIPANT" in str(e).upper():
                    return None, "already"
                raise
        ent = await resolve_chat(link_info["chat"])
        if ent is None:
            return None, "notfound"
        await user_client(functions.channels.JoinChannelRequest(ent))
        return ent, "joined"
    except FloodWaitError as e:
        return None, f"flood:{e.seconds}"
    except Exception as e:
        return None, f"error:{e}"


async def collect_album(chat, msg) -> List[types.Message]:
    if not msg or not getattr(msg, "grouped_id", None):
        return [msg] if msg else []
    try:
        around = await user_client.get_messages(chat, ids=list(range(max(1, msg.id - 10), msg.id + 11)))
        group = [m for m in around if m and m.grouped_id == msg.grouped_id]
        return sorted(group, key=lambda x: x.id) or [msg]
    except Exception:
        return [msg]


def _is_protected(msg) -> bool:
    chat = getattr(msg, "chat", None)
    ttl = getattr(getattr(msg, "media", None), "ttl_seconds", None)
    return bool(getattr(msg, "noforwards", False) or getattr(chat, "noforwards", False) or ttl)


def _source_footer(msg) -> str:
    chat = getattr(msg, "chat", None)
    title = getattr(chat, "title", None) or getattr(chat, "first_name", None) or "chat"
    return f"\n\n— 🧲 {title} · #{msg.id}"


async def clone_message(msg, dest=None, status=None) -> bool:
    """Copies ANY message (protected, view-once, private) with original formatting & attributes.
    Not-protected media is re-sent by file reference (zero download)."""
    if not msg:
        return False
    dest = dest or dump_target()
    text = msg.message or ""
    ents = list(msg.entities or [])
    footer = _source_footer(msg) if db.data["backup"].get("dl_footer", True) else ""

    media = msg.media
    if not media or isinstance(media, (types.MessageMediaWebPage, types.MessageMediaEmpty)):
        if not text:
            return False
        await user_client.send_message(dest, text + footer, formatting_entities=ents, link_preview=False)
        return True

    if isinstance(media, (types.MessageMediaPoll, types.MessageMediaGeo, types.MessageMediaContact,
                          types.MessageMediaVenue, types.MessageMediaDice)):
        await user_client.send_message(dest, f"⚠️ این نوع پیام (نظرسنجی/لوکیشن/مخاطب) قابل کپی کامل نیست.{footer}")
        return True

    cap = text + footer if len(text) + len(footer) <= 1000 else text[:1024]

    # Fast path: not protected → send by reference, no bandwidth used on your server
    if not _is_protected(msg):
        try:
            await user_client.send_file(dest, media, caption=cap, formatting_entities=ents)
            return True
        except Exception as e:
            logger.info(f"Reference copy failed, falling back to download: {e}")

    path = thumb = None
    try:
        path = await user_client.download_media(
            msg, file=DOWNLOAD_DIR,
            progress_callback=make_progress(status, "⬇️ <b>دانلود از تلگرام...</b>")
        )
        if not path:
            return False
        doc = getattr(msg, "document", None)
        attrs = None
        if doc:
            attrs = [a for a in doc.attributes if not isinstance(a, types.DocumentAttributeSticker)] or None
            if getattr(doc, "thumbs", None):
                try:
                    thumb = await user_client.download_media(msg, file=DOWNLOAD_DIR, thumb=-1)
                except Exception:
                    thumb = None
        is_video_note = any(isinstance(a, types.DocumentAttributeVideo) and getattr(a, "round_message", False)
                            for a in (attrs or []))
        is_voice = any(isinstance(a, types.DocumentAttributeAudio) and getattr(a, "voice", False)
                       for a in (attrs or []))
        await user_client.send_file(
            dest, path,
            caption=cap, formatting_entities=ents,
            attributes=attrs, thumb=thumb,
            supports_streaming=True,
            video_note=is_video_note, voice_note=is_voice,
            progress_callback=make_progress(status, "⬆️ <b>آپلود نسخه آزاد...</b>")
        )
        return True
    finally:
        for p_ in (path, thumb):
            if p_ and isinstance(p_, str):
                try:
                    os.remove(p_)
                except OSError:
                    pass


async def clone_album(msgs: List[types.Message], dest=None, status=None) -> bool:
    msgs = [m for m in msgs if m]
    if not msgs:
        return False
    if len(msgs) == 1:
        return await clone_message(msgs[0], dest, status)
    dest = dest or dump_target()
    captions = [m.message or "" for m in msgs]
    if db.data["backup"].get("dl_footer", True):
        captions[0] = (captions[0] + _source_footer(msgs[0]))[:1024]
    try:
        if not any(_is_protected(m) for m in msgs):
            await user_client.send_file(dest, [m.media for m in msgs], caption=captions)
            return True
        paths = []
        for i, m in enumerate(msgs, 1):
            p_ = await user_client.download_media(
                m, file=DOWNLOAD_DIR,
                progress_callback=make_progress(status, f"⬇️ <b>آلبوم: فایل {i}/{len(msgs)}</b>")
            )
            if p_:
                paths.append(p_)
        try:
            await user_client.send_file(dest, paths, caption=captions[:len(paths)])
        finally:
            for p_ in paths:
                try:
                    os.remove(p_)
                except OSError:
                    pass
        return True
    except Exception as e:
        logger.warning(f"Album send failed, sending one by one: {e}")
        ok = False
        for m in msgs:
            ok = await clone_message(m, dest, status) or ok
        return ok


async def fetch_from_link(link: str, status=None) -> Tuple[int, str]:
    """Returns (saved_count, error_text)."""
    info = parse_tg_link(link)
    if not info:
        return 0, "لینک تلگرام معتبر نیست."
    if info["kind"] == "invite":
        ent, st = await join_chat_from_link(info)
        if st == "request":
            return 0, "درخواست عضویت فرستاده شد؛ بعد از تأیید ادمین دوباره لینک پست رو بفرست."
        if ent is None and st not in ("already",):
            return 0, f"عضویت ناموفق بود: <code>{esc(st)}</code>"
        return 0, "✅ عضو شدی. حالا لینک پست (t.me/c/...) رو بفرست."
    if info["kind"] == "chat":
        return 0, "این لینک خود کانال است؛ لینک پست یا بازه (مثلاً <code>/10-40</code>) بده."

    chat = await resolve_chat(info["chat"])
    if chat is None:
        return 0, ("به این چت دسترسی ندارم. کانال خصوصیه؟ اول با "
                   f"<code>{esc(db.data['prefix'])}join لینک‌دعوت</code> عضو شو.")

    if info.get("comment"):
        try:
            disc = await user_client(functions.messages.GetDiscussionMessageRequest(peer=chat, msg_id=info["start"]))
            dchat = disc.chats[0] if disc.chats else None
            m = await user_client.get_messages(dchat, ids=info["comment"])
            return (1 if await clone_album(await collect_album(dchat, m), status=status) else 0), ""
        except Exception as e:
            return 0, f"کامنت پیدا نشد: <code>{esc(e)}</code>"

    return await fetch_range(chat, info["start"], info["end"], status)


async def fetch_range(chat, start: int, end: int, status=None) -> Tuple[int, str]:
    end = min(end, start + 199)  # safety cap: 200 posts per command
    saved, seen_groups = 0, set()
    ids = list(range(start, end + 1))
    for chunk_i in range(0, len(ids), 50):
        msgs = await user_client.get_messages(chat, ids=ids[chunk_i:chunk_i + 50])
        for m in msgs:
            if not m:
                continue
            if m.grouped_id:
                if m.grouped_id in seen_groups:
                    continue
                seen_groups.add(m.grouped_id)
            try:
                group = await collect_album(chat, m)
                if await clone_album(group, status=status):
                    saved += 1
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
            except Exception as e:
                logger.warning(f"Range item {m.id} failed: {e}")
            if end > start:
                await asyncio.sleep(1.2)
    if saved == 0:
        return 0, "پستی پیدا نشد یا حذف شده (یا شماره پیام اشتباهه)."
    return saved, ""


# ---------------- Premium Emoji Studio ----------------

def u16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def u16slice(text: str, offset: int, length: int) -> str:
    b = text.encode("utf-16-le")
    return b[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def extract_custom_emojis(msg) -> List[Tuple[str, int]]:
    out = []
    text = getattr(msg, "message", "") or ""
    for e in (getattr(msg, "entities", None) or []):
        if isinstance(e, types.MessageEntityCustomEmoji):
            out.append((u16slice(text, e.offset, e.length), e.document_id))
    return out


def _emoji_variants(ch: str) -> List[str]:
    base = ch.replace("\ufe0f", "")
    return list({ch, base, base + "\ufe0f"})


def premium_entities(text: str, existing=None, emap=None) -> List[Any]:
    emap = emap if emap is not None else db.data["premium"].get("emoji_map", {})
    if not emap or not text:
        return []
    blocked = []
    for e in existing or []:
        if isinstance(e, (types.MessageEntityCode, types.MessageEntityPre, types.MessageEntityCustomEmoji)):
            blocked.append((e.offset, e.offset + e.length))
    keys = sorted(emap.keys(), key=len, reverse=True)
    out, i, off = [], 0, 0
    while i < len(text):
        hit = None
        for k in keys:
            if k and text.startswith(k, i):
                hit = k
                break
        if hit:
            ln = u16len(hit)
            if not any(a <= off < b for a, b in blocked):
                out.append(types.MessageEntityCustomEmoji(offset=off, length=ln, document_id=int(emap[hit])))
            i += len(hit)
            off += ln
        else:
            off += u16len(text[i])
            i += 1
    return out


def pe(ch: str) -> str:
    """Panel decorator: wraps an emoji in <tg-emoji> if a premium id is mapped for the panel UI.
    Bots only render these if the bot has a Fragment username; otherwise Telegram shows the normal emoji."""
    prem = db.data["premium"]
    if not prem.get("bot_custom_emoji"):
        return ch
    did = prem.get("ui_emoji", {}).get(ch) or prem.get("emoji_map", {}).get(ch)
    return f'<tg-emoji emoji-id="{did}">{ch}</tg-emoji>' if did else ch


# ---------------- Social Relay Downloader (IG / YT / TikTok) ----------------

def detect_platform(url: str) -> str:
    u = url.lower()
    if "instagram.com" in u or "instagr.am" in u:
        return "ig"
    if "tiktok.com" in u:
        return "tt"
    if "youtube.com" in u or "youtu.be" in u:
        return "yt"
    return "other"


SOCIAL_URL_RE = re.compile(r"https?://(?:www\.|m\.|vm\.|vt\.)?(?:instagram\.com|instagr\.am|tiktok\.com|youtube\.com|youtu\.be)/\S+", re.I)
QUALITY_RE = re.compile(r"(720|480|360|1080|mp4|video|ویدیو|ویدئو|دانلود|download|best)", re.I)
FORCE_JOIN_RE = re.compile(r"(join|subscribe|عضو|جوین|کانال ما)", re.I)
NOT_SUPPORTED_RE = re.compile(r"(поддерживается|не поддерживается|not supported|doesn't support|does not support|پشتیبانی نمی)", re.I)


async def relay_social(link: str, status=None) -> Tuple[List[types.Message], str, str]:
    """Sends the link to third-party downloader bots from YOUR account and grabs their result.
    The video is downloaded on THEIR servers; we only re-send by file reference."""
    cfg = db.data["social_dl"]
    platform = detect_platform(link)
    bots = list(cfg["bots"].get(platform) or []) + [b for b in cfg["bots"].get("other", []) if b not in cfg["bots"].get(platform, [])]
    timeout = int(cfg.get("timeout", 90))
    errors_log = []
    for bot_name in bots:
        try:
            if status:
                await status.edit(f"🌐 <b>ارسال به</b> <code>{esc(bot_name)}</code> <i>...</i>", parse_mode=ZHTML)
            ent = await user_client.get_entity(bot_name)
            history = await user_client.get_messages(ent, limit=1)
            if not history:
                await user_client.send_message(ent, "/start")
                await asyncio.sleep(2)
            sent = await user_client.send_message(ent, link)
            trace = [sent.id]
            media_msgs, last_text, clicked, not_supported = [], "", False, False
            deadline = time.time() + timeout
            while time.time() < deadline:
                await asyncio.sleep(2)
                new = await user_client.get_messages(ent, min_id=sent.id, limit=30)
                new = sorted([m for m in new if not m.out], key=lambda m: m.id)
                for m in new:
                    if m.id not in trace:
                        trace.append(m.id)
                media_now = [m for m in new if m.media and not isinstance(m.media, types.MessageMediaWebPage)]
                if media_now:
                    await asyncio.sleep(4)  # let album parts arrive
                    new = await user_client.get_messages(ent, min_id=sent.id, limit=30)
                    media_msgs = sorted([m for m in new if not m.out and m.media
                                         and not isinstance(m.media, types.MessageMediaWebPage)], key=lambda m: m.id)
                    trace += [m.id for m in new if m.id not in trace]
                    break
                for m in new:
                    if m.message:
                        last_text = m.message
                    if not clicked and m.buttons:
                        flat = [b for row in m.buttons for b in row]
                        if any(getattr(b, "url", None) for b in flat) and FORCE_JOIN_RE.search(m.message or ""):
                            errors_log.append(f"{bot_name}: جوین اجباری")
                            deadline = 0
                            break
                        wanted = str(cfg.get("quality", "720")).lower()
                        if wanted == "max":
                            pick = next((b for b in flat if not getattr(b, "url", None) and re.search(r"(max|best|original|1080|hd)", b.text or "", re.I)), None)
                        else:
                            pick = next((b for b in flat if not getattr(b, "url", None) and re.search(rf"(?<!\d){re.escape(wanted)}\s*p?(?!\d)", b.text or "", re.I)), None)
                        pick = pick or next((b for b in flat if not getattr(b, "url", None) and QUALITY_RE.search(b.text or "")), None)
                        pick = pick or next((b for b in flat if not getattr(b, "url", None)), None)
                        if pick:
                            try:
                                await pick.click()
                                clicked = True
                            except Exception:
                                pass
                if NOT_SUPPORTED_RE.search(last_text or ""):
                    not_supported = True
                    break
            if NOT_SUPPORTED_RE.search(last_text or ""):
                not_supported = True
                errors_log.append(f"{bot_name}: یوتیوب پشتیبانی نمی‌شود")
            if media_msgs:
                if cfg.get("clean_trace", False):
                    asyncio.create_task(_clean_later(ent, trace))
                return media_msgs, bot_name, ""
            if last_text and re.search(r"https?://", last_text):
                return [], bot_name, last_text
            if not not_supported:
                errors_log.append(f"{bot_name}: بدون خروجی")
        except FloodWaitError as e:
            errors_log.append(f"{bot_name}: FloodWait {e.seconds}s")
        except Exception as e:
            errors_log.append(f"{bot_name}: {e}")
    return [], "", " | ".join(errors_log) or "هیچ رباتی تنظیم نشده."


async def _clean_later(ent, ids):
    await asyncio.sleep(20)
    try:
        await user_client.delete_messages(ent, ids, revoke=True)
    except Exception:
        pass


async def deliver_social(event, link: str, replace_msg=None):
    status = replace_msg or await event.reply("🌐 <i>در حال آماده‌سازی...</i>", parse_mode=ZHTML)
    direct_err = ""
    if detect_platform(link) == "yt":
        await status.edit("🎬 <i>در حال دانلود مستقیم ویدیوی یوتیوب...</i>", parse_mode=ZHTML)
        vpath, vtitle = await download_youtube_video(link)
        if vpath:
            try:
                await user_client.send_file(event.chat_id, vpath, reply_to=event.reply_to_msg_id)
            except Exception:
                await user_client.send_file(event.chat_id, vpath)
            await status.delete()
            import shutil as _shutil

            _shutil.rmtree(vpath.parent, ignore_errors=True)
            return
        direct_err = vtitle
    msgs, via, extra = await relay_social(link, status)
    if msgs:
        try:
            await user_client.send_file(event.chat_id, [m.media for m in msgs] if len(msgs) > 1 else msgs[0].media,
                                        reply_to=event.reply_to_msg_id)
        except Exception:
            await user_client.forward_messages(event.chat_id, msgs)
        await status.delete()
        return
    if via and extra:
        await status.edit(f"🔗 <b>لینک مستقیم از {esc(via)}:</b>\n<blockquote>{esc(extra[:900])}</blockquote>", parse_mode=ZHTML)
        return
    err_text = "❌ <b>دانلود نشد.</b>\n<blockquote expandable>" + esc(extra) + "</blockquote>\n"
    if direct_err:
        err_text += "💡 دانلود مستقیم هم ناموفق بود: <code>" + esc(direct_err[:300]) + "</code>\n"
    err_text += f"💡 با <code>{esc(db.data['prefix'])}setdl ig @bot1 @bot2</code> ربات‌های دیگه رو تنظیم کن."
    await status.edit(err_text, parse_mode=ZHTML)


# ---------------- v3 Command Router ----------------

MUSIC_SEARCHES = {}


async def search_music_list(query: str, n: int = 5):
    """Search YouTube without downloading. Returns list of dicts or (None, error)."""
    ytdlp = Path(sys.executable).parent / "yt-dlp"
    cmdline = [
        str(ytdlp) if ytdlp.exists() else "yt-dlp",
        "--ignore-config", *_HTTP_PROXY_ARGS,
        "--flat-playlist", "--no-warnings",
        "--print", "%(id)s	%(title)s	%(duration_string)s	%(duration)s",
        f"ytsearch{n + 4}:{query}",
    ]
    _node_env = os.getenv("NODE_PATH", "").strip()
    node = Path(_node_env) if _node_env else None
    if node is None:
        import shutil
        _which_node = shutil.which("node")
        node = Path(_which_node) if _which_node else None
    if node is not None and node.exists():
        cmdline += ["--js-runtimes", f"node:{node}"]
    proc = await asyncio.create_subprocess_exec(
        *cmdline, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "مهلت جستجو تمام شد."
    if proc.returncode != 0:
        return None, (err or out).decode(errors="replace")[-400:] or "خطای جستجو"
    results = []
    all_results = []
    for line in out.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip():
            try:
                secs = int(float(parts[3])) if len(parts) >= 4 and parts[3].strip() else 0
            except Exception:
                secs = 0
            all_results.append({"id": parts[0].strip(), "title": parts[1].strip(), "duration": parts[2].strip(), "secs": secs})
    full = [r for r in all_results if r["secs"] >= 90]
    results = (full if full else all_results)[:n]
    if not results:
        return None, "نتیجه‌ای پیدا نشد."
    return results, None


async def download_music_file(query_or_url: str):
    """Download full audio as mp3 via the bot venv yt-dlp, through SOCKS proxy.
    Returns (Path, title) on success, or (None, error_text) on failure."""
    import uuid
    tmpdir = Path("downloads") / "music" / uuid.uuid4().hex[:12]
    tmpdir.mkdir(parents=True, exist_ok=True)
    ytdlp = Path(sys.executable).parent / "yt-dlp"
    cmdline = [
        str(ytdlp) if ytdlp.exists() else "yt-dlp",
        "--ignore-config", *_HTTP_PROXY_ARGS,
        "--no-playlist", "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "192K",
        "--no-warnings", "-o", str(tmpdir / "%(title)s.%(ext)s"),
    ]
    _node_env = os.getenv("NODE_PATH", "").strip()
    node = Path(_node_env) if _node_env else None
    if node is None:
        import shutil
        _which_node = shutil.which("node")
        node = Path(_which_node) if _which_node else None
    if node is not None and node.exists():
        cmdline += ["--js-runtimes", f"node:{node}"]
    if query_or_url.startswith("http"):
        cmdline.append(query_or_url)
    else:
        cmdline.append(f"ytsearch1:{query_or_url}")
    proc = await asyncio.create_subprocess_exec(
        *cmdline, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "مهلت دانلود (۱۰ دقیقه) تمام شد."
    if proc.returncode != 0:
        tail = (err or out).decode(errors="replace")[-600:]
        return None, tail or "خطای ناشناخته‌ی yt-dlp"
    mp3s = sorted(tmpdir.glob("*.mp3"), key=lambda x: x.stat().st_size, reverse=True)
    if not mp3s:
        return None, "فایل mp3 ساخته نشد."
    return mp3s[0], mp3s[0].stem

async def download_youtube_video(link: str):
    """Download a YouTube video directly via yt-dlp (proxy), up to 720p, merged mp4.
    Returns (Path, title) or (None, error). No download-sections, so ffmpeg never
    fetches googlevideo directly (that bypasses the proxy and times out from Iran)."""
    import uuid
    import shutil

    tmpdir = Path("downloads") / "video" / uuid.uuid4().hex[:12]
    tmpdir.mkdir(parents=True, exist_ok=True)
    ytdlp = Path(sys.executable).parent / "yt-dlp"
    cmdline = [
        str(ytdlp) if ytdlp.exists() else "yt-dlp",
        "--ignore-config", *_HTTP_PROXY_ARGS,
        "--no-playlist", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4", "--no-warnings",
        "-o", str(tmpdir / "%(title)s.%(ext)s"),
    ]
    _node_env = os.getenv("NODE_PATH", "").strip()
    node = Path(_node_env) if _node_env else None
    if node is None:
        import shutil
        _which_node = shutil.which("node")
        node = Path(_which_node) if _which_node else None
    if node is not None and node.exists():
        cmdline += ["--js-runtimes", f"node:{node}"]
    cmdline.append(link)
    proc = await asyncio.create_subprocess_exec(
        *cmdline, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, "مهلت دانلود (۱۰ دقیقه) تمام شد."
    if proc.returncode != 0:
        tail = (err or out).decode(errors="replace")[-600:]
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, tail or "خطای ناشناخته‌ی yt-dlp"
    vids = sorted(
        [f for f in tmpdir.glob("*") if f.is_file() and f.suffix.lower() in (".mp4", ".webm", ".mkv")],
        key=lambda x: x.stat().st_size, reverse=True,
    )
    if not vids:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, "فایل ویدیو ساخته نشد."
    return vids[0], vids[0].stem


async def audio_duration_seconds(path) -> int:
    """Duration of an mp3 via ffprobe, 0 on failure. Used so Telegram shows the real length."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return int(float(out.decode().strip()))
    except Exception:
        return 0


IDENTIFY_BOTS = ["@WhatIsThisMusicBot", "@ShazamBot"]


def parse_identified_song(text):
    """Best-effort parse of an identification bot reply into (artist, title)."""
    if not text:
        return None
    title_m = re.search(r"(?:Title|Song|Track|Name)\s*[:\uff1a]\s*([^\n\r]+)", text, re.I)
    artist_m = re.search(r"(?:Artist|Singer|Performer)\s*[:\uff1a]\s*([^\n\r]+)", text, re.I)
    if title_m and artist_m:
        title = re.sub(r"https?://\S+", "", title_m.group(1)).strip()
        artist = re.sub(r"https?://\S+", "", artist_m.group(1)).strip()
        if len(artist) >= 2 and len(title) >= 2:
            return artist, title
    for line in text.splitlines():
        s = line.strip()
        if not s or "http" in s or "join" in s.lower() or "subscribe" in s.lower():
            continue
        s = re.sub(r"^[^\w]+", "", s).strip()
        m = re.match(r"^(.{2,60}?)\s*[-\u2013\u2014]\s*(.{2,60})$", s)
        if m:
            artist, title = m.group(1).strip(), m.group(2).strip()
            title = re.sub(r"\s*\(.*\)\s*$", "", title).strip()
            if artist and title:
                return artist, title
    return None


async def extract_audio_clip(src, out):
    """First 20 seconds of audio from a video/audio file (30-50s if over 60s)."""
    try:
        dur = await audio_duration_seconds(src)
        start = 30 if dur > 60 else 0
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", "20",
            "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "128k", str(out),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        return proc.returncode == 0 and out.exists() and out.stat().st_size > 1000
    except Exception as e:
        logger.info("identify clip failed: %s", e)
        return False


async def identify_song_via_bot(clip):
    """Send an audio clip to free identification bots, return (artist, title)."""
    errors = []
    for bot_name in IDENTIFY_BOTS:
        try:
            ent = await user_client.get_entity(bot_name)
            if not getattr(ent, "bot", False):
                errors.append(f"{bot_name}: بات نیست")
                continue
            history = await user_client.get_messages(ent, limit=1)
            if not history:
                await user_client.send_message(ent, "/start")
                await asyncio.sleep(2)
            sent = await user_client.send_file(
                ent, str(clip),
                attributes=[types.DocumentAttributeAudio(duration=20, title="clip")],
            )
            trace = [sent.id]
            candidate = ""
            deadline = time.time() + 90
            while time.time() < deadline:
                await asyncio.sleep(2)
                new = await user_client.get_messages(ent, min_id=sent.id, limit=30)
                new = sorted([m for m in new if not m.out], key=lambda m: m.id)
                for m in new:
                    if m.id not in trace:
                        trace.append(m.id)
                texts = [m.message for m in new if m.message]
                if texts:
                    last = texts[-1]
                    low = last.lower()
                    if any(w in low for w in ("identifying", "please wait", "processing", "searching")) and len(last) < 80:
                        continue
                    candidate = last
                    break
            if db.data.get("social_dl", {}).get("clean_trace", False):
                asyncio.create_task(_clean_later(ent, trace))
            if not candidate:
                errors.append(f"{bot_name}: بدون جواب")
                continue
            logger.info("identify reply from %s: %s", bot_name, candidate[:500])
            if FORCE_JOIN_RE.search(candidate) and " - " not in candidate:
                errors.append(f"{bot_name}: جوین اجباری")
                continue
            parsed = parse_identified_song(candidate)
            if parsed:
                return parsed[0], parsed[1]
            errors.append(f"{bot_name}: فرمت جواب خوانده نشد")
        except FloodWaitError as e:
            errors.append(f"{bot_name}: FloodWait {e.seconds}s")
        except Exception as e:
            errors.append(f"{bot_name}: {e}")
    logger.info("identify failed: %s", " | ".join(errors))
    return None, None


async def deliver_music(event, query_or_url):
    """Download a full mp3 and send it to the command chat, then clean up."""
    await event.edit("در حال دانلود کامل موزیک...", parse_mode=ZHTML)
    mp3_path, title_or_err = await download_music_file(query_or_url)
    if not mp3_path:
        await event.edit(f"دانلود موزیک ناموفق بود: {esc(title_or_err)}", parse_mode=ZHTML)
        return
    try:
        dur = await audio_duration_seconds(mp3_path)
        await user_client.send_file(
            event.chat_id, str(mp3_path),
            attributes=[types.DocumentAttributeAudio(duration=dur, title=title_or_err)],
        )
        try:
            await event.delete()
        except Exception:
            pass
    except Exception as e:
        await event.edit(f"خطا در ارسال فایل: {esc(e)}", parse_mode=ZHTML)
    finally:
        try:
            mp3_path.unlink(missing_ok=True)
            mp3_path.parent.rmdir()
        except Exception:
            pass


def clean_song_query(text: str):
    """Clean a video title/caption into a music search query."""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"\bib:@?\S+", " ", s, flags=re.I)
    s = re.sub(r"#\S+", " ", s)
    s = re.sub(r"@\S+", " ", s)
    s = re.sub(r"\bib:\s*", " ", s, flags=re.I)
    if ":" in s:
        after = s.split(":", 1)[1].strip()
        if len(after) >= 4:
            s = after
    s = re.sub(r"\((Official Video|Official Music Video|Official Audio|Official Lyric Video)\)", " ", s, flags=re.I)
    s = re.sub(r"\[(Official Video|Official Music Video|Official Audio)\]", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -|")
    return s[:80] if len(s) >= 3 else None


async def get_link_song_query(url: str):
    """Get a song search query from a link's metadata (title/track/artist)."""
    ytdlp = Path(sys.executable).parent / "yt-dlp"
    cmdline = [
        str(ytdlp) if ytdlp.exists() else "yt-dlp",
        "--ignore-config", *_HTTP_PROXY_ARGS,
        "--no-playlist", "--no-warnings",
        "--print", "%(track)s", "--print", "%(artist)s", "--print", "%(title)s",
        url,
    ]
    _node_env = os.getenv("NODE_PATH", "").strip()
    node = Path(_node_env) if _node_env else None
    if node is None:
        import shutil
        _which_node = shutil.which("node")
        node = Path(_which_node) if _which_node else None
    if node is not None and node.exists():
        cmdline += ["--js-runtimes", f"node:{node}"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmdline, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in out.decode(errors="replace").splitlines() if ln.strip()]
    if len(lines) < 3:
        return None
    track, artist, title = lines[0], lines[1], lines[2]
    if track and track != "NA" and "original sound" not in track.lower():
        q = f"{artist} {track}" if artist and artist != "NA" else track
        return clean_song_query(q)
    return clean_song_query(title)


async def send_full_song_for_link(event, url: str):
    """After a clip download, find and send the full song for the same link.
    Returns True if a full (>=90s) song was sent, else False."""
    status_msg = await user_client.send_message(event.chat_id, "در حال پیدا کردن آهنگ کامل...")
    diag = ""
    try:
        query = await get_link_song_query(url)
        if not query:
            diag = "عنوانی از لینک خوانده نشد."
        else:
            diag = f"عنوان استخراج‌شده: {query}"
        if query:
            results, _err = await search_music_list(query)
            if not results:
                diag += f" | جستجو نتیجه‌ای نداد: {_err or ''}"
            if results:
                first = results[0]
                await status_msg.edit(f"آهنگ کامل پیدا شد: {esc(first['title'])} ({esc(first['duration'])}) - در حال دانلود...")
                mp3_path, title_or_err = await download_music_file("https://www.youtube.com/watch?v=" + first["id"])
                if not mp3_path:
                    diag += f" | دانلود نتیجه اول ناموفق: {title_or_err}"
                if mp3_path:
                    dur = await audio_duration_seconds(mp3_path)
                    await user_client.send_file(
                        event.chat_id, str(mp3_path),
                        attributes=[types.DocumentAttributeAudio(duration=dur, title=title_or_err)],
                    )
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                    try:
                        mp3_path.unlink(missing_ok=True)
                        mp3_path.parent.rmdir()
                    except Exception:
                        pass
                    return True
        mp3_path, _title = await download_music_file(url)
        if mp3_path:
            dur = await audio_duration_seconds(mp3_path)
            if dur >= 90:
                await user_client.send_file(
                    event.chat_id, str(mp3_path),
                    attributes=[types.DocumentAttributeAudio(duration=dur, title=_title)],
                )
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                try:
                    mp3_path.unlink(missing_ok=True)
                    mp3_path.parent.rmdir()
                except Exception:
                    pass
                return True
            try:
                mp3_path.unlink(missing_ok=True)
                mp3_path.parent.rmdir()
            except Exception:
                pass
        logger.info(f"Full song not found for link, diag: {diag[:300]}")
        try:
            await status_msg.delete()
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error(f"Full song lookup failed: {e}")
        try:
            await status_msg.delete()
        except Exception:
            pass
        return False


PRICE_COINS = {
    "btc": ("bitcoin", "بیت‌کوین"),
    "bitcoin": ("bitcoin", "بیت‌کوین"),
    "eth": ("ethereum", "اتریوم"),
    "ethereum": ("ethereum", "اتریوم"),
    "usdt": ("tether", "تتر"),
    "tether": ("tether", "تتر"),
    "sol": ("solana", "سولانا"),
    "solana": ("solana", "سولانا"),
    "bnb": ("binancecoin", "بایننس‌کوین"),
    "binancecoin": ("binancecoin", "بایننس‌کوین"),
    "doge": ("dogecoin", "دوج‌کوین"),
    "dogecoin": ("dogecoin", "دوج‌کوین"),
    "xrp": ("ripple", "ریپل"),
    "ripple": ("ripple", "ریپل"),
    "trx": ("tron", "ترون"),
    "tron": ("tron", "ترون"),
    "ada": ("cardano", "کاردانو"),
    "cardano": ("cardano", "کاردانو"),
}


def fa_num(v, decimals=None):
    """Format a number fully in Persian: Persian digits, Persian separators.
    Keeps the whole line RTL so Telegram does not flip English/Latin segments."""
    try:
        f = float(v)
    except Exception:
        return str(v)
    if decimals is None:
        decimals = 0 if f >= 1000 else (2 if f >= 10 else 4)
    s = f"{f:,.{decimals}f}"
    table = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")
    return s.translate(table)


def fa_pct(chg):
    """Persian percent with trend arrow, e.g. ▼ ۲٫۴٪ افت / ▲ ۱٫۲٪ رشد."""
    try:
        f = float(chg)
    except Exception:
        return ""
    if f == 0:
        return "بدون تغییر"
    arrow = "▲" if f > 0 else "▼"
    word = "رشد" if f > 0 else "افت"
    return f"{arrow} {fa_num(abs(f), 1)}٪ {word}"


async def fetch_json_curl(url: str, proxy: bool = False):
    """Fetch JSON with curl (proxy for foreign APIs, direct for Iranian APIs)."""
    cmdline = ["curl", "-s", "--max-time", "25", "-A", "Mozilla/5.0"]
    if proxy:
        cmdline += _HTTP_PROXY_ARGS
    cmdline.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmdline, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except Exception:
        return None
    if proc.returncode != 0 or not out:
        return None
    try:
        return json.loads(out.decode(errors="replace"))
    except Exception:
        return None


def fmt_usd(v):
    try:
        f = float(v)
    except Exception:
        return str(v)
    if f >= 1000:
        return f"{f:,.0f}"
    if f >= 10:
        return f"{f:,.2f}"
    return f"{f:,.4f}"


def fmt_toman(v):
    try:
        f = float(v)
    except Exception:
        return str(v)
    return f"{f:,.0f}"


def tgju_toman(ir, key):
    try:
        raw = ir["current"][key]["p"].replace(",", "")
        return float(raw) / 10.0
    except Exception:
        return None


async def get_price_data():
    """Returns (crypto_dict, ir_current_dict, dollar_toman, tgju_date).
    dollar_toman is the LIVE Wallex USDT ask for crypto conversion (24/7);
    the Iran-market section still reads TGJU directly. Falls back to TGJU
    dollar if Wallex is unavailable."""
    ids = ",".join(sorted({v[0] for v in PRICE_COINS.values()}))
    crypto, tgju, wallex = await asyncio.gather(
        fetch_json_curl(
            "https://api.coingecko.com/api/v3/simple/price?ids=" + ids + "&vs_currencies=usd&include_24hr_change=true",
            proxy=True,
        ),
        fetch_json_curl("https://call1.tgju.org/ajax.json", proxy=False),
        fetch_json_curl("https://api.wallex.ir/v1/depth?symbol=USDTTMN", proxy=False),
    )
    crypto = crypto or {}
    ir = (tgju or {}).get("current", {}) if isinstance(tgju, dict) else {}
    tgju_date = ""
    try:
        tgju_date = ir["price_dollar_rl"].get("t", "")
    except Exception:
        tgju_date = ""
    dollar = None
    try:
        dollar = float(wallex["result"]["ask"][0]["price"])
    except Exception:
        dollar = None
    if not dollar:
        dollar = tgju_toman({"current": ir}, "price_dollar_rl") if ir else None
    return crypto, ir, dollar, tgju_date


PRICE_INLINE_CACHE = {"html": None, "plain": None, "ts": 0}
PRICE_INLINE_TTL = 300


async def deliver_price(event, lines, rich_html):
    """Send a price card via the helper bot inline as a Rich Message.
    Falls back to a plain message in the same chat if inline/Rich fails."""
    global PRICE_INLINE_CACHE
    PRICE_INLINE_CACHE = {"html": rich_html, "plain": chr(10).join(lines), "ts": time.time()}
    plain = chr(10).join((chr(8207) + ln if ln else ln) for ln in lines)
    try:
        await event.delete()
        results = await user_client.inline_query(BOT_USERNAME, "price")
        if results:
            await results[0].click(event.chat_id, reply_to=event.reply_to_msg_id)
            return
    except Exception as e:
        logger.error(f"Price inline delivery failed: {e}")
    await user_client.send_message(event.chat_id, plain, parse_mode=ZHTML)


def lines_to_rich_table(lines):
    """Convert pipe-table lines into a real Rich Message <table>.
    Section headers (<b>...</b>) become <h3>, header rows become <th>,
    data rows become <td>. Separator lines are dropped."""
    parts = []
    in_table = False
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("<b>") and ln.endswith("</b>"):
            if in_table:
                parts.append("</table>")
                in_table = False
            parts.append("<h3>" + ln[3:-4] + "</h3>")
            continue
        if set(ln) == {"-"}:
            continue
        if " | " in ln:
            cells = [c.strip() for c in ln.split(" | ")]
            if not in_table:
                parts.append("<table>")
                in_table = True
            tag = "th" if cells[0] in ("ارز", "کالا") else "td"
            parts.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        parts.append(ln)
    if in_table:
        parts.append("</table>")
    return chr(10).join(parts)


INLINE_RICH_CACHE = {}
PANEL_RICH_CACHE = {}


async def deliver_inline_rich(event, key, title, rich_html, plain_lines):
    """Send a message via the helper bot inline as a Rich Message.
    plain_lines is a list of lines for the plain fallback message.
    Falls back to a plain message in the same chat if inline/Rich fails."""
    global INLINE_RICH_CACHE
    plain = chr(10).join(plain_lines)
    INLINE_RICH_CACHE[key] = {"html": rich_html, "plain": plain, "title": title}
    try:
        await event.delete()
        results = await user_client.inline_query(BOT_USERNAME, key)
        if results:
            await results[0].click(event.chat_id, reply_to=event.reply_to_msg_id)
            return
    except Exception as e:
        logger.error(f"Inline rich delivery failed ({key}): {e}")
    await user_client.send_message(event.chat_id, plain, parse_mode=ZHTML)


def rich_table(header, rows):
    """Build a real Rich Message <table> from header cells and row cell lists."""
    out = ["<table>"]
    out.append("<tr>" + "".join(f"<th>{c}</th>" for c in header) + "</tr>")
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    out.append("</table>")
    return chr(10).join(out)


PRICE_ICONS = {"btc": "🪙", "eth": "💎", "sol": "☀️", "bnb": "🟡", "xrp": "🔷", "doge": "🐶", "trx": "🔺", "ada": "🅰️", "usdt": "💵"}
IR_ICONS = {
    "price_dollar_rl": "💵", "price_eur": "💶", "price_gbp": "💷",
    "geram18": "🥇", "geram24": "🥇",
    "sekee": "🪙", "sekeb": "🪙", "nim": "🪙", "rob": "🪙",
}


async def _aiohttp_json(method, url, headers, payload=None, timeout=120):
    """POST/GET JSON via aiohttp: direct first, SOCKS proxy as fallback.

    Returns (status, parsed_json_or_None). Never logs headers or payloads.
    """
    import aiohttp

    async def _once(proxy_connector=None):
        async with aiohttp.ClientSession(connector=proxy_connector, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            if method == "POST":
                async with session.post(url, headers=headers, json=payload) as resp:
                    try:
                        txt = await resp.text()
                        data = json.loads(txt)
                    except Exception:
                        try:
                            data, _ = json.JSONDecoder().raw_decode(txt)
                        except Exception:
                            data = None
                    return resp.status, data
            else:
                async with session.get(url, headers=headers) as resp:
                    try:
                        txt = await resp.text()
                        data = json.loads(txt)
                    except Exception:
                        try:
                            data, _ = json.JSONDecoder().raw_decode(txt)
                        except Exception:
                            data = None
                    return resp.status, data

    try:
        status, data = await _once()
        if 200 <= status < 300 and data is not None:
            return status, data
        logger.info("ai http direct failed (%s), trying proxy", status)
    except Exception as e:
        logger.info("ai http direct error (%s), trying proxy", type(e).__name__)
    if not HTTP_PROXY_URL:
        return 0, None
    try:
        from aiohttp_socks import ProxyConnector

        connector = ProxyConnector.from_url(HTTP_PROXY_URL)
        return await _once(connector)
    except Exception as e:
        logger.info("ai http proxy error (%s)", type(e).__name__)
        return 0, None


AI_EMOJI_MAP = {
    "check": ("✅", "5303308506227565965"),
    "cross": ("❌", "5303282637639543136"),
    "star": ("🌟", "5962868307248811532"),
    "fire": ("🔥", "5963214228209798963"),
    "heart": ("❤", "5962817828498181364"),
    "diamond": ("💎", "5958725897191165855"),
    "money": ("💸", "5960784535145680764"),
    "rocket": ("🚀", "5958604585839889620"),
    "warning": ("🚨", "5960648376092468597"),
    "party": ("🎉", "5962876622305497954"),
    "thumbs_up": ("👍", "5960548024181591190"),
    "thumbs_down": ("👎", "5963179434679733598"),
    "muscle": ("💪", "5960961470618406085"),
    "pray": ("🙏", "5962913443060125576"),
    "hundred": ("💯", "5963252079756579188"),
    "eyes": ("👀", "5962958488677125372"),
    "clap": ("👏", "5962961091427307022"),
    "bell": ("🔔", "5963223333540465643"),
    "boom": ("💥", "5962793265580216131"),
    "broken_heart": ("💔", "5960648431927037021"),
    "thinking": ("🤔", "5958454773085638062"),
    "point_up": ("☝", "5960811181122785083"),
    "sparkles": ("💫", "5963316684654644605"),
    "star": ("\u2b50\ufe0f", "5053473385355412667"),
    "target": ("🎯", "5242486160088899134"),
    "alarm": ("⏰", "5933977535422405375"),
    "warning_sign": ("\u26a0\ufe0f", "5935840722300182490"),
    "crown": ("👑", "5044126248029128166"),
    "money_bag": ("💰", "4965219701572503640"),
    "chart_up": ("📈", "5028746137645876535"),
    "chart_down": ("📉", "5028325978175177540"),
    "chart": ("📊", "5071491301443110142"),
    "search": ("🔎", "5301219309580738905"),
    "lightbulb": ("💡", "5323743114513373152"),
    "location": ("📍", "5321275372333979355"),
    "writing": ("\u270d\ufe0f", "5330550994159815930"),
    "pin": ("📌", "5864156824776743194"),
    "trophy": ("🏆", "5312160339335347417"),
    "question": ("❓", "5233684543738764528"),
    "exclamation": ("\u2757\ufe0f", "5233324062838639368"),
    "star_glow": ("🌟", "5962868307248811532"),
    "globe": ("🌐", "5996668686256052639"),
    "signal": ("📶", "6050886193032207644"),
    "lock": ("🔐", "6050646916109179497"),
    "phone": ("📱", "5866022060353918430"),
    "laptop": ("💻", "5933550168996581523"),
    "robot": ("🤖", "5931408462079594667"),
    "link": ("🔗", "5803014250171469676"),
    "lightning": ("\u26a1\ufe0f", "5803190781917269776"),
    "green_circle": ("🟢", "5818884798575284650"),
    "blue_circle": ("🔵", "5866328553515127723"),
    "package": ("📦", "5821344131208714546"),
    "cart": ("🛒", "6003375647055945783"),
    "calendar": ("📆", "5834822129425584578"),
    "down_arrow": ("\u2b07\ufe0f", "5805670623019537278"),
    "up_arrow_double": ("⏫", "5805470185485767041"),
    "new_label": ("🆕", "5805294512733426378"),
    "video_camera": ("📹", "5936178658916964051"),
    "sun": ("\u2600\ufe0f", "5917743942022992542"),
    "ok_hand": ("👌", "5920030720050336088"),
    "speech": ("💬", "5917749143228388681"),
    "handshake": ("🤝", "5917775342528893706"),
    "interrobang": ("\u2049\ufe0f", "5920148131571306711"),
    "music_notes": ("🎶", "5920187653860364547"),
    "patrick_angry": ("😡", "5868735513317347737"),
    "patrick_happy": ("😊", "5866376343616230931"),
    "patrick_laugh": ("😂", "5868359965671953555"),
    "patrick_love": ("🥰", "5870815475784488115"),
    "patrick_sad": ("😢", "5866233080687105240"),
    "heart_arrow": ("💘", "5997055396521448486"),
    "heart_ribbon": ("💝", "5996871473136931573"),
    "white_heart": ("🤍", "5996700417474435151"),
}


def rich_to_plain(html_text):
    """Convert AI Rich HTML to escaped plain-text lines for fallback delivery.
    Table rows become pipe rows, tg-emoji becomes its fallback emoji, links
    become their text. Output has no HTML tags and is HTML-escaped, so it is
    safe to send with parse_mode HTML."""
    import re as _re
    x = html_text
    x = _re.sub(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", x, flags=_re.S)
    x = _re.sub(r"<a[^>]*>(.*?)</a>", r"\1", x, flags=_re.S)
    x = _re.sub(r"</(tr|li|h2|h3|p)>", "\n", x)
    x = _re.sub(r"<li>", "• ", x)
    x = _re.sub(r"</(td|th)>", " | ", x)
    x = _re.sub(r"<[^>]+>", "", x)
    x = html.unescape(x)
    lines = []
    for ln in x.split("\n"):
        ln = " ".join(ln.split()).rstrip(" |").strip()
        if ln:
            lines.append(html.escape(ln))
    return "\n".join(lines)


def clean_search_url(url):
    """Unwrap Google redirect URLs to the real destination, so sources are
    short, real links instead of long google.com/goto redirect URLs."""
    try:
        import urllib.parse as _up
        parts = _up.urlparse(url)
        if "google.com" in parts.netloc:
            qs = _up.parse_qs(parts.query)
            for key in ("url", "q"):
                vals = qs.get(key)
                if vals and vals[0].startswith("http"):
                    return vals[0]
    except Exception:
        pass
    return url


SUMMARIZE_COMMANDS = {"خلاصه کن", "خلاصه", "خلاصه اش کن", "خلاصه اش", "خلاصه کن لطفا", "لطفا خلاصه کن", "summarize", "خلاصه سازی", "خلاصه سازی کن"}

FACTCHECK_COMMANDS = {"واقعی", "واقعیه", "این واقعیه", "این درسته", "درسته", "چک کن", "چک", "واقعی بودن", "واقعی بودنش", "صحت", "صحتش چیه", "راستی آزمایی", "حقیقت داره", "واقعیت داره", "ایا واقعیه", "ایا این واقعیه", "fact check", "factcheck"}

RICH_COMMANDS = {"ریچ کن", "ریچ", "ریچش کن", "ریچ اش کن", "ریچ سازی کن", "ریچ سازی", "ریچ کن لطفا", "لطفا ریچ کن", "rich", "rich کن", "richify"}


def normalize_reply_cmd(s):
    import re as _re
    x = (s or "").strip().lower()
    x = x.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    x = x.replace("\u200c", " ").replace("\u200d", " ").replace("-", " ").replace("ـ", " ")
    x = _re.sub(r"[؟?!.،,؛:]+", "", x)
    x = " ".join(x.split())
    return x


def classify_reply_cmd(arg):
    x = normalize_reply_cmd(arg)
    if not x:
        return None
    if x in SUMMARIZE_COMMANDS or x.startswith("خلاصه کن"):
        return "summarize"
    if x in FACTCHECK_COMMANDS or x.startswith("این واقعیه") or x.startswith("این درسته") or x.startswith("واقعیت داره") or x.startswith("حقیقت داره") or x.startswith("ایا واقعیه") or x.startswith("ایا این واقعیه"):
        return "factcheck"
    if x in RICH_COMMANDS or x.startswith("ریچ کن") or x.startswith("ریچش کن") or x.startswith("ریچ اش کن") or x.startswith("ریچ سازی"):
        return "rich"
    return None


def text_to_rich(text):
    """Convert plain text to Rich HTML faithfully: pipe tables, lists, headings, paragraphs.
    No LLM, no content change: cell/line text is preserved, only structure tags are added.
    Bare URLs become <a> links. HTML special chars are escaped."""
    import re as _re

    def _rich_inline(s):
        raw = s or ""
        tag_re = _re.compile(r"</?(b|strong|i|em|code|u|a|tg-emoji)(\s[^<>]*)?>", _re.IGNORECASE)
        tags = list(tag_re.finditer(raw))
        balanced = True
        for kind, open_pat, close_pat in [
            ("b", r"<(b|strong)(\s[^<>]*)?>", r"</(b|strong)>"),
            ("i", r"<(i|em)(\s[^<>]*)?>", r"</(i|em)>"),
            ("code", r"<code(\s[^<>]*)?>", r"</code>"),
            ("u", r"<u(\s[^<>]*)?>", r"</u>"),
            ("a", r"<a(\s[^<>]*)?>", r"</a>"),
            ("tg", r"<tg-emoji(\s[^<>]*)?>", r"</tg-emoji>"),
        ]:
            if len(_re.findall(open_pat, raw, _re.IGNORECASE)) != len(_re.findall(close_pat, raw, _re.IGNORECASE)):
                balanced = False
                break
        stored = []
        work = raw
        if balanced and tags:
            def _store(m):
                tag = m.group(0)
                low = tag.lower()
                if low.startswith("<strong"):
                    tag = "<b" + tag[7:]
                elif low.startswith("</strong"):
                    tag = "</b>"
                elif low.startswith("<em"):
                    tag = "<i" + tag[3:]
                elif low.startswith("</em"):
                    tag = "</i>"
                stored.append(tag)
                return "@@TAG" + str(len(stored) - 1) + "@@"
            work = tag_re.sub(_store, raw)
        out = esc(work)

        def _rep(m):
            u = m.group(0)
            tail = ""
            while u and u[-1] in ".,،؛:!?)]":
                tail = u[-1] + tail
                u = u[:-1]
            return f'<a href="{u}">{u}</a>' + tail
        out = _re.sub(r"https?://[^\s<>]+", _rep, out)
        out = _re.sub(r"\*\*(.+?)\*\*", lambda m: "<b>" + m.group(1) + "</b>", out)
        out = _re.sub(r"__(.+?)__", lambda m: "<b>" + m.group(1) + "</b>", out)
        out = _re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", out)
        for idx, tag in enumerate(stored):
            out = out.replace("@@TAG" + str(idx) + "@@", tag)
        return out

    def _cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def _is_sep(cells):
        cells = [c for c in cells if c]
        return bool(cells) and all(set(c) <= set("-: ") and "-" in c for c in cells)

    raw_lines = (text or "").splitlines()
    out = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        if not line:
            i += 1
            continue
        if "|" in line:
            rows = []
            while i < len(raw_lines) and "|" in raw_lines[i]:
                cells = _cells(raw_lines[i])
                if _is_sep(cells):
                    i += 1
                    continue
                rows.append(cells)
                i += 1
            if rows:
                out.append("<table>")
                for ri, row in enumerate(rows):
                    tag = "th" if ri == 0 else "td"
                    out.append("<tr>" + "".join(f"<{tag}>{_rich_inline(c)}</{tag}>" for c in row) + "</tr>")
                out.append("</table>")
            continue
        lm = _re.match(r"^([\-•\*–]\s+|\d+[.)]\s+)(.+)$", line)
        if lm:
            ordered = bool(_re.match(r"^\d+[.)]\s+", line))
            items = []
            while i < len(raw_lines):
                ilm = _re.match(r"^([\-•\*–]\s+|\d+[.)]\s+)(.+)$", raw_lines[i].strip())
                if not ilm:
                    break
                is_num = bool(_re.match(r"^\d+[.)]\s+", raw_lines[i].strip()))
                if is_num != ordered:
                    break
                items.append(ilm.group(2).strip())
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_rich_inline(it)}</li>" for it in items) + f"</{tag}>")
            continue
        if len(line) >= 4 and ((line.startswith("**") and line.endswith("**")) or (line.startswith("__") and line.endswith("__"))):
            out.append("<h3>" + _rich_inline(line.strip("*_")) + "</h3>")
            i += 1
            continue
        if line.endswith(":") and len(line) <= 80:
            out.append("<h3>" + _rich_inline(line[:-1].strip()) + "</h3>")
            i += 1
            continue
        para = [line]
        i += 1
        while i < len(raw_lines):
            nxt = raw_lines[i].strip()
            if not nxt or "|" in nxt or _re.match(r"^[\-•\*–]\s+|\d+[.)]\s+", nxt) or (nxt.endswith(":") and len(nxt) <= 80):
                break
            para.append(nxt)
            i += 1
        out.append("<p>" + "<br>".join(_rich_inline(q) for q in para) + "</p>")
    return chr(10).join(out)


def replace_plain_emojis_with_premium(html_text):
    """Replace plain Unicode emojis in Rich HTML text nodes with premium <tg-emoji> tags from AI_EMOJI_MAP.
    Single regex pass, longest variant first, so inserted tags are never re-scanned or double-wrapped.
    Existing <tg-emoji> and <code> blocks are protected and left untouched.
    Emojis with no map entry are left as-is. No ids are invented."""
    import re as _re
    if not html_text:
        return html_text
    variant_map = {}
    for _name, (_ch, _did) in AI_EMOJI_MAP.items():
        for _v in _emoji_variants(_ch):
            if _v not in variant_map:
                variant_map[_v] = (_ch, _did)
    variants = sorted(variant_map.keys(), key=len, reverse=True)
    pattern = _re.compile("|".join(_re.escape(_v) for _v in variants))
    protected = []

    def _protect(m):
        protected.append(m.group(0))
        return "@@PROT" + str(len(protected) - 1) + "@@"

    work = _re.sub(r"<tg-emoji[^<>]*>.*?</tg-emoji>|<code[^<>]*>.*?</code>", _protect, html_text, flags=_re.DOTALL)

    def _rep(m):
        _ch, _did = variant_map[m.group(0)]
        return f'<tg-emoji emoji-id="{_did}">{_ch}</tg-emoji>'

    work = pattern.sub(_rep, work)
    for _idx, _orig in enumerate(protected):
        work = work.replace("@@PROT" + str(_idx) + "@@", _orig)
    return work


async def handle_reply_rich(event, reply_text):
    """AI Rich conversion for a message, shared by .ai rich and .rich. Returns True when handled."""
    import uuid
    if not LLM_API_KEY:
        await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
        return True
    await event.edit("در حال ریچ کردن پیام...", parse_mode=ZHTML)
    rich_prompt = """You are a Persian Rich formatter. Reformat the given message as Rich HTML ONLY, no markdown, no code fences, no text outside HTML.
Preserve the original message exactly: same wording, same facts, numbers, names, and codes, in the same order. Do NOT summarize, do NOT omit anything, do NOT invent facts, do NOT add new headings, titles, introductions, or conclusions that are not in the original message. Use headings only for section titles already present in the message.
Turn tabular data into a real table, bullet lines into a list, numbered lines into a numbered list, and section titles into headings, so the message reads well on mobile.
Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, blockquote, a, table, tr, th, td, br, tg-emoji.
No div, span, style, img, button, script, strong, or any other tag. No inline styles. Close every tag.
Tables: first row th header cells, other rows td. Max 5 columns, max 30 rows, short cell text for mobile.
Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags.
Do NOT include sources. Do NOT invent URLs. Do NOT add a disclaimer or a header about AI.
Use premium emojis actively where they help: headings, key points, list items, at most 1 per heading/item, only from the mapping given below, copying the exact tg-emoji tag. Never invent an emoji-id. Do not use plain Unicode emojis in Rich output, use the premium tags instead."""
    rich_prompt = rich_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + chr(10).join(
        f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
        for name, (ch, did) in AI_EMOJI_MAP.items()
    )
    rich_answer = await llm_answer("", [], system_prompt_override=rich_prompt, user_prompt_override=reply_text[:8000])
    rich_title = " ".join(reply_text.split())[:50] or "پیام ریچ‌شده"
    if not rich_answer:
        rich_html = replace_plain_emojis_with_premium(text_to_rich(reply_text))
        if len(rich_html) > 8000:
            plain_fb = reply_text[:3500]
            if len(reply_text) > 3500:
                plain_fb = plain_fb + "..."
            await event.edit(esc(plain_fb), parse_mode=ZHTML)
            return True
        await deliver_inline_rich(event, "rich" + uuid.uuid4().hex[:12], rich_title, rich_html, reply_text.splitlines())
        return True
    text = rich_answer.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    text = replace_plain_emojis_with_premium(text)
    bad = ("<script", "<img", "<button", "tg-button", "<div", "<span", "<strong", "style=", "onclick")
    if len(text) > 8000 or any(b in text for b in bad):
        plain_fb = rich_to_plain(text)
        if len(plain_fb) > 3500:
            plain_fb = plain_fb[:3500] + "..."
        await event.edit(esc(plain_fb), parse_mode=ZHTML)
        return True
    plain_lines = rich_to_plain(text).splitlines() if "<" in text else reply_text.splitlines()
    await deliver_inline_rich(event, "rich" + uuid.uuid4().hex[:12], rich_title, text, plain_lines)
    return True


TTS_EMOTIONS = {
    "شاد": ("extremely happy, very excited, cheerful, maximum energy", "شاد"),
    "خوشحال": ("extremely happy, very excited, cheerful, maximum energy", "شاد"),
    "هیجانی": ("extremely happy, very excited, maximum energy", "هیجانی"),
    "happy": ("extremely happy, very excited, cheerful, maximum energy", "شاد"),
    "excited": ("extremely happy, very excited, maximum energy", "هیجانی"),
    "cheerful": ("extremely happy, very excited, cheerful, maximum energy", "شاد"),
    "غمگین": ("extremely sad, deeply melancholic, very slow", "غمگین"),
    "ناراحت": ("extremely sad, deeply melancholic, very slow", "غمگین"),
    "sad": ("extremely sad, deeply melancholic, very slow", "غمگین"),
    "عصبانی": ("extremely angry, furious, intense, very loud", "عصبانی"),
    "خشمگین": ("extremely angry, furious, intense, very loud", "عصبانی"),
    "angry": ("extremely angry, furious, intense, very loud", "عصبانی"),
    "آرام": ("very calm, gentle, soft, slow, relaxed", "آرام"),
    "ملایم": ("very calm, gentle, soft, slow, relaxed", "آرام"),
    "calm": ("very calm, gentle, soft, slow, relaxed", "آرام"),
    "ترسناک": ("extremely scary, eerie, whispering, very tense", "ترسناک"),
    "scary": ("extremely scary, eerie, whispering, very tense", "ترسناک"),
    "عاشقانه": ("extremely romantic, tender, warm", "عاشقانه"),
    "romantic": ("extremely romantic, tender, warm", "عاشقانه"),
    "خسته": ("extremely tired, sleepy, very slow, low energy", "خسته"),
    "tired": ("extremely tired, sleepy, very slow, low energy", "خسته"),
    "جدی": ("very serious, formal, steady", "جدی"),
    "serious": ("very serious, formal, steady", "جدی"),
    "بامزه": ("extremely playful, humorous, laughing, high energy", "بامزه"),
    "خنده‌دار": ("extremely playful, humorous, laughing, high energy", "بامزه"),
    "funny": ("extremely playful, humorous, laughing, high energy", "بامزه"),
    "نجوا": ("whispering, very quiet", "نجوا"),
    "whisper": ("whispering, very quiet", "نجوا"),
    "فریاد": ("shouting, very loud, extremely energetic", "فریاد"),
    "shout": ("shouting, very loud, extremely energetic", "فریاد"),
    "خنثی": ("", "خنثی"),
    "neutral": ("", "خنثی"),
}
TTS_VOICES = {
    "زن": ("Kore", "زن"),
    "female": ("Kore", "زن"),
    "woman": ("Kore", "زن"),
    "مرد": ("Charon", "مرد"),
    "male": ("Charon", "مرد"),
    "man": ("Charon", "مرد"),
}
TTS_MODEL = "gemini-3.8-flash-tts"
# Optional chat (channel / group / user id) where .tts results are also copied.
# Empty / 0 = disabled: results are only sent where the command ran.
TTS_COPY_CHAT_ID = int(os.getenv("TTS_COPY_CHAT_ID", "0") or 0)
TTS_MAX_CHARS = 2000


async def gemini_tts_ogg(speak_text, style, voice="Charon"):
    import base64
    import subprocess
    import uuid
    import wave

    import aiohttp
    from aiohttp_socks import ProxyConnector

    # Shared pool first (GEMINI_API_KEYS env, 1-30 keys); optional fallback is
    # a local file with one key per line (GEMINI_KEYS_FILE), then LLM_API_KEY.
    keys = list(GEMINI_KEYS)
    _keys_file = os.getenv("GEMINI_KEYS_FILE", "").strip()
    if not keys and _keys_file:
        try:
            keys = [ln.strip() for ln in Path(_keys_file).expanduser().read_text().splitlines() if ln.strip()]
        except Exception:
            keys = []
    if not keys and LLM_API_KEY:
        keys = [LLM_API_KEY]
    if not keys:
        return None, "هیچ کلید جمینای تنظیم نشده است."
    tmpdir = DOWNLOAD_DIR / "tts" / uuid.uuid4().hex[:12]
    tmpdir.mkdir(parents=True, exist_ok=True)
    wav_path = tmpdir / "voice.wav"
    ogg_path = tmpdir / "voice.ogg"
    content_item = {"type": "text", "text": speak_text}
    if style:
        content_item["annotations"] = [{"type": "speech_metadata", "style": style}]
    payload = {
        "model": TTS_MODEL,
        "input": [{"type": "user_input", "content": [content_item]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    # Direct by default; set HTTP_PROXY_URL to route the TTS calls via a proxy.
    _proxy_urls = (HTTP_PROXY_URL,) if HTTP_PROXY_URL else (None,)
    for _proxy_url in _proxy_urls:
        connector = ProxyConnector.from_url(_proxy_url) if _proxy_url else None
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=120)) as sess:
            for key in keys:
                try:
                    async with sess.post(
                        "https://generativelanguage.googleapis.com/v1beta/interactions",
                        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                        json=payload,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            audio_data = None
                            audio_mime = ""
                            for step in data.get("steps", []):
                                if step.get("type") != "model_output":
                                    continue
                                for item in step.get("content", []):
                                    if item.get("type") == "audio" and item.get("data"):
                                        audio_data = item["data"]
                                        audio_mime = item.get("mime_type", "")
                            if not audio_data:
                                continue
                            raw = base64.b64decode(audio_data)
                            if raw[:4] == b"RIFF" or "wav" in audio_mime.lower():
                                wav_path.write_bytes(raw)
                            else:
                                with wave.open(str(wav_path), "wb") as w:
                                    w.setnchannels(1)
                                    w.setsampwidth(2)
                                    w.setframerate(24000)
                                    w.writeframes(raw)
                            conv = subprocess.run(
                                ["ffmpeg", "-y", "-v", "error", "-i", str(wav_path), "-c:a", "libopus", "-b:a", "64k", str(ogg_path)],
                                capture_output=True, text=True,
                            )
                            if conv.returncode == 0 and ogg_path.exists() and ogg_path.stat().st_size > 0:
                                try:
                                    wav_path.unlink(missing_ok=True)
                                except Exception:
                                    pass
                                return ogg_path, None
                            return None, "تبدیل صوت ناموفق بود."
                        if resp.status == 400:
                            return None, "متن برای تبدیل مناسب نیست."
                        if resp.status in (429, 403, 500, 502, 503):
                            _gemini_mark_bad(key)
                        continue
                except Exception:
                    if _proxy_url is None:
                        continue  # direct mode: try next key
                    break  # network error on this proxy -> try next proxy
            else:
                return None, "همه کلیدها جواب ندادند، بعدا دوباره تلاش کن."
    return None, "خطای شبکه در تماس با سرویس صوت."


async def deliver_ai_answer(event, text, header_plain, header_rich, header_html, results):
    """Deliver an .ai answer (summarize / fact-check) as Rich, HTML, or plain.

    results is a list of search results or None (summarize: no sources).
    """
    import re as _re
    import uuid
    if text.startswith("```"):
        text = _re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
        text = text.strip()
    text = replace_plain_emojis_with_premium(text)
    src_urls = " • ".join([r['url'] for r in results[:5]]) if results else ""
    src_links = " • ".join(
        f"<a href=\"{esc(r['url'])}\">{esc(r['title'][:60])}</a>"
        for r in results[:5]
    ) if results else ""
    if "<table" in text or "<h2" in text or "<h3" in text:
        rich_body = "<p><i>" + AI_DISCLAIMER + "</i></p>" + header_rich + text
        bad = ("<script", "<img", "<button", "tg-button", "<div", "<span", "style=", "onclick")
        if len(rich_body) > 8000 or any(b in text for b in bad):
            plain_text = rich_to_plain(rich_body)
            if len(plain_text) > 3500:
                plain_text = plain_text[:3500] + "..."
            if results:
                plain_text += chr(10) + chr(10) + "منابع: " + src_urls
            await event.edit(plain_text)
            return True
        rich_html = rich_body
        if results:
            rich_html += "<h3>منابع</h3><ul>" + "".join(
                f"<li><a href=\"{esc(r['url'])}\">{esc(r['title'][:80])}</a></li>"
                for r in results[:5]
            ) + "</ul>"
        plain_lines = [ln for ln in rich_to_plain(rich_body).split(chr(10)) if ln.strip()]
        if results:
            plain_lines += ["", "منابع: " + src_urls]
        key = "ai" + uuid.uuid4().hex[:12]
        await deliver_inline_rich(event, key, "پاسخ هوش مصنوعی", rich_html, plain_lines)
        return True
    if "<tg-emoji" in text or "<b>" in text or "<a " in text:
        body_html = "<i>" + AI_DISCLAIMER + "</i>" + chr(10) + chr(10) + header_html + chr(10) + chr(10) + text
        if len(body_html) > 3500:
            body_html = body_html[:3500] + "..."
        try:
            if results:
                await event.edit(body_html + chr(10) + chr(10) + "منابع: " + src_links, parse_mode=ZHTML)
            else:
                await event.edit(body_html, parse_mode=ZHTML)
        except Exception:
            pt = AI_DISCLAIMER + chr(10) + chr(10) + header_plain + chr(10) + chr(10) + html.unescape(rich_to_plain(text))
            pt = pt[:3500]
            if results:
                pt += chr(10) + chr(10) + "منابع: " + src_urls
            await event.edit(pt)
        return True
    body_plain = AI_DISCLAIMER + chr(10) + chr(10) + header_plain + chr(10) + chr(10) + text
    if len(body_plain) > 3500:
        body_plain = body_plain[:3500] + "..."
    try:
        if results:
            await event.edit(html.escape(body_plain) + chr(10) + chr(10) + "منابع: " + src_links, parse_mode=ZHTML)
        else:
            await event.edit(html.escape(body_plain), parse_mode=ZHTML)
    except Exception:
        if results:
            await event.edit(body_plain + chr(10) + chr(10) + "منابع: " + src_urls)
        else:
            await event.edit(body_plain)
    return True


AI_DISCLAIMER = "این متن توسط هوش مصنوعی نوشته شده و نظر شخصی من نیست و ممکن است نادرست باشد."


async def apify_search(query):
    """Search the web with Apify google-search-scraper (1 page, 1 query).

    Returns a list of {title, url, snippet}. Cost is input-bound: one search
    page, no full-page scraping in v1.
    """
    if not APIFY_TOKEN:
        return []
    headers = {"Authorization": "Bearer " + APIFY_TOKEN, "Content-Type": "application/json"}
    status, run = await _aiohttp_json(
        "POST",
        "https://api.apify.com/v2/acts/apify~google-search-scraper/runs",
        headers,
        {"queries": query, "maxPagesPerQuery": 1},
        timeout=60,
    )
    if not run or not isinstance(run, dict):
        logger.info("apify run create failed, status %s", status)
        return []
    data = run.get("data") or {}
    run_id = data.get("id")
    dataset_id = data.get("defaultDatasetId")
    if not run_id or not dataset_id:
        logger.info("apify run missing id/dataset")
        return []
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(1)
        status2, run2 = await _aiohttp_json(
            "GET", "https://api.apify.com/v2/actor-runs/" + run_id, headers, timeout=30
        )
        if not run2 or not isinstance(run2, dict):
            break
        st = (run2.get("data") or {}).get("status", "")
        if st == "SUCCEEDED":
            break
        if st in ("FAILED", "TIMED-OUT", "ABORTED"):
            logger.info("apify run status %s", st)
            return []
    status3, items = await _aiohttp_json(
        "GET", "https://api.apify.com/v2/datasets/" + dataset_id + "/items?limit=20", headers, timeout=60
    )
    if not isinstance(items, list):
        logger.info("apify dataset items not a list, status %s", status3)
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = []
        if isinstance(item.get("organicResults"), list):
            candidates = item["organicResults"]
        elif isinstance(item.get("results"), list):
            candidates = item["results"]
        elif item.get("title") and item.get("url"):
            candidates = [item]
        for r in candidates:
            if not isinstance(r, dict):
                continue
            title = r.get("title") or ""
            url = r.get("url") or r.get("link") or ""
            snippet = r.get("description") or r.get("snippet") or r.get("text") or ""
            if title and url:
                out.append({"title": str(title).strip(), "url": clean_search_url(str(url).strip()), "snippet": str(snippet).strip()[:800]})
            if len(out) >= 8:
                return out
    return out


async def llm_answer(question, results, system_prompt_override=None, user_prompt_override=None):
    """Answer a question in Persian from Apify search results.

    OpenAI-compatible providers (openai, openrouter, or any base URL) use the
    chat completions API; gemini uses generateContent. Returns plain text or
    None on failure, so the caller can fall back to the raw search results.
    """
    provider = (LLM_PROVIDER or "openai").strip().lower()
    model = (LLM_MODEL or "").strip()
    if provider == "gemini":
        model = model or "gemini-3.8-flash"
    elif provider == "openrouter":
        model = model or "openai/gpt-4o-mini"
    else:
        model = model or "gpt-4o-mini"
    context_lines = []
    for i, r in enumerate(results[:8], 1):
        context_lines.append(f"{i}. {r['title']} ({r['url']}): {r['snippet']}")
    context = chr(10).join(context_lines)
    system_prompt = (
        "You are a helpful assistant. Answer in Persian (Farsi), concisely, "
        "for a mobile chat. Use ONLY the search results below. If the answer "
        "is not in the results, say so plainly instead of guessing. Do not "
        "use markdown. For plain answers, use plain Persian text with no HTML. "
        "RICH OUTPUT: If the answer naturally contains a table, comparison, "
        "list with headings, or the user asks for a table or a rich message, "
        "output RICH HTML ONLY, no markdown, no code fences, no text outside HTML. "
        "Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, "
        "blockquote, a, table, tr, th, td, br, tg-emoji. No div, span, style, "
        "img, button, script, or any other tag. No inline styles. "
        "Tables: first row th header cells, other rows td. Max 5 columns, "
        "max 30 rows, short cell text for mobile. Close every tag. "
        "Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags. "
        "Premium emoji: use premium emojis actively where they help: at the start of "
        "headings, verdicts, list items, and key points, at most 1 per heading/row/item, "
        "never 2 in a row. Use ONLY the mapping given below, copying the exact "
        "tg-emoji tag. Never invent an emoji-id. Do not use plain Unicode emojis in Rich "
        "output; use the premium tags instead. "
        "Do NOT include sources; the bot appends real source links itself. "
        "Do NOT invent URLs. Keep the answer under 300 words. "
        "Iranian money units: many Iranian sources quote prices in rials "
        "(ریال). 1 تومان = 10 ریال. If a source number is in rials, divide "
        "by 10 before reporting it in تومان, and always state the unit. "
        "Never label a rial number as تومان. Sanity check: the Iranian "
        "free-market dollar is in the hundreds of thousands of تومان (around "
        "270,000), not millions; a dollar number in the millions of تومان "
        "is almost certainly rials, so convert it. If sources disagree, "
        "report each source's number separately instead of mixing numbers "
        "from different sources into one range."
    )
    emoji_lines = chr(10).join(
        f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
        for name, (ch, did) in AI_EMOJI_MAP.items()
    )
    if system_prompt_override is not None:
        system_prompt = system_prompt_override
    else:
        system_prompt = system_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + emoji_lines
    if user_prompt_override is not None:
        user_prompt = user_prompt_override
    else:
        user_prompt = "Question: " + question + chr(10) + chr(10) + "Search results:" + chr(10) + context
    try:
        if provider == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
            payload = {
                "contents": [{"parts": [{"text": system_prompt + chr(10) + chr(10) + user_prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
            }
            # Shared pool: try keys round-robin; a 429 / quota / server error
            # cools that key down and moves to the next one. A 400 is
            # request-specific, not key-specific, so stop at once.
            for _ in range(max(len(GEMINI_KEYS), 1)):
                key = _gemini_next_key() or LLM_API_KEY
                if not key:
                    break
                headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
                status, data = await _aiohttp_json("POST", url, headers, payload, timeout=120)
                if status == 400:
                    logger.info("gemini answer failed, status 400, key #%d", _gemini_key_index(key))
                    return None
                if data and isinstance(data, dict):
                    cands = data.get("candidates") or []
                    if cands:
                        parts = ((cands[0].get("content") or {}).get("parts") or [])
                        if parts and parts[0].get("text"):
                            return parts[0]["text"].strip()
                if status in (429, 403, 500, 502, 503):
                    _gemini_mark_bad(key)
                logger.info("gemini answer failed, status %s, key #%d", status, _gemini_key_index(key))
            return None
        if provider == "openrouter":
            base = "https://openrouter.ai/api/v1"
            headers = {
                "Authorization": "Bearer " + LLM_API_KEY,
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/",
                "X-Title": "KetaSelf",
            }
        elif provider == "openai":
            base = "https://api.openai.com/v1"
            headers = {"Authorization": "Bearer " + LLM_API_KEY, "Content-Type": "application/json"}
        else:
            base = (LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
            headers = {"Authorization": "Bearer " + LLM_API_KEY, "Content-Type": "application/json"}
        url = base + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
            "enable_thinking": False,
        }
        status, data = await _aiohttp_json("POST", url, headers, payload, timeout=120)
        if not data or not isinstance(data, dict):
            logger.info("llm answer failed, status %s", status)
            return None
        choices = data.get("choices") or []
        if not choices:
            logger.info("llm answer no choices: %s", str(data)[:300])
            return None
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        return content or None
    except Exception as e:
        logger.info("llm answer error (%s)", type(e).__name__)
        return None


async def ketaself_v3_commands(event, cmd: str, arg: str) -> bool:
    """Short v4 command vocabulary. Legacy commands remain aliases."""
    p = esc(db.data["prefix"])
    bk = db.data["backup"]
    aliases = {
        "dl": "fetch", "save": "fetch", "دانلود": "fetch", "سیو": "fetch",
        "get": "fetch", "ig": "fetch", "insta": "fetch", "اینستا": "fetch",
        "yt": "fetch", "youtube": "fetch", "یوتیوب": "fetch",
        "tt": "fetch", "tiktok": "fetch", "تیکتاک": "fetch",
        "dlfind": "find", "جستجو": "find", "dump": "dest", "مقصد": "dest",
        "join": "join", "عضویت": "join", "watch": "watch", "unwatch": "unwatch",
        "رصد": "watch", "msgid": "id", "شناسه": "id",
        "ping": "status", "پینگ": "status", "q": "queue", "stop": "cancel",
        "video": "fetch"
    }
    cmd = aliases.get(cmd, cmd)

    if cmd in ("panel", "پنل"):
        await event.delete()
        try:
            results = await user_client.inline_query(BOT_USERNAME, "panel")
            if results:
                await results[0].click(event.chat_id, reply_to=event.reply_to_msg_id)
        except Exception as e:
            await user_client.send_message(
                event.chat_id,
                f"⚠️ <b>خطا در باز کردن پنل:</b>\n<code>{esc(e)}</code>",
                parse_mode=ZHTML,
            )
        return True

    if cmd in ("help", "h", "راهنما"):
        help_sections = [
            ("🪐", "پنل و وضعیت", "پنل شیشه‌ای همه‌ی تنظیمات را با دکمه دارد؛ این‌ها میانبرهای خطی همان بخش‌ها هستند.", [
                ("🪐", f"{p}panel", "باز کردن پنل شیشه‌ای (با فاصله هم کار می‌کند)"),
                ("🧲", f"{p}help", "همین راهنمای کامل"),
                ("📊", f"{p}status", "وضعیت دانلودر، آپتایم و نسخه"),
                ("📥", f"{p}queue", "صف دانلودهای در حال اجرا"),
                ("⏹", f"{p}cancel", "لغو دانلود جاری"),
            ]),
            ("🧲", "دانلودر تلگرام ضد قفل", "پست‌های کانال و گروه قفل‌شده و خصوصی را بدون نیاز به فوروارد می‌گیرد.", [
                ("🧲", f"{p}fetch لینک", "دریافت لینک پست تلگرام، کانال یا گروه"),
                ("🧲", f"{p}fetch", "ریپلای روی پست و دریافت همان پست"),
                ("🔍", f"{p}find عبارت", "جستجو در پیام‌های همین چت"),
                ("➕", f"{p}join لینک‌دعوت", "عضویت در کانال یا گروه خصوصی با لینک دعوت"),
                ("👀", f"{p}watch", "رصد این چت: پست‌های جدید خودکار کپی می‌شوند"),
                ("👀", f"{p}unwatch", "توقف رصد این چت"),
                ("📍", f"{p}dest", "مقصد ذخیره دانلودها = همین چت"),
                ("📍", f"{p}dest me", "مقصد ذخیره = Saved Messages"),
                ("🎞", f"{p}quality 720", "کیفیت دانلود اجتماعی"),
                ("⚙️", f"{p}setdl ig @bot1 @bot2", "ترتیب ربات‌های دانلودر؛ اگر اولی نشد، بعدی امتحان می‌شود"),
                ("🆔", f"{p}id", "آیدی عددی کاربر ریپلای‌شده"),
            ]),
            ("🌐", "دانلود اجتماعی", "اینستا، یوتیوب و تیک‌تاک از راه ربات دانلودر ثالث؛ بدون کانال اسپانسر و بدون جوین اجباری.", [
                ("🌐", f"{p}dl لینک", "دانلود کلیپ از لینک اینستا/یوتیوب/تیک‌تاک"),
                ("🌐", f"{p}dl متن", "اگر متن آهنگ باشد، جستجوی موزیک باز می‌شود"),
                ("🌐", f"{p}dl شماره", "دانلود مورد انتخاب‌شده از لیست موزیک"),
                ("🌐", f"{p}dl لینک تیک‌تاک", "کلیپ + آهنگ کامل همان کلیپ، هر دو فرستاده می‌شوند"),
            ]),
            ("🎵", "موزیک فایندر + دانلود", "جستجو و دانلود نسخه‌ی کامل آهنگ، نه پیش‌نمایش یک‌دقیقه‌ای.", [
                ("🎵", f"{p}music اسم آهنگ", "جستجو و نشان دادن لیست با مدت هر آهنگ"),
                ("🎵", f"{p}music شماره", "دانلود کامل آهنگ انتخاب‌شده از لیست"),
                ("🎵", f"{p}music لینک", "دانلود مستقیم آهنگ از لینک"),
                ("🎵", f"{p}music dl شماره", "همان دانلود با پیشوند dl"),
            ]),
            ("💰", "قیمت زنده", "هر بار تازه از منابع زنده گرفته می‌شود؛ بدون کش. اعداد به تومان و با نرخ دلار آزاد.", [
                ("💰", f"{p}price", "خلاصه ارزهای دیجیتال + دلار، یورو، پوند، طلا و سکه"),
                ("💰", f"{p}price btc", "قیمت یک ارز به‌تنهایی، با تغییر ۲۴ ساعته"),
                ("💰", f"{p}price دلار", "فقط بخش بازار ایران"),
                ("💰", f"{p}price طلا", "فقط بخش بازار ایران"),
            ]),
            ("🧠", "هوش مصنوعی", "سوال با سرچ وب، خلاصه پیام، راستی‌آزمایی و ریچ‌سازی پیام. اول هر پاسخ: «این متن توسط هوش مصنوعی نوشته شده و نظر شخصی من نیست و ممکن است نادرست باشد.» سوال بالای جواب می‌آید و منابع داخل متن با لینک‌اند؛ اگر جواب جدول/تیتر داشته باشد، ریچ می‌شود. پاسخ‌ها با ایموجی پریمیوم همراه‌اند.", [
                ("🧠", f"{p}ai سوال", "پاسخ با سرچ وب و منابع"),
                ("🧠", f"{p}ai خلاصه کن", "ریپلای روی پیام: خلاصه همان پیام"),
                ("🧠", f"{p}ai واقعی؟", "ریپلای روی پیام: بررسی واقعی بودن با حکم و دلیل"),
                ("🧠", f"{p}خلاصه", "ریپلای روی پیام: خلاصه همان پیام"),
                ("🧠", f"{p}واقعی؟", "ریپلای روی پیام: بررسی واقعی بودن با حکم و دلیل"),
                ("🧠", f"{p}ai ریچ کن", "ریپلای روی پیام: تبدیل همان پیام به ریچ"),
                ("✨", f"{p}rich", "ریپلای روی پیام یا متن مستقیم: تبدیل به ریچ با هوش مصنوعی و ایموجی پریمیوم"),
                ("🎙", f"{p}tts زن شاد متن", "متن مستقیم: ویس با صدای زن و احساس شاد"),
                ("🎙", f"{p}tts زن شاد متن + ریپلای", "ریپلای روی پیام + متن خودت: متن خودت خوانده می‌شود، ویس روی همان پیام می‌رود"),
                ("🎙", f"{p}tts زن شاد + ریپلای", "ریپلای بدون متن: پیام ریپلای‌شده خوانده می‌شود"),
                ("🎙", f"{p}tts", "صدا: زن/مرد (پیش‌فرض مرد)؛ احساس‌ها با حداکثر شدت: شاد، غمگین, عصبانی، آرام، ترسناک، عاشقانه، خسته، جدی، بامزه، نجوا، فریاد، خنثی؛ کپی ویس و پیام وضعیت در کانال TTS می‌روند؛ حداکثر ۲۰۰۰ کاراکتر"),
            ]),
            ("👤", "پروفایل و حضور", "نام، بیو و حالت آنلاین؛ تنظیم‌های بیشتر با دکمه در پنل بخش پروفایل.", [
                ("👤", f"{p}setname نام", "تنظیم نام اصلی اکانت"),
                ("👤", f"{p}setbio متن", "تنظیم بیوگرافی پایه"),
                ("👤", f"{p}addbio متن", "افزودن بیو به لیست چرخشی"),
                ("👤", f"{p}clearbios", "پاکسازی لیست بیوهای چرخشی"),
                ("👤", f"{p}clone", "ریپلای روی کاربر: کپی کامل نام و بیوی او"),
                ("🕐", "پنل پروفایل", "ساعت زنده روی اسم و بیو، آنلاین دائمی، اکشن چت تایپینگ/ویس/بازی، فونت ساعت"),
            ]),
            ("🤖", "منشی خودکار", "وقتی آفلاینی، به پیام‌های پی‌وی جواب آماده می‌دهد.", [
                ("🤖", f"{p}setreply متن", "تغییر متن پاسخ منشی"),
                ("🤖", "پنل منشی", "روشن/خاموش، فقط در زمان آفلاین بودن، فاصله ۱۵/۳۰/۶۰ دقیقه، ریست حافظه"),
            ]),
            ("🔒", "امنیت و مدیریت پی‌وی", "شناسایی اکانت مشکوک و کنترل سریع افرادی که پیام می‌دهند.", [
                ("🔒", f"{p}check", "استعلام کامل اکانت و ذخیره در Saved Messages"),
                ("🔒", f"{p}whois", "همان استعلام، با نام دیگر"),
                ("🔒", f"{p}saveuser", "ذخیره مشخصات کاربر در Saved Messages"),
                ("✅", f"{p}wl", "افزودن کاربر به لیست سفید پی‌وی"),
                ("🔇", f"{p}mute", "سکوت کاربر در پی‌وی"),
                ("🔊", f"{p}unmute", "رفع سکوت کاربر"),
                ("🚫", f"{p}block", "مسدودسازی سریع کاربر"),
                ("✅", f"{p}unblock", "رفع مسدودیت کاربر"),
                ("❤️", f"{p}setreact", "تنظیم ری‌اکشن خودکار پی‌وی"),
                ("⚔️", f"{p}addenemy", "افزودن به لیست دشمن: پاسخ و ری‌اکشن خودکار"),
                ("⚔️", f"{p}delenemy", "حذف از لیست دشمن"),
                ("🤝", f"{p}addfriend", "افزودن به لیست دوست ویژه"),
                ("🤝", f"{p}delfriend", "حذف از لیست دوست ویژه"),
            ]),
            ("🗂", "بکاپ و آنتی‌دلیت", "این‌ها خودکارند و با دکمه در پنل بخش بکاپ روشن و خاموش می‌شوند.", [
                ("🔥", f"{p}save", "ریپلای روی پیام: ذخیره دستی در Saved Messages"),
                ("🔥", "سیو خودکار تایمدار", "عکس، ویدیو و ویس زماندار پی‌وی همان لحظه در Saved Messages ذخیره می‌شود"),
                ("🗑", "آنتی‌دلیت پی‌وی و گروه", "پیام پاک‌شده با مشخصات فرستنده برایت ارسال می‌شود"),
                ("✏️", "آنتی‌ادیت", "ویرایش پیام پی‌وی گزارش می‌شود"),
            ]),
            ("📅", "پیام خودکار", "ارسال دوره‌ای یک پیام به چت‌های هدف.", [
                ("📅", f"{p}addauto", "افزودن همین چت به لیست ارسال خودکار"),
                ("📅", f"{p}delauto", "حذف همین چت از لیست ارسال خودکار"),
                ("📅", f"{p}setautotext متن", "تنظیم متن پیام خودکار"),
            ]),
            ("🎨", "استایل متن و انیمیشن", "افکت‌های نمایشی روی پیام‌های خودت؛ استایل دائمی خروجی هم از پنل بخش استایل متن.", [
                ("⌨️", f"{p}type متن", "تایپ تدریجی متن، حرف‌به‌حرف"),
                ("❤️", f"{p}heart", "انیمیشن قلب‌های رنگی"),
                ("⏳", f"{p}load", "انیمیشن نوار بارگذاری تا ۱۰۰ درصد"),
                ("🎲", f"{p}dice", "فرستادن تاس"),
                ("🎯", f"{p}dart", "فرستادن دارت"),
                ("🎨", "پنل استایل متن", "فرمت خودکار خروجی: ضخیم، مونو، کج، اسپویلر، نقل‌قول، خط‌خورده، فونت لاتین"),
            ]),
            ("💎", "ایموجی پریمیوم", "ایموجی سفارشی تلگرام؛ اگر اکانت پریمیوم نباشد، ایموجی عادی نشان داده می‌شود.", [
                ("💎", f"{p}emojiid", "ریپلای روی ایموجی سفارشی: گرفتن آیدی آن"),
                ("💎", f"{p}setpe", "ریپلای روی ایموجی سفارشی: ذخیره برای جایگزینی خودکار"),
                ("💎", f"{p}setui", "ریپلای روی ایموجی سفارشی: ذخیره برای ایموجی‌های پنل"),
                ("💎", f"{p}pepack", "ذخیره یک پک کامل ایموجی پریمیوم"),
                ("💎", f"{p}pe متن", "فرستادن متن با ایموجی‌های پریمیوم ذخیره‌شده"),
                ("💎", "جایگزینی خودکار", "در پیام‌های عادی، ایموجی‌های نگاشت‌شده خودکار پریمیوم می‌شوند"),
            ]),
            ("🛠", "ابزارها", "ابزارهای روزمره روی پیام‌ها و چت‌ها.", [
                ("⚡", f"{p}ping", "وضعیت و پینگ (میانبر وضعیت)"),
                ("🧮", f"{p}calc عبارت", "محاسبه سریع عبارت ریاضی"),
                ("⌨️", f"{p}fa", "ریپلای روی متن: اصلاح کیبورد فارسی/انگلیسی"),
                ("🌐", f"{p}tr", "ریپلای روی متن: ترجمه"),
                ("📊", f"{p}chatinfo", "آمار کامل گروه یا کانال"),
                ("🗑", f"{p}del", "ریپلای روی پیام: حذف همان پیام"),
                ("🗑", f"{p}purge عدد", "حذف چند پیام آخر چت"),
                ("🗑", f"{p}purgeme عدد", "حذف چند پیام آخر خودت در چت"),
                ("📣", f"{p}spam عدد متن", "فرستادن یک متن تا ۵۰ بار"),
                ("📢", f"{p}tagall", "منشن همه‌ی اعضای چت"),
            ]),
            ("⌨️", "پیشوند دستورها", "پیشوند فعلی نقطه است؛ از پنل بخش پیشوند می‌توانی آن را عوض کنی.", [
                ("⌨️", "پنل پیشوند", "انتخاب بین نقطه، تعجب، اسلش، شارپ، ستاره، موج"),
            ]),
        ]
        help_plain = []
        for sec_icon, sec_title, sec_desc, sec_rows in help_sections:
            help_plain.append(f"{pe(sec_icon)} {sec_title}: {sec_desc}")
            help_plain.append("دستور | کار")
            help_plain.append("----------------------------------------")
            help_plain += [f"{pe(ic)} {c} | {d}" for ic, c, d in sec_rows]
            help_plain.append("")
        help_rich = "<h2>" + pe("🧲") + " راهنمای کامل KetaSelf</h2>" + chr(10) + chr(10).join("<h3>" + pe(sec_icon) + " " + sec_title + "</h3>" + chr(10) + "<p>" + sec_desc + "</p>" + chr(10) + rich_table(["دستور", "کار"], [[f"{pe(ic)} {c}", d] for ic, c, d in sec_rows]) for sec_icon, sec_title, sec_desc, sec_rows in help_sections)
        await deliver_inline_rich(event, "help", "راهنمای کامل", help_rich, help_plain)
        return True

    if cmd == "status":
        queued = sum(1 for j in DOWNLOAD_JOBS.values() if j["state"] == "queued")
        running = sum(1 for j in DOWNLOAD_JOBS.values() if j["state"] == "running")
        status_rows = [
            ("⚙️", "نسخه", f"v4.0 · روشن بودن: {get_uptime()}"),
            ("📥", "در حال اجرا / در صف", f"{running} / {queued}"),
            ("📍", "مقصد", esc(dump_target())),
            ("🎞", "کیفیت اجتماعی", esc(db.data['social_dl'].get('quality', '720'))),
        ]
        status_plain = ["مورد | مقدار", "----------------------------------------"] + [f"{pe(icon)} {item} | {val}" for icon, item, val in status_rows]
        status_rich = "<h2>" + pe("📊") + " وضعیت دانلودر</h2>" + chr(10) + rich_table(["مورد", "مقدار"], [[f"{pe(icon)} {item}", val] for icon, item, val in status_rows])
        await deliver_inline_rich(event, "status", "وضعیت دانلودر", status_rich, status_plain)
        return True

    if cmd == "queue":
        jobs = [j for j in DOWNLOAD_JOBS.values() if j["chat_id"] == event.chat_id]
        if not jobs:
            await event.edit("✅ صف دانلود این چت خالیه.")
        else:
            lines = [f"#{j['id']} · {'⬇️ در حال اجرا' if j['state']=='running' else '🕒 در صف'} · {esc(j['title'])}" for j in jobs]
            await event.edit("📥 <b>صف دانلود</b>\n<blockquote>" + "\n".join(lines) + "</blockquote>\nبرای لغو: <code>"+p+"cancel [شماره]</code>", parse_mode=ZHTML)
        return True

    if cmd == "cancel":
        jobs = [j for j in list(DOWNLOAD_JOBS.values()) if j["chat_id"] == event.chat_id]
        if arg.strip().isdigit():
            jobs = [j for j in jobs if j["id"] == int(arg.strip())]
        for j in jobs:
            task = j.get("task")
            if task and not task.done():
                task.cancel()
        await event.edit(f"⏹ درخواست لغو برای <b>{len(jobs)}</b> دانلود ارسال شد." if jobs else "صف این چت دانلودی نداره.")
        return True

    if cmd in ("price", "قیمت", "ارز", "دلار", "طلا", "crypto"):
        await event.edit("در حال گرفتن قیمت‌های زنده...")
        crypto, ir, dollar, tgju_date = await get_price_data()
        if not crypto and not ir:
            await event.edit("قیمت‌ها در دسترس نیست. دوباره تلاش کن.")
            return True
        q = arg.strip().lower()
        lines = []
        if q in PRICE_COINS:
            cid, label = PRICE_COINS[q]
            info = crypto.get(cid) or {}
            usd = info.get("usd")
            chg = info.get("usd_24h_change")
            if usd is None:
                await event.edit("این ارز پیدا نشد.")
                return True
            lines.append("ارز | قیمت (دلار) | قیمت (تومان) | تغییر")
            lines.append("----------------------------------------")
            chg_txt = f"{chg:+.1f}%" if chg is not None else "-"
            toman_txt = f"{fmt_toman(float(usd) * dollar)} تومان" if dollar else "-"
            lines.append(f"{pe(PRICE_ICONS.get(q, EMOJI))} {label} | {fmt_usd(usd)} دلار | {toman_txt} | {chg_txt}")
            await deliver_price(event, lines, "<h2>" + label + "</h2>" + chr(10) + lines_to_rich_table(lines))
            return True
        if q in ("dollar", "دلار", "usd", "طلا", "gold", "سکه"):
            pass
        else:
            order = ["btc", "eth", "sol", "bnb", "xrp", "doge", "trx", "ada", "usdt"]
            seen = set()
            lines.append("<b>ارز دیجیتال (تتر زنده)</b>")
            lines.append("ارز | قیمت (دلار) | قیمت (تومان) | تغییر")
            lines.append("----------------------------------------")
            for sym in order:
                cid, label = PRICE_COINS[sym]
                if cid in seen:
                    continue
                seen.add(cid)
                info = crypto.get(cid) or {}
                if info.get("usd") is None:
                    continue
                usd = info["usd"]
                chg = info.get("usd_24h_change")
                chg_txt = f"{chg:+.1f}%" if chg is not None else "-"
                toman_txt = f"{fmt_toman(float(usd) * dollar)} تومان" if dollar else "-"
                lines.append(f"{pe(PRICE_ICONS.get(sym, '💰'))} {label} | {fmt_usd(usd)} دلار | {toman_txt} | {chg_txt}")
        if ir:
            lines.append("")
            lines.append("<b>دلار و طلا و سکه (بازار ایران" + (f" - {tgju_date}" if tgju_date else "") + ")</b>")
            lines.append("کالا | قیمت (تومان)")
            lines.append("----------------------------------------")
            if dollar:
                tgju_d = tgju_toman({"current": ir}, "price_dollar_rl")
                if tgju_d and dollar != tgju_d:
                    lines.append(f"{pe(IR_ICONS.get('price_dollar_rl', '💰'))} دلار آزاد (تتر زنده) | {fmt_toman(dollar)} تومان")
            ir_rows = [
                ("price_dollar_rl", "دلار آزاد"),
                ("price_eur", "یورو"),
                ("price_gbp", "پوند"),
                ("geram18", "طلای 18 عیار (گرم)"),
                ("geram24", "طلای 24 عیار (گرم)"),
                ("sekee", "سکه امامی"),
                ("sekeb", "سکه بهار آزادی"),
                ("nim", "نیم سکه"),
                ("rob", "ربع سکه"),
            ]
            for key, label in ir_rows:
                v = tgju_toman({"current": ir}, key)
                if v is not None:
                    lines.append(f"{pe(IR_ICONS.get(key, '💰'))} {label} | {fmt_toman(v)} تومان")
        elif dollar:
            lines.append("")
            lines.append(f"دلار (والکس) | {fmt_toman(dollar)} تومان")

        rich_summary = "<h2>قیمت‌های زنده</h2>" + chr(10) + lines_to_rich_table(lines)
        await deliver_price(event, lines, rich_summary)
        return True

    if cmd in ("ai", "هوش", "ask"):
        if not arg.strip():
            await event.edit("استفاده: .ai سوال", parse_mode=ZHTML)
            return True
        reply_kind = classify_reply_cmd(arg.strip())
        if reply_kind is not None:
            if not event.is_reply:
                await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
                return True
            reply_msg = await event.get_reply_message()
            reply_text = ""
            if reply_msg is not None:
                reply_text = (reply_msg.text or reply_msg.message or "").strip()
            if not reply_text:
                await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
                return True
            if reply_kind == "summarize":
                if not LLM_API_KEY:
                    await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
                    return True
                await event.edit("در حال خلاصه کردن پیام...", parse_mode=ZHTML)
                sum_prompt = (
                    "You are a concise Persian summarizer. Summarize the given message in Persian, "
                    "preserving key facts, numbers, names, and dates. Keep it under 200 words unless "
                    "the message is long. Do not invent facts. If the message is unclear, say so plainly. "
                    "Do not use markdown. For plain answers, use plain Persian text with no HTML. "
                    "RICH OUTPUT: If the summary naturally contains a table, comparison, or headings, "
                    "output RICH HTML ONLY, no markdown, no code fences, no text outside HTML. "
                    "Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, blockquote, a, table, tr, th, td, br, tg-emoji. "
                    "No div, span, style, img, button, script, or any other tag. No inline styles. "
                    "Tables: first row th header cells, other rows td. Max 5 columns, max 30 rows, short cell text for mobile. Close every tag. "
                    "Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags. "
                    "Do NOT include sources. Do NOT invent URLs. "
                    "Use premium emojis actively where they help: headings, key points, list items, "
                    "at most 1 per heading/item, only from the mapping given below, copying the exact tg-emoji tag. "
                    "Never invent an emoji-id."
                )
                sum_prompt = sum_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + chr(10).join(
                    f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
                    for name, (ch, did) in AI_EMOJI_MAP.items()
                )
                sum_answer = await llm_answer("", [], system_prompt_override=sum_prompt, user_prompt_override=reply_text[:8000])
                if not sum_answer:
                    await event.edit("خلاصه کردن ناموفق بود.", parse_mode=ZHTML)
                    return True
                await deliver_ai_answer(event, sum_answer, "خلاصه پیام ریپلای‌شده:", "<h2>خلاصه پیام ریپلای‌شده</h2>", "<b>خلاصه پیام ریپلای‌شده:</b>", None)
                return True
            if reply_kind == "rich":
                return await handle_reply_rich(event, reply_text)
            if not APIFY_TOKEN:
                await event.edit("توکن Apify تنظیم نشده است.", parse_mode=ZHTML)
                return True
            if not LLM_API_KEY:
                await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
                return True
            await event.edit("در حال بررسی واقعی بودن پیام...", parse_mode=ZHTML)
            fc_results = await apify_search(" ".join(reply_text.split())[:300])
            if not fc_results:
                excerpt0 = " ".join(reply_text.split())[:200]
                await event.edit("پیام بررسی‌شده: " + esc(excerpt0) + chr(10) + chr(10) + "برای بررسی، نتیجه سرچی پیدا نشد.", parse_mode=ZHTML)
                return True
            fc_prompt = (
                "You are a Persian fact-checker. Given a message/claim and web search results, judge it as: "
                "واقعی (true), نادرست (false), گمراه‌کننده (misleading), or قابل تأیید نیست (unverifiable). "
                "Start with the verdict, then evidence from the search results, then what is wrong or missing, "
                "with confidence (بالا/متوسط/کم). Use ONLY the search results. If the results do not support a verdict, "
                "say قابل تأیید نیست instead of guessing. Do not invent sources. Do NOT include a sources list; "
                "the bot appends real source links itself. Do NOT invent URLs. Keep it under 300 words. "
                "Iranian money units: 1 تومان = 10 ریال. If a source number is in rials, divide by 10 before reporting it in تومان, and always state the unit. "
                "RICH OUTPUT: If the verdict naturally needs a table or headings, output RICH HTML ONLY, no markdown, no code fences, no text outside HTML. "
                "Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, blockquote, a, table, tr, th, td, br, tg-emoji. "
                "No div, span, style, img, button, script, or any other tag. No inline styles. Close every tag. "
                "Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags. "
                "Use premium emojis actively: start the verdict with a premium emoji (واقعی with check, "
                "نادرست with cross, گمراه‌کننده with warning_sign, قابل تأیید نیست with thinking), "
                "at most 1 per heading/item, only from the mapping given below, copying the exact tg-emoji tag. "
                "Never invent an emoji-id."
            )
            fc_question = "آیا پیام زیر واقعی است؟" + chr(10) + reply_text[:1000]
            fc_prompt = fc_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + chr(10).join(
                f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
                for name, (ch, did) in AI_EMOJI_MAP.items()
            )
            fc_answer = await llm_answer(fc_question, fc_results, system_prompt_override=fc_prompt)
            if not fc_answer:
                lines = [f"{i + 1}. {r['title']} - {r['url']}" for i, r in enumerate(fc_results[:5])]
                await event.edit("پیام بررسی‌شده: " + " ".join(reply_text.split())[:200] + chr(10) + chr(10) + "بررسی مدل ناموفق بود؛ نتایج سرچ:" + chr(10) + chr(10).join(lines))
                return True
            excerpt = " ".join(reply_text.split())[:200]
            await deliver_ai_answer(event, fc_answer, "پیام بررسی‌شده: " + excerpt, "<h2>بررسی واقعی بودن پیام</h2>", "<b>پیام بررسی‌شده:</b> " + esc(excerpt), fc_results)
            return True
        if not APIFY_TOKEN:
            await event.edit("توکن Apify تنظیم نشده است.", parse_mode=ZHTML)
            return True
        if not LLM_API_KEY:
            await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
            return True
        await event.edit(f"در حال جستجو و پاسخ به: {esc(arg.strip()[:200])}...", parse_mode=ZHTML)
        results = await apify_search(arg.strip())
        if not results:
            await event.edit(f"سوال: {esc(arg.strip()[:200])}" + chr(10) + "جستجو نتیجه‌ای نداد.", parse_mode=ZHTML)
            return True
        await event.edit(f"در حال نوشتن پاسخ به: {esc(arg.strip()[:200])}...", parse_mode=ZHTML)
        answer = await llm_answer(arg.strip(), results)
        if not answer:
            lines = [f"{i + 1}. {r['title']} - {r['url']}" for i, r in enumerate(results[:5])]
            await event.edit(f"سوال: {arg.strip()}" + chr(10) + chr(10) + "پاسخ مدل ناموفق بود؛ نتایج سرچ:" + chr(10) + chr(10).join(lines))
            return True
        text = answer.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()
        sources = " • ".join([r['url'] for r in results[:5]])
        src_links = " • ".join(
            f"<a href=\"{esc(r['url'])}\">{esc(r['title'][:60])}</a>"
            for r in results[:5]
        )
        q_text = arg.strip()
        if "<table" in text or "<h2" in text or "<h3" in text:
            rich_body = "<p><i>" + AI_DISCLAIMER + "</i></p>" + "<h2>" + esc(q_text[:200]) + "</h2>" + text
            bad = ("<script", "<img", "<button", "tg-button", "<div", "<span", "style=", "onclick")
            if len(rich_body) > 8000 or any(b in text for b in bad):
                plain_text = rich_to_plain(rich_body)
                if len(plain_text) > 3500:
                    plain_text = plain_text[:3500] + "..."
                await event.edit(plain_text + chr(10) + chr(10) + "منابع: " + sources)
                return True
            rich_html = rich_body
            rich_html += "<h3>منابع</h3><ul>" + "".join(
                f"<li><a href=\"{esc(r['url'])}\">{esc(r['title'][:80])}</a></li>"
                for r in results[:5]
            ) + "</ul>"
            plain_lines = [ln for ln in rich_to_plain(rich_body).split(chr(10)) if ln.strip()]
            plain_lines += ["", "منابع: " + sources]
            import uuid
            key = "ai" + uuid.uuid4().hex[:12]
            await deliver_inline_rich(event, key, "پاسخ هوش مصنوعی", rich_html, plain_lines)
            return True
        if "<tg-emoji" in text or "<b>" in text or "<a " in text:
            body_html = "<i>" + AI_DISCLAIMER + "</i>" + chr(10) + chr(10) + "<b>سوال:</b> " + esc(q_text) + chr(10) + chr(10) + text
            if len(body_html) > 3500:
                body_html = body_html[:3500] + "..."
            try:
                await event.edit(body_html + chr(10) + chr(10) + "منابع: " + src_links, parse_mode=ZHTML)
            except Exception:
                pt = AI_DISCLAIMER + chr(10) + chr(10) + "سوال: " + q_text + chr(10) + chr(10) + html.unescape(rich_to_plain(text))
                await event.edit(pt[:3500] + chr(10) + chr(10) + "منابع: " + sources)
            return True
        body_plain = AI_DISCLAIMER + chr(10) + chr(10) + "سوال: " + q_text + chr(10) + chr(10) + text
        if len(body_plain) > 3500:
            body_plain = body_plain[:3500] + "..."
        try:
            await event.edit(html.escape(body_plain) + chr(10) + chr(10) + "منابع: " + src_links, parse_mode=ZHTML)
        except Exception:
            await event.edit(body_plain + chr(10) + chr(10) + "منابع: " + sources)
        return True

    if cmd in ("rich", "ریچ"):
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            rich_text = ""
            if reply_msg is not None:
                rich_text = (reply_msg.text or reply_msg.message or "").strip()
            if not rich_text:
                await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
                return True
            return await handle_reply_rich(event, rich_text)
        if arg.strip():
            return await handle_reply_rich(event, arg.strip())
        await event.edit("روی یک پیام متنی ریپلای کن یا متن را جلوی دستور بنویس.", parse_mode=ZHTML)
        return True

    if cmd in ("خلاصه",):
        if not event.is_reply:
            await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
            return True
        reply_msg = await event.get_reply_message()
        reply_text = ""
        if reply_msg is not None:
            reply_text = (reply_msg.text or reply_msg.message or "").strip()
        if not reply_text:
            await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
            return True
        if not LLM_API_KEY:
            await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
            return True
        await event.edit("در حال خلاصه کردن پیام...", parse_mode=ZHTML)
        sum_prompt = (
            "You are a concise Persian summarizer. Summarize the given message in Persian, "
            "preserving key facts, numbers, names, and dates. Keep it under 200 words unless "
            "the message is long. Do not invent facts. If the message is unclear, say so plainly. "
            "Do not use markdown. For plain answers, use plain Persian text with no HTML. "
            "RICH OUTPUT: If the summary naturally contains a table, comparison, or headings, "
            "output RICH HTML ONLY, no markdown, no code fences, no text outside HTML. "
            "Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, blockquote, a, table, tr, th, td, br, tg-emoji. "
            "No div, span, style, img, button, script, or any other tag. No inline styles. "
            "Tables: first row th header cells, other rows td. Max 5 columns, max 30 rows, short cell text for mobile. Close every tag. "
            "Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags. "
            "Do NOT include sources. Do NOT invent URLs. "
            "Use premium emojis actively where they help: headings, key points, list items, "
            "at most 1 per heading/item, only from the mapping given below, copying the exact tg-emoji tag. "
            "Never invent an emoji-id."
        )
        sum_prompt = sum_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + chr(10).join(
            f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
            for name, (ch, did) in AI_EMOJI_MAP.items()
        )
        sum_answer = await llm_answer("", [], system_prompt_override=sum_prompt, user_prompt_override=reply_text[:8000])
        if not sum_answer:
            await event.edit("خلاصه کردن ناموفق بود.", parse_mode=ZHTML)
            return True
        await deliver_ai_answer(event, sum_answer, "خلاصه پیام ریپلای‌شده:", "<h2>خلاصه پیام ریپلای‌شده</h2>", "<b>خلاصه پیام ریپلای‌شده:</b>", None)
        return True

    if cmd in ("واقعی", "واقعی؟"):
        if not event.is_reply:
            await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
            return True
        reply_msg = await event.get_reply_message()
        reply_text = ""
        if reply_msg is not None:
            reply_text = (reply_msg.text or reply_msg.message or "").strip()
        if not reply_text:
            await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
            return True
        if reply_kind == "rich":
            return await handle_reply_rich(event, reply_text)
        if not APIFY_TOKEN:
            await event.edit("توکن Apify تنظیم نشده است.", parse_mode=ZHTML)
            return True
        if not LLM_API_KEY:
            await event.edit("کلید مدل هوش مصنوعی تنظیم نشده است.", parse_mode=ZHTML)
            return True
        await event.edit("در حال بررسی واقعی بودن پیام...", parse_mode=ZHTML)
        fc_results = await apify_search(" ".join(reply_text.split())[:300])
        if not fc_results:
            excerpt0 = " ".join(reply_text.split())[:200]
            await event.edit("پیام بررسی‌شده: " + esc(excerpt0) + chr(10) + chr(10) + "برای بررسی، نتیجه سرچی پیدا نشد.", parse_mode=ZHTML)
            return True
        fc_prompt = (
            "You are a Persian fact-checker. Given a message/claim and web search results, judge it as: "
            "واقعی (true), نادرست (false), گمراه‌کننده (misleading), or قابل تأیید نیست (unverifiable). "
            "Start with the verdict, then evidence from the search results, then what is wrong or missing, "
            "with confidence (بالا/متوسط/کم). Use ONLY the search results. If the results do not support a verdict, "
            "say قابل تأیید نیست instead of guessing. Do not invent sources. Do NOT include a sources list; "
            "the bot appends real source links itself. Do NOT invent URLs. Keep it under 300 words. "
            "Iranian money units: 1 تومان = 10 ریال. If a source number is in rials, divide by 10 before reporting it in تومان, and always state the unit. "
            "RICH OUTPUT: If the verdict naturally needs a table or headings, output RICH HTML ONLY, no markdown, no code fences, no text outside HTML. "
            "Allowed Rich tags ONLY: h2, h3, p, b, i, u, code, ul, ol, li, blockquote, a, table, tr, th, td, br, tg-emoji. "
            "No div, span, style, img, button, script, or any other tag. No inline styles. Close every tag. "
            "Escape &, <, > in text as &amp; &lt; &gt;, except inside allowed tags. "
            "Use premium emojis actively: start the verdict with a premium emoji (واقعی with check, "
            "نادرست with cross, گمراه‌کننده with warning_sign, قابل تأیید نیست with thinking), "
            "at most 1 per heading/item, only from the mapping given below, copying the exact tg-emoji tag. "
            "Never invent an emoji-id."
        )
        fc_question = "آیا پیام زیر واقعی است؟" + chr(10) + reply_text[:1000]
        fc_prompt = fc_prompt + chr(10) + "Premium emoji mapping (copy exactly):" + chr(10) + chr(10).join(
            f"- {name}: <tg-emoji emoji-id=\"{did}\">{ch}</tg-emoji>"
            for name, (ch, did) in AI_EMOJI_MAP.items()
        )
        fc_answer = await llm_answer(fc_question, fc_results, system_prompt_override=fc_prompt)
        if not fc_answer:
            lines = [f"{i + 1}. {r['title']} - {r['url']}" for i, r in enumerate(fc_results[:5])]
            await event.edit("پیام بررسی‌شده: " + " ".join(reply_text.split())[:200] + chr(10) + chr(10) + "بررسی مدل ناموفق بود؛ نتایج سرچ:" + chr(10) + chr(10).join(lines))
            return True
        excerpt = " ".join(reply_text.split())[:200]
        await deliver_ai_answer(event, fc_answer, "پیام بررسی‌شده: " + excerpt, "<h2>بررسی واقعی بودن پیام</h2>", "<b>پیام بررسی‌شده:</b> " + esc(excerpt), fc_results)
        return True

    if cmd in ("tts", "صوت"):
        reply_text = ""
        if event.is_reply:
            rm = await event.get_reply_message()
            if rm is not None:
                reply_text = (rm.text or rm.message or "").strip()
        arg_s = (arg or "").strip()
        tokens = arg_s.split()
        voice = "Charon"
        voice_name = "مرد"
        emotion_style = ""
        emotion_name = "خنثی"
        idx = 0
        if idx < len(tokens):
            v = TTS_VOICES.get(tokens[idx]) or TTS_VOICES.get(tokens[idx].lower())
            if v:
                voice, voice_name = v
                idx += 1
        if idx < len(tokens):
            emo = TTS_EMOTIONS.get(tokens[idx]) or TTS_EMOTIONS.get(tokens[idx].lower())
            if emo:
                emotion_style, emotion_name = emo
                idx += 1
        own_text = " ".join(tokens[idx:]).strip()
        if own_text:
            text_to_speak = own_text
        elif reply_text:
            text_to_speak = reply_text
        else:
            await event.edit("روی یک پیام متنی ریپلای کن یا متن را جلوی دستور بنویس. مثال: .tts زن شاد سلام چطوری؟", parse_mode=ZHTML)
            return True
        if not text_to_speak:
            await event.edit("روی یک پیام متنی ریپلای کن.", parse_mode=ZHTML)
            return True
        if len(text_to_speak) > TTS_MAX_CHARS:
            await event.edit(f"متن خیلی طولانی است، حداکثر {TTS_MAX_CHARS} کاراکتر.", parse_mode=ZHTML)
            return True
        is_copy_dest = bool(TTS_COPY_CHAT_ID) and (event.chat_id == TTS_COPY_CHAT_ID)
        status_msg = None
        if TTS_COPY_CHAT_ID and not is_copy_dest:
            try:
                status_msg = await user_client.send_message(TTS_COPY_CHAT_ID, f"دارم آماده‌اش می‌کنم... صدای {voice_name}، احساس {emotion_name}")
            except Exception:
                await event.edit("ارسال پیام وضعیت ناموفق بود.", parse_mode=ZHTML)
                return True
        try:
            await event.delete()
        except Exception:
            pass
        ogg_path, tts_err = await gemini_tts_ogg(text_to_speak, emotion_style, voice)
        if not ogg_path:
            err_text = f"ساخت صوت ناموفق بود: {esc(tts_err or 'خطای نامشخص')}"
            if status_msg is not None:
                try:
                    await status_msg.edit(err_text, parse_mode=ZHTML)
                except Exception:
                    pass
            else:
                try:
                    await user_client.send_message(event.chat_id, err_text, parse_mode=ZHTML)
                except Exception:
                    pass
            return True
        try:
            if TTS_COPY_CHAT_ID and not is_copy_dest:
                await user_client.send_file(TTS_COPY_CHAT_ID, str(ogg_path), voice_note=True)
            await user_client.send_file(
                event.chat_id, str(ogg_path), voice_note=True,
                reply_to=event.reply_to_msg_id if event.is_reply else None,
            )
            if status_msg is not None:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
        except Exception as e:
            err_text = f"خطا در ارسال صوت: {esc(e)}"
            if status_msg is not None:
                try:
                    await status_msg.edit(err_text, parse_mode=ZHTML)
                except Exception:
                    pass
            else:
                try:
                    await user_client.send_message(event.chat_id, err_text, parse_mode=ZHTML)
                except Exception:
                    pass
        finally:
            try:
                ogg_path.unlink(missing_ok=True)
                ogg_path.parent.rmdir()
            except Exception:
                pass
        return True

    if cmd in ("music", "song", "\u0645\u0648\u0632\u06cc\u06a9", "\u0622\u0647\u0646\u06af"):
        # Reply to a video/audio with no text: identify its song from the audio,
        # then download the full version from YouTube. Free route: relay to an
        # identification bot (AudD is paid, Shazam is blocked from this server).
        if not arg.strip() and event.is_reply:
            import uuid

            reply = await event.get_reply_message()
            if not reply or not reply.media:
                await event.edit("\u0631\u0648\u06cc \u06cc\u06a9 \u0648\u06cc\u062f\u06cc\u0648 \u06cc\u0627 \u0622\u0647\u0646\u06af \u0631\u06cc\u067e\u0644\u0627\u06cc \u06a9\u0646.", parse_mode=ZHTML)
                return True
            await event.edit("\u062f\u0631 \u062d\u0627\u0644 \u0634\u0646\u0627\u0633\u0627\u06cc\u06cc \u0622\u0647\u0646\u06af \u0627\u0632 \u0648\u06cc\u062f\u06cc\u0648...", parse_mode=ZHTML)
            tmpdir = Path("downloads") / "identify" / uuid.uuid4().hex[:12]
            try:
                tmpdir.mkdir(parents=True, exist_ok=True)
                src = await user_client.download_media(reply, file=tmpdir)
                if not src:
                    await event.edit("\u062f\u0627\u0646\u0644\u0648\u062f \u0648\u06cc\u062f\u06cc\u0648\u06cc \u0631\u06cc\u067e\u0644\u0627\u06cc\u200c\u0634\u062f\u0647 \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f.", parse_mode=ZHTML)
                    return True
                clip = tmpdir / "clip.mp3"
                if not await extract_audio_clip(Path(src), clip):
                    await event.edit("\u0628\u0631\u06cc\u062f\u0646 \u0635\u062f\u0627\u06cc \u0648\u06cc\u062f\u06cc\u0648 \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f.", parse_mode=ZHTML)
                    return True
                artist, title = await identify_song_via_bot(clip)
                if not artist or not title:
                    await event.edit("\u0622\u0647\u0646\u06af \u0634\u0646\u0627\u0633\u0627\u06cc\u06cc \u0646\u0634\u062f.", parse_mode=ZHTML)
                    return True
                results, err = await search_music_list(f"{artist} - {title}")
                if not results:
                    await event.edit("\u0622\u0647\u0646\u06af \u0634\u0646\u0627\u0633\u0627\u06cc\u06cc \u0634\u062f \u0648\u0644\u06cc \u0646\u0633\u062e\u0647\u200c\u06cc \u06a9\u0627\u0645\u0644 \u062f\u0631 \u06cc\u0648\u062a\u06cc\u0648\u0628 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f.", parse_mode=ZHTML)
                    return True
                await deliver_music(event, "https://www.youtube.com/watch?v=" + results[0]["id"])
            finally:
                try:
                    for pth in tmpdir.iterdir():
                        pth.unlink(missing_ok=True)
                    tmpdir.rmdir()
                except Exception:
                    pass
            return True
        # Pick a previous search result: .music 2
        m = re.match(r"^(?:dl\s+)?(\d+)$", arg.strip())
        if m:
            results = MUSIC_SEARCHES.get(event.chat_id)
            idx = int(m.group(1)) - 1
            if not results or idx < 0 or idx >= len(results):
                await event.edit("شماره‌ای برای دانلود نیست. اول با .music اسم آهنگ را جستجو کن.", parse_mode=ZHTML)
                return True
            chosen = results[idx]
            await event.edit(f"در حال دانلود کامل: {esc(chosen['title'])}", parse_mode=ZHTML)
            mp3_path, title_or_err = await download_music_file("https://www.youtube.com/watch?v=" + chosen["id"])
            if not mp3_path:
                await event.edit(f"دانلود ناموفق بود: {esc(title_or_err)}", parse_mode=ZHTML)
                return True
            try:
                await user_client.send_file(
                    event.chat_id, str(mp3_path), caption=f"🎵 {title_or_err}",
                    attributes=[types.DocumentAttributeAudio(title=title_or_err)],
                )
                await event.edit(f"موزیک کامل فرستاده شد: {esc(title_or_err)}", parse_mode=ZHTML)
            except Exception as e:
                await event.edit(f"خطا در ارسال فایل: {esc(e)}", parse_mode=ZHTML)
            finally:
                try:
                    mp3_path.unlink(missing_ok=True)
                    mp3_path.parent.rmdir()
                except Exception:
                    pass
            return True
        # Direct link: download immediately, no sponsor, no join
        if arg.strip().startswith("http"):
            await event.edit("در حال دانلود کامل موزیک از لینک...", parse_mode=ZHTML)
            mp3_path, title_or_err = await download_music_file(arg.strip().split()[0])
            if not mp3_path:
                await event.edit(f"دانلود ناموفق بود: {esc(title_or_err)}", parse_mode=ZHTML)
                return True
            try:
                await user_client.send_file(
                    event.chat_id, str(mp3_path), caption=f"🎵 {title_or_err}",
                    attributes=[types.DocumentAttributeAudio(title=title_or_err)],
                )
                await event.edit(f"موزیک کامل فرستاده شد: {esc(title_or_err)}", parse_mode=ZHTML)
            except Exception as e:
                await event.edit(f"خطا در ارسال فایل: {esc(e)}", parse_mode=ZHTML)
            finally:
                try:
                    mp3_path.unlink(missing_ok=True)
                    mp3_path.parent.rmdir()
                except Exception:
                    pass
            return True
        # Text query: finder first, then download by number
        if not arg.strip():
            await event.edit("استفاده: .music اسم آهنگ + خواننده  |  .music لینک  |  .music شماره (بعد از جستجو)", parse_mode=ZHTML)
            return True
        await event.edit(f"در حال جستجو برای: {esc(arg.strip())}", parse_mode=ZHTML)
        results, err = await search_music_list(arg.strip())
        if not results:
            await event.edit(f"جستجو نتیجه‌ای نداد: {esc(err or '')}", parse_mode=ZHTML)
            return True
        MUSIC_SEARCHES[event.chat_id] = results
        lines = [f"{i + 1}. {esc(r['title'])} ({esc(r['duration'])})" for i, r in enumerate(results)]
        music_rows = [[str(i + 1), f"{pe('🎵')} {esc(r['title'])}", esc(r['duration'])] for i, r in enumerate(results)]
        music_plain = ["# | آهنگ | مدت", "----------------------------------------"] + [f"{i + 1} | {pe('🎵')} {esc(r['title'])} | {esc(r['duration'])}" for i, r in enumerate(results)] + ["برای دانلود کامل، .music و شماره را بفرست. مثال: .music 1"]
        music_rich = "<h2>نتایج جستجو</h2>" + chr(10) + rich_table(["#", "آهنگ", "مدت"], music_rows) + chr(10) + "برای دانلود کامل، .music و شماره را بفرست. مثال: .music 1"
        await deliver_inline_rich(event, "music", "نتایج جستجو", music_rich, music_plain)
        return True

    if cmd == "fetch":
        m_dl = re.match(r"^(?:dl\s+)?(\d+)$", arg.strip())
        if m_dl:
            results_dl = MUSIC_SEARCHES.get(event.chat_id)
            idx_dl = int(m_dl.group(1)) - 1
            if results_dl and 0 <= idx_dl < len(results_dl):
                await deliver_music(event, "https://www.youtube.com/watch?v=" + results_dl[idx_dl]["id"])
                return True
        link = arg.strip()
        reply_source = None
        if not link and event.is_reply:
            reply_source = await event.get_reply_message()
            link = reply_source.raw_text or ""
        social_match = SOCIAL_URL_RE.search(link or "")
        tg_match = re.search(r"https?://(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/\S+", link or "", re.I)
        if (not link or (not social_match and not tg_match)) and event.is_reply and reply_source:
            status = await event.edit("🧲 <i>جاری در صف...</i>", parse_mode=ZHTML)
            async def reply_work():
                group = await collect_album(await event.get_input_chat(), reply_source)
                ok = await clone_album(group, status=status)
                await status.edit("✅ <b>انجام شد.</b>" if ok else "❌ محتوایی برای دریافت نبود.", parse_mode=ZHTML)
            jid = await enqueue_download(event.chat_id, status, "دریافت پیام ریپلای‌شده", reply_work)
            return True
        if social_match:
            url = social_match.group(0).rstrip(".,)")
            status = await event.edit(f"🌐 <i>در صف دریافت {esc(detect_platform(url).upper())}...</i>", parse_mode=ZHTML)
            async def social_work():
                await deliver_social(event, url, replace_msg=status)
                await send_full_song_for_link(event, url)
            await enqueue_download(event.chat_id, status, f"لینک {detect_platform(url).upper()}", social_work, dedupe_key=url.lower())
            return True
        if tg_match:
            url = tg_match.group(0).rstrip(".,)")
            status = await event.edit("🧲 <i>در صف دریافت تلگرام...</i>", parse_mode=ZHTML)
            async def telegram_work():
                n, err = await fetch_from_link(url, status)
                if n:
                    await status.edit(f"✅ <b>{n} پست دریافت شد</b> → <code>{esc(dump_target())}</code>", parse_mode=ZHTML)
                else:
                    await status.edit("⚠️ " + (err or "پستی دریافت نشد."), parse_mode=ZHTML)
            await enqueue_download(event.chat_id, status, "لینک تلگرام", telegram_work, dedupe_key=url.lower())
            return True
        if link and not social_match and not tg_match:
            if link.startswith("http"):
                await deliver_music(event, link.split()[0])
                return True
            await event.edit(f"در حال جستجو برای موزیک: {esc(link)}", parse_mode=ZHTML)
            results_m, err_m = await search_music_list(link)
            if not results_m:
                await event.edit(f"جستجو نتیجه‌ای نداد: {esc(err_m or '')}", parse_mode=ZHTML)
                return True
            MUSIC_SEARCHES[event.chat_id] = results_m
            lines_m = [f"{i + 1}. {esc(r['title'])} ({esc(r['duration'])})" for i, r in enumerate(results_m)]
            music_rows_m = [[str(i + 1), f"{pe('🎵')} {esc(r['title'])}", esc(r['duration'])] for i, r in enumerate(results_m)]
            music_plain_m = ["# | آهنگ | مدت", "----------------------------------------"] + [f"{i + 1} | {pe('🎵')} {esc(r['title'])} | {esc(r['duration'])}" for i, r in enumerate(results_m)] + ["برای دانلود کامل، .dl و شماره را بفرست. مثال: .dl 1"]
            music_rich_m = "<h2>نتایج جستجو موزیک</h2>" + chr(10) + rich_table(["#", "آهنگ", "مدت"], music_rows_m) + chr(10) + "برای دانلود کامل، .dl و شماره را بفرست. مثال: .dl 1"
            await deliver_inline_rich(event, "music", "نتایج جستجو موزیک", music_rich_m, music_plain_m)
            return True
        await event.edit(
            "🔗 لینک پشتیبانی‌شده پیدا نشد. لینک تلگرام/اینستا/یوتیوب/تیک‌تاک بده، یا روی یک پیام ریپلای کن.\n"
            f"مثال: <code>{p}fetch https://youtu.be/...</code>", parse_mode=ZHTML
        )
        return True

    if cmd == "find":
        if not arg:
            await event.edit(f"مثال: <code>{p}find اسم فایل</code>", parse_mode=ZHTML)
            return True
        status = await event.edit("🔎 <i>در صف جستجو...</i>", parse_mode=ZHTML)
        async def find_work():
            n = 0
            async for m in user_client.iter_messages(event.chat_id, search=arg, limit=15):
                if m.media and await clone_message(m, status=status):
                    n += 1
            await status.edit(f"✅ <b>{n} مدیا</b> با «{esc(arg)}» دریافت شد.", parse_mode=ZHTML)
        await enqueue_download(event.chat_id, status, f"جستجو: {arg[:45]}", find_work)
        return True

    if cmd == "id":
        if event.is_reply:
            r = await event.get_reply_message()
            await event.edit(f"🆔 <b>شناسه پیام:</b> <code>{r.id}</code>", parse_mode=ZHTML)
        else:
            await event.edit("برای دیدن شناسه پیام، روی پیام ریپلای کن.")
        return True

    if cmd == "join":
        info = parse_tg_link(arg) if arg else None
        if not info:
            await event.edit(f"مثال: <code>{p}join https://t.me/+AbCdEf</code>", parse_mode=ZHTML)
            return True
        ent, st = await join_chat_from_link(info)
        txt = {"joined": "✅ عضو شدی.", "already": "ℹ️ از قبل عضوی.",
               "request": "📨 درخواست عضویت فرستاده شد.", "notfound": "❌ چت پیدا نشد."}.get(st, f"❌ <code>{esc(st)}</code>")
        await event.edit(txt + (f" {esc(getattr(ent, 'title', '') or '')}" if ent else ""), parse_mode=ZHTML)
        return True

    if cmd in ("watch", "unwatch"):
        cid = event.chat_id
        wl = bk.setdefault("watch_chats", [])
        if cmd == "unwatch":
            if cid in wl:
                wl.remove(cid)
            db.save()
            await event.edit("🔕 رصد این چت خاموش شد.")
        else:
            if cid not in wl:
                wl.append(cid)
            db.save()
            await event.edit(f"👁 رصد روشن شد؛ پست‌های جدید این چت به <code>{esc(dump_target())}</code> میرن.", parse_mode=ZHTML)
        return True

    if cmd == "dest":
        bk["dump_chat"] = "me" if arg.strip().lower() in ("me", "saved", "") else event.chat_id
        db.save()
        await event.edit(f"📥 مقصد ذخیره: <code>{esc(dump_target())}</code>", parse_mode=ZHTML)
        return True

    if cmd == "quality":
        quality = arg.strip().lower()
        if quality not in ("360", "480", "720", "1080", "max"):
            await event.edit(f"کیفیت‌های مجاز: <code>{p}quality 360</code>، 480، 720، 1080 یا max", parse_mode=ZHTML)
        else:
            db.data["social_dl"]["quality"] = quality
            db.save()
            await event.edit(f"✅ کیفیت دانلود روی <b>{quality}</b> تنظیم شد.", parse_mode=ZHTML)
        return True

    if cmd == "setdl":
        parts = arg.split()
        if len(parts) < 2 or parts[0] not in ("ig", "yt", "tt", "other"):
            await event.edit(f"مثال: <code>{p}setdl ig @bot1 @bot2</code>", parse_mode=ZHTML)
            return True
        db.data["social_dl"]["bots"][parts[0]] = [b if b.startswith("@") else "@" + b for b in parts[1:]]
        db.save()
        await event.edit(f"✅ ربات‌های {parts[0]}: <code>{esc(' → '.join(db.data['social_dl']['bots'][parts[0]]))}</code>", parse_mode=ZHTML)
        return True

    # Premium Emoji Studio, keep old concise commands
    if cmd in ("emojiid", "eid"):
        if not event.is_reply:
            await event.edit("روی پیامی که ایموجی پریمیوم داره ریپلای کن.")
            return True
        found = extract_custom_emojis(await event.get_reply_message())
        if not found:
            await event.edit("ایموجی پریمیوم توی این پیام پیدا نشد.")
            return True
        lines = "\n".join(f'<tg-emoji emoji-id="{d}">{esc(c)}</tg-emoji> <code>{d}</code>' for c, d in found)
        await event.edit(f"💎 <b>شناسه ایموجی‌ها:</b>\n<blockquote expandable>{lines}</blockquote>", parse_mode=ZHTML)
        return True

    if cmd in ("setpe", "setui", "pepack"):
        if not event.is_reply:
            await event.edit("روی پیامی با ایموجی پریمیوم ریپلای کن.")
            return True
        found = extract_custom_emojis(await event.get_reply_message())
        if cmd == "pepack" and found:
            try:
                docs = await user_client(functions.messages.GetCustomEmojiDocumentsRequest(document_id=[found[0][1]]))
                sset = next(a.stickerset for a in docs[0].attributes if isinstance(a, types.DocumentAttributeCustomEmoji))
                pack = await user_client(functions.messages.GetStickerSetRequest(stickerset=sset, hash=0))
                found = [(next((a.alt for a in d.attributes if isinstance(a, types.DocumentAttributeCustomEmoji)), ""), d.id) for d in pack.documents]
            except Exception as e:
                await event.edit(f"❌ پک خوانده نشد: <code>{esc(e)}</code>", parse_mode=ZHTML)
                return True
        if not found:
            await event.edit("ایموجی پریمیوم پیدا نشد.")
            return True
        target = "ui_emoji" if cmd == "setui" else "emoji_map"
        store = db.data["premium"].setdefault(target, {})
        for ch, did in found:
            if ch:
                for variant in _emoji_variants(ch):
                    store[variant] = did
        db.save()
        await event.edit(f"✅ {len(found)} ایموجی ذخیره شد.", parse_mode=ZHTML)
        return True

    if cmd == "pe":
        if not arg:
            await event.edit(f"مثال: <code>{p}pe سلام 🔥</code>", parse_mode=ZHTML)
        else:
            await event.edit(arg, formatting_entities=premium_entities(arg))
        return True

    return False

@user_client.on(events.NewMessage(outgoing=True))
async def v3_outgoing_magic(event):
    """Auto premium-emoji replacement + auto social link download."""
    txt = event.raw_text or ""
    if not txt or txt.startswith(db.data["prefix"]) or txt.strip() in (".پنل", ".panel"):
        return
    try:
        sd = db.data["social_dl"]
        m = SOCIAL_URL_RE.fullmatch(txt.strip())
        if sd.get("auto_link") and m:
            status = await event.edit("🌐 <i>در حال دریافت ویدیو...</i>", parse_mode=ZHTML)
            await deliver_social(event, m.group(0), replace_msg=status)
            return
        prem = db.data["premium"]
        if prem.get("use_custom_emoji") and (ACCOUNT_PREMIUM or event.chat_id == OWNER_ID) \
                and db.data["text_style"]["mode"] == "none" and not db.data["animation"]["typing_effect"]:
            existing = list(event.message.entities or [])
            new = premium_entities(event.message.message, existing)
            if new:
                await event.edit(event.message.message, formatting_entities=existing + new, link_preview=False)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        logger.debug(f"v3 outgoing magic: {e}")


def _is_watched(e) -> bool:
    try:
        bk = db.data["backup"]
        return e.chat_id in bk.get("watch_chats", []) and e.chat_id != bk.get("dump_chat")
    except Exception:
        return False


@user_client.on(events.NewMessage(incoming=True, func=lambda e: _is_watched(e) and not e.grouped_id))
async def v3_watch_single(event):
    try:
        await clone_message(event.message)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 1)
    except Exception as e:
        logger.warning(f"Watch copy failed: {e}")


@user_client.on(events.Album(func=_is_watched))
async def v3_watch_album(event):
    try:
        await clone_album(list(event.messages))
    except Exception as e:
        logger.warning(f"Watch album failed: {e}")



# ==============================================================================
# 6. USERBOT OUTGOING COMMAND HANDLERS
# ==============================================================================

@user_client.on(events.NewMessage(outgoing=True))
async def outgoing_commands_handler(event: events.NewMessage.Event):
    raw_text = event.raw_text or ""
    p = db.data["prefix"]

    # 1. Open Glass Panel (.پنل or .panel)
    _panel_txt = raw_text.strip()
    if _panel_txt in (f"{p}پنل", f"{p}panel", ".پنل", ".panel") or (_panel_txt.startswith(p) and _panel_txt[len(p):].strip().lower() in ("panel", "پنل")):
        await event.delete()
        try:
            results = await user_client.inline_query(BOT_USERNAME, "panel")
            if results:
                await results[0].click(event.chat_id, reply_to=event.reply_to_msg_id)
        except Exception as e:
            await user_client.send_message(
                event.chat_id,
                f"⚠️ <b>خطا در باز کردن پنل شیشه‌ای:</b>\n<code>{esc(e)}</code>\n\n"
                "💡 <i>مطمئن شوید در @BotFather دستور <code>/setinline</code> را برای ربات کمکی فعال کرده‌اید.</i>",
                parse_mode=ZHTML
            )
        return

    # 2. Outgoing Prefix Commands
    if raw_text.startswith(p):
        cmd_body = raw_text[len(p):].strip()
        parts = cmd_body.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if await ketaself_v3_commands(event, cmd, arg):
            return

        # --- PING & STATUS ---
        if cmd in ("ping", "پینگ"):
            t0 = time.perf_counter()
            await event.edit("⚡ <i>در حال سنجش سرعت...</i>", parse_mode=ZHTML)
            dt = (time.perf_counter() - t0) * 1000
            await event.edit(
                "🪐 <b>KetaSelf Ultra v4.2</b>\n"
                "<blockquote>"
                f"⚡ <b>پینگ سرور:</b> <code>{dt:.1f} ms</code>\n"
                f"⏱ <b>آپتایم:</b> <code>{get_uptime()}</code>\n"
                f"📅 <b>تاریخ:</b> <code>{get_jalali_date()}</code>"
                "</blockquote>",
                parse_mode=ZHTML
            )
            return

        # --- SAVE TIMED MEDIA OR RESTRICTED CONTENT (.save / .dl) ---
        if cmd in ("save", "dl", "سیو", "دانلود"):
            if arg.startswith("http"):
                await event.edit("🧲 <i>در حال دریافت محتوا از لینک...</i>", parse_mode=ZHTML)
                ok = await download_from_telegram_link(arg)
                if ok:
                    await event.edit("✅ <b>محتوا با موفقیت در Saved Messages ذخیره شد!</b>", parse_mode=ZHTML)
                else:
                    await event.edit("❌ <b>خطا در دریافت لینک یا عدم دسترسی به کانال.</b>", parse_mode=ZHTML)
                return

            if not event.is_reply:
                await event.edit("❌ لطفاً روی یک پیام/مدیا ریپلای کنید یا لینک پست را جلوی دستور بنویسید.")
                return
            reply_msg = await event.get_reply_message()
            await event.delete()
            await save_media_to_saved_messages(reply_msg, reason="ذخیره دستی (سیو زماندار / ضد قفل)")
            return

        # --- USER PROFILER & SCAM CHECKER (.check / .whois / .saveuser / .id) ---
        if cmd in ("check", "whois", "saveuser", "id", "آیدی"):
            target_id = event.chat_id
            if event.is_reply:
                reply = await event.get_reply_message()
                target_id = reply.sender_id
            elif arg:
                target_id = int(arg) if arg.lstrip("-").isdigit() else arg

            try:
                entity = await user_client.get_entity(target_id)
                full_bio = "ندارد"
                common_chats = 0
                try:
                    full = await user_client(GetFullUserRequest(entity.id))
                    full_bio = full.full_user.about or "ندارد"
                    common_chats = full.full_user.common_chats_count
                except Exception:
                    pass

                is_scam = getattr(entity, "scam", False)
                is_fake = getattr(entity, "fake", False)
                is_premium = getattr(entity, "premium", False)
                is_bot = getattr(entity, "bot", False)
                first_name = getattr(entity, "first_name", "") or getattr(entity, "title", "بدون نام")
                last_name = getattr(entity, "last_name", "") or ""
                full_name = f"{first_name} {last_name}".strip()
                username = f"@{entity.username}" if getattr(entity, "username", None) else "ندارد"
                dc_id = getattr(getattr(entity, "photo", None), "dc_id", "نامشخص")

                info_html = (
                    "🔍 <b>شناسنامه و استعلام امنیتی کاربر</b>\n"
                    "<blockquote>"
                    f"👤 <b>نام کامل:</b> <code>{esc(full_name)}</code>\n"
                    f"🆔 <b>آیدی عددی:</b> <code>{entity.id}</code>\n"
                    f"🔗 <b>یوزرنیم:</b> {esc(username)}\n"
                    f"💎 <b>پریمیوم:</b> <code>{'بله ✨' if is_premium else 'خیر'}</code> | <b>ربات:</b> <code>{'بله' if is_bot else 'خیر'}</code>\n"
                    f"🌐 <b>دیتاسنتر (DC):</b> <code>{dc_id}</code> | <b>گروه‌های مشترک:</b> <code>{common_chats}</code>\n"
                    f"🚨 <b>برچسب Scam:</b> <code>{'⚠️ بله (خطرناک!)' if is_scam else '✅ سفید'}</code>\n"
                    f"⚠️ <b>برچسب Fake:</b> <code>{'⚠️ بله' if is_fake else '✅ سفید'}</code>"
                    "</blockquote>\n"
                    f"📝 <b>بیوگرافی:</b> <code>{esc(full_bio)}</code>"
                )
                await event.edit(info_html, parse_mode=ZHTML)
                if cmd == "saveuser" or is_scam or is_fake:
                    await user_client.send_message("me", info_html, parse_mode=ZHTML)
            except Exception as e:
                await event.edit(f"❌ خطا در استعلام کاربر: <code>{esc(e)}</code>", parse_mode=ZHTML)
            return

        # --- CLONE PROFILE (.clone) ---
        if cmd == "clone" and event.is_reply:
            reply = await event.get_reply_message()
            target = await reply.get_sender()
            if target:
                fname = getattr(target, "first_name", "") or "User"
                lname = getattr(target, "last_name", "") or ""
                bio = ""
                try:
                    full = await user_client(GetFullUserRequest(target.id))
                    bio = (full.full_user.about or "")[:70]
                except Exception:
                    pass
                await user_client(UpdateProfileRequest(first_name=fname, last_name=lname, about=bio))
                db.data["profile"]["base_name"] = fname
                db.data["profile"]["base_bio"] = bio
                db.save()
                await event.edit(f"✅ <b>پروفایل با موفقیت از روی <code>{esc(fname)}</code> کپی شد!</b>", parse_mode=ZHTML)
            return

        # --- PROFILE & SECRETARY SETTINGS ---
        if cmd == "setname" and arg:
            db.data["profile"]["base_name"] = arg
            db.save()
            await user_client(UpdateProfileRequest(first_name=arg))
            await event.edit(f"✅ نام پایه روی <code>{esc(arg)}</code> تنظیم شد.", parse_mode=ZHTML)
            return

        if cmd == "setbio" and arg:
            db.data["profile"]["base_bio"] = arg[:70]
            db.save()
            await user_client(UpdateProfileRequest(about=arg[:70]))
            await event.edit(f"✅ بیو پایه روی <code>{esc(arg[:70])}</code> تنظیم شد.", parse_mode=ZHTML)
            return

        if cmd == "addbio" and arg:
            db.data["profile"]["bios_list"].append(arg[:60])
            db.save()
            await event.edit(f"✅ بیو جدید به لیست چرخشی اضافه شد (تعداد: <code>{len(db.data['profile']['bios_list'])}</code>).", parse_mode=ZHTML)
            return

        if cmd == "clearbios":
            db.data["profile"]["bios_list"].clear()
            db.save()
            await event.edit("🧹 لیست بیوهای چرخشی پاکسازی شد.")
            return

        if cmd == "setreply" and arg:
            db.data["secretary"]["text"] = arg
            db.save()
            await event.edit(f"✅ متن منشی خودکار بروزرسانی شد:\n<blockquote>{esc(arg)}</blockquote>", parse_mode=ZHTML)
            return

        if cmd == "setreact" and arg:
            db.data["premium"]["react_emoji"] = arg.strip()
            db.save()
            await event.edit(f"✅ ایموجی ری‌اکشن خودکار روی {esc(arg.strip())} تنظیم شد.", parse_mode=ZHTML)
            return

        # --- ENEMY & FRIEND MANAGEMENT ---
        if cmd in ("addenemy", "delenemy", "addfriend", "delfriend"):
            target_id = event.chat_id
            if event.is_reply:
                r = await event.get_reply_message()
                target_id = r.sender_id
            elif arg.isdigit():
                target_id = int(arg)

            enemies = db.data["fun_social"]["enemies"]
            friends = db.data["fun_social"]["friends"]

            if cmd == "addenemy":
                if target_id not in enemies:
                    enemies.append(target_id)
                await event.edit(f"💀 کاربر <code>{target_id}</code> به لیست دشمنان اضافه شد!", parse_mode=ZHTML)
            elif cmd == "delenemy":
                if target_id in enemies:
                    enemies.remove(target_id)
                await event.edit(f"✅ کاربر <code>{target_id}</code> از لیست دشمنان خارج شد.", parse_mode=ZHTML)
            elif cmd == "addfriend":
                if target_id not in friends:
                    friends.append(target_id)
                await event.edit(f"💖 کاربر <code>{target_id}</code> به لیست دوستان ویژه اضافه شد!", parse_mode=ZHTML)
            elif cmd == "delfriend":
                if target_id in friends:
                    friends.remove(target_id)
                await event.edit(f"✅ کاربر <code>{target_id}</code> از لیست دوستان حذف شد.", parse_mode=ZHTML)
            db.save()
            return

        # --- SECURITY COMMANDS (.wl / .mute / .unmute / .block / .unblock) ---
        if cmd in ("wl", "mute", "unmute", "block", "unblock"):
            target_id = event.chat_id
            if event.is_reply:
                r = await event.get_reply_message()
                target_id = r.sender_id

            if cmd == "wl":
                if target_id not in db.data["security"]["whitelist"]:
                    db.data["security"]["whitelist"].append(target_id)
                    db.save()
                await event.edit(f"✅ کاربر <code>{target_id}</code> به لیست سفید پی‌وی اضافه شد.", parse_mode=ZHTML)
            elif cmd == "mute":
                if target_id not in db.data["security"]["muted_users"]:
                    db.data["security"]["muted_users"].append(target_id)
                    db.save()
                await event.edit(f"🔇 کاربر <code>{target_id}</code> در حالت سکوت (حذف خودکار پیام) قرار گرفت.", parse_mode=ZHTML)
            elif cmd == "unmute":
                if target_id in db.data["security"]["muted_users"]:
                    db.data["security"]["muted_users"].remove(target_id)
                    db.save()
                await event.edit(f"🔊 کاربر <code>{target_id}</code> از حالت سکوت خارج شد.", parse_mode=ZHTML)
            elif cmd == "block":
                await user_client(functions.contacts.BlockRequest(id=target_id))
                await event.edit(f"🚫 کاربر <code>{target_id}</code> مسدود شد.", parse_mode=ZHTML)
            elif cmd == "unblock":
                await user_client(functions.contacts.UnblockRequest(id=target_id))
                await event.edit(f"✅ کاربر <code>{target_id}</code> رفع مسدودیت شد.", parse_mode=ZHTML)
            return

        # --- AUTO MESSAGE TARGETS ---
        if cmd == "addauto":
            if event.chat_id not in db.data["auto_msg"]["targets"]:
                db.data["auto_msg"]["targets"].append(event.chat_id)
                db.save()
            await event.edit("✅ این چت به لیست ارسال پیام خودکار اضافه شد.")
            return

        if cmd == "delauto":
            if event.chat_id in db.data["auto_msg"]["targets"]:
                db.data["auto_msg"]["targets"].remove(event.chat_id)
                db.save()
            await event.edit("🗑 این چت از لیست ارسال پیام خودکار حذف شد.")
            return

        if cmd == "setautotext" and arg:
            db.data["auto_msg"]["text"] = arg
            db.save()
            await event.edit(f"✅ متن پیام خودکار تنظیم شد:\n<blockquote>{esc(arg)}</blockquote>", parse_mode=ZHTML)
            return

        # --- SMART TOOLS: CALCULATOR, KEYBOARD FIXER, TRANSLATOR ---
        if cmd == "calc" and arg:
            try:
                res = safe_math_eval(arg)
                await event.edit(f"🧮 <b>محاسبه:</b>\n<code>{esc(arg)} = {res}</code>", parse_mode=ZHTML)
            except Exception as e:
                await event.edit(f"❌ خطا در فرمول: <code>{esc(e)}</code>", parse_mode=ZHTML)
            return

        if cmd == "fa" and event.is_reply:
            r = await event.get_reply_message()
            fixed = (r.raw_text or "").translate(PERSIAN_KEYBOARD_LAYOUT)
            await event.edit(f"⌨️ <b>اصلاح کیبورد فارسی:</b>\n<blockquote>{esc(fixed)}</blockquote>", parse_mode=ZHTML)
            return

        if cmd == "tr" and event.is_reply:
            target_lang = arg if arg else "fa"
            r = await event.get_reply_message()
            q_text = r.raw_text or ""
            if not q_text:
                await event.edit("❌ متنی برای ترجمه یافت نشد.")
                return
            await event.edit("🌐 <i>در حال ترجمه...</i>", parse_mode=ZHTML)
            try:
                import urllib.parse
                import urllib.request
                url = (
                    "https://translate.googleapis.com/translate_a/single?client=gtx"
                    f"&sl=auto&tl={urllib.parse.quote(target_lang)}&dt=t&q={urllib.parse.quote(q_text)}"
                )
                loop = asyncio.get_event_loop()
                def _fetch():
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                data = await loop.run_in_executor(None, _fetch)
                translated = "".join(part[0] for part in data[0] if part[0])
                await event.edit(
                    f"🌐 <b>ترجمه به ({esc(target_lang)}):</b>\n"
                    f"<blockquote>{esc(translated)}</blockquote>",
                    parse_mode=ZHTML
                )
            except Exception as e:
                await event.edit(f"❌ خطا در ترجمه: <code>{esc(e)}</code>", parse_mode=ZHTML)
            return

        # --- DELETE, PURGE, SPAM, TAGALL ---
        if cmd == "del":
            if event.is_reply:
                r = await event.get_reply_message()
                await r.delete()
            await event.delete()
            return

        if cmd == "purge":
            count = int(arg) if arg.isdigit() else 15
            msgs = []
            async for m in user_client.iter_messages(event.chat_id, limit=min(count + 1, 200)):
                msgs.append(m.id)
            await user_client.delete_messages(event.chat_id, msgs)
            return

        if cmd == "purgeme":
            count = int(arg) if arg.isdigit() else 15
            msgs = []
            async for m in user_client.iter_messages(event.chat_id, from_user="me", limit=min(count + 1, 200)):
                msgs.append(m.id)
            await user_client.delete_messages(event.chat_id, msgs)
            return

        if cmd == "spam" and arg:
            sp = arg.split(maxsplit=1)
            if len(sp) == 2 and sp[0].isdigit():
                count = min(int(sp[0]), 50)
                text_to_send = sp[1]
                await event.delete()
                for _ in range(count):
                    await user_client.send_message(event.chat_id, text_to_send)
                    await asyncio.sleep(0.25)
            return

        if cmd == "tagall":
            note = arg or "📢 توجه کنید:"
            mentions = []
            async for user in user_client.iter_participants(event.chat_id, limit=40):
                if not user.bot and not user.deleted:
                    name = esc(user.first_name or "کاربر")
                    mentions.append(f"<a href='tg://user?id={user.id}'>{name}</a>")
            if mentions:
                chunk = " ، ".join(mentions)
                await event.edit(f"{esc(note)}\n\n{chunk}", parse_mode=ZHTML)
            return

        # --- ANIMATIONS (.type, .heart, .load, .dice, .dart) ---
        if cmd == "type" and arg:
            built = ""
            for ch in arg:
                built += ch
                if ch.strip():
                    await event.edit(f"<code>{esc(built)}▒</code>", parse_mode=ZHTML)
                    await asyncio.sleep(0.07)
            await event.edit(f"<b>{esc(built)}</b>", parse_mode=ZHTML)
            return

        if cmd == "heart":
            frames = ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "💖", "💝"]
            for f in frames:
                await event.edit(f"✨ {f} ✨")
                await asyncio.sleep(0.25)
            return

        if cmd == "load":
            for i in range(1, 11):
                bar = "█" * i + "░" * (10 - i)
                await event.edit(f"⏳ <b>Loading:</b> <code>[{bar}] {i * 10}%</code>", parse_mode=ZHTML)
                await asyncio.sleep(0.25)
            await event.edit("✅ <b>Completed 100%!</b>", parse_mode=ZHTML)
            return

        if cmd in ("dice", "dart"):
            emoticon = "🎲" if cmd == "dice" else "🎯"
            await event.delete()
            await user_client.send_file(event.chat_id, types.InputMediaDice(emoticon=emoticon))
            return

    # 3. Automatic Outgoing Text Styling / Typing Animation (for normal messages)
    if not raw_text.startswith(p) and raw_text and not event.media:
        if db.data["animation"]["typing_effect"] and len(raw_text) <= 55:
            built = ""
            for ch in raw_text:
                built += ch
                if ch.strip():
                    try:
                        await event.edit(f"{built}▏")
                        await asyncio.sleep(db.data["animation"].get("effect_speed", 0.05))
                    except Exception:
                        break
            try:
                await event.edit(raw_text)
            except Exception:
                pass

        style = db.data["text_style"]["mode"]
        if style != "none":
            try:
                if style == "bold":
                    await event.edit(f"<b>{esc(raw_text)}</b>", parse_mode=ZHTML)
                elif style == "mono":
                    await event.edit(f"<code>{esc(raw_text)}</code>", parse_mode=ZHTML)
                elif style == "italic":
                    await event.edit(f"<i>{esc(raw_text)}</i>", parse_mode=ZHTML)
                elif style == "spoiler":
                    await event.edit(f"<tg-spoiler>{esc(raw_text)}</tg-spoiler>", parse_mode=ZHTML)
                elif style == "strike":
                    await event.edit(f"<s>{esc(raw_text)}</s>", parse_mode=ZHTML)
                elif style == "quote":
                    await event.edit(f"<blockquote>{esc(raw_text)}</blockquote>", parse_mode=ZHTML)
                elif style == "fancy":
                    await event.edit(raw_text.translate(EN_FANCY_MAP))
            except Exception:
                pass


# ==============================================================================
# 7. INCOMING HANDLERS: TIMED MEDIA, ANTI-SCAM, ENEMY/FRIEND, SECRETARY
# ==============================================================================

@user_client.on(events.NewMessage(incoming=True))
async def incoming_message_handler(event: events.NewMessage.Event):
    sender = await event.get_sender()
    sender_id = event.sender_id
    sender_name = getattr(sender, "first_name", "") or getattr(sender, "title", "کاربر")
    is_bot = getattr(sender, "bot", False)

    # 1. Cache messages for Anti-Delete & Anti-Edit
    if event.is_private or (event.is_group and db.data["backup"]["anti_delete_groups"]):
        media_Backup_path = None
        # Pre-cache small private media if Anti-Delete PV is enabled
        if event.is_private and db.data["backup"]["anti_delete_pv"] and event.media:
            file_size = getattr(getattr(event.media, "document", None), "size", 0) or 0
            if file_size < 15 * 1024 * 1024:  # Under 15MB
                try:
                    media_Backup_path = await user_client.download_media(event.message, file=DOWNLOAD_DIR)
                except Exception:
                    media_Backup_path = None

        MESSAGE_CACHE[(event.chat_id, event.id)] = {
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": event.raw_text or "[مدیا / فایل]",
            "media_path": media_Backup_path,
            "time": datetime.now().strftime("%H:%M:%S"),
            "is_private": event.is_private
        }
        if len(MESSAGE_CACHE) > 1500:
            oldest_key = next(iter(MESSAGE_CACHE))
            old_item = MESSAGE_CACHE.pop(oldest_key, None)
            if old_item and old_item.get("media_path") and os.path.exists(old_item["media_path"]):
                try:
                    os.remove(old_item["media_path"])
                except OSError:
                    pass

    # 2. Muted User Auto-Delete
    if sender_id in db.data["security"]["muted_users"]:
        try:
            await event.delete()
        except Exception:
            pass
        return

    # 3. Enemy Auto-Roast & Friend Auto-Reaction (works in PV & Groups)
    if sender_id in db.data["fun_social"]["enemies"] and db.data["fun_social"]["enemy_mode"]:
        replies = db.data["fun_social"]["enemy_replies"]
        if replies:
            chosen = replies[int(time.time()) % len(replies)]
            try:
                await event.reply(chosen)
            except Exception:
                pass

    if sender_id in db.data["fun_social"]["friends"]:
        try:
            await user_client(SendReactionRequest(
                peer=event.chat_id,
                msg_id=event.id,
                reaction=[types.ReactionEmoji(emoticon=db.data["fun_social"]["friend_emoji"])]
            ))
        except Exception:
            pass

    # 4. Private Chat Specific Modules
    if event.is_private:
        # 4a. Auto-Save View-Once / Timed Media
        if db.data["backup"]["save_timed_media"] and is_timed_or_view_once_media(event.message):
            await save_media_to_saved_messages(event.message, reason="سیو خودکار مدیا زماندار (یک‌بار مصرف)")

        # 4b. Anti-Scam & Suspicious Account Detector
        if db.data["security"]["anti_scam_save"] and sender:
            is_scam = getattr(sender, "scam", False)
            is_fake = getattr(sender, "fake", False)
            if is_scam or is_fake:
                warn_html = (
                    "🚨 <b>هشدار رادار امنیتی: پیام از اکانت اسکم / فیک!</b>\n"
                    "<blockquote>"
                    f"👤 <b>نام:</b> <code>{esc(sender_name)}</code>\n"
                    f"🆔 <b>آیدی عددی:</b> <code>{sender_id}</code>\n"
                    f"💬 <b>متن پیام:</b> <code>{esc(event.raw_text or '[مدیا]')}</code>\n"
                    f"📅 <b>زمان:</b> <code>{get_jalali_date()} - {datetime.now().strftime('%H:%M:%S')}</code>"
                    "</blockquote>"
                )
                await user_client.send_message("me", warn_html, parse_mode=ZHTML)

        # 4c. Anti-Spam Flood Protection in PV
        if db.data["security"]["anti_spam_pv"] and not is_bot and sender_id not in db.data["security"]["whitelist"] and sender_id != OWNER_ID:
            now_t = time.time()
            history = [t for t in SPAM_TRACKER.get(sender_id, []) if now_t - t < 10]
            history.append(now_t)
            SPAM_TRACKER[sender_id] = history
            if len(history) >= db.data["security"].get("spam_limit", 8):
                db.data["security"]["muted_users"].append(sender_id)
                db.save()
                await event.reply("🛡 <b>به دلیل ارسال پیام رگباری (اسپم)، به صورت خودکار سکوت شدید.</b>", parse_mode=ZHTML)
                await user_client.send_message(
                    "me",
                    f"🛡 کاربر <code>{esc(sender_name)}</code> (<code>{sender_id}</code>) به دلیل اسپم در پی‌وی خودکار Mute شد.",
                    parse_mode=ZHTML
                )
                return

        # 4d. PV Lock
        if db.data["security"]["pv_lock"]:
            if sender_id not in db.data["security"]["whitelist"] and not is_bot:
                await event.delete()
                return

        # 4e. Smart Secretary (منشی خودکار)
        if db.data["secretary"]["enabled"] and sender and not is_bot:
            now = time.time()
            last_sent = SECRETARY_MEMORY.get(sender_id, 0)
            if now - last_sent >= db.data["secretary"]["cooldown_sec"]:
                SECRETARY_MEMORY[sender_id] = now
                await event.reply(db.data["secretary"]["text"])

        # 4f. Auto Reaction in PV
        if db.data["premium"]["auto_react_pv"] and not is_bot:
            try:
                await user_client(SendReactionRequest(
                    peer=event.chat_id,
                    msg_id=event.id,
                    reaction=[types.ReactionEmoji(emoticon=db.data["premium"]["react_emoji"])]
                ))
            except Exception:
                pass


NOTIFY_CHANNEL_ID = -1004319876616  # Anti-Delete / Anti-Edit logs go here, not Saved Messages

@user_client.on(events.MessageDeleted)
async def message_deleted_handler(event: events.MessageDeleted.Event):
    for msg_id in event.deleted_ids:
        for (chat_id, cached_msg_id), info in list(MESSAGE_CACHE.items()):
            if cached_msg_id == msg_id:
                if info["is_private"] and not db.data["backup"]["anti_delete_pv"]:
                    continue
                if not info["is_private"] and not db.data["backup"]["anti_delete_groups"]:
                    continue

                log_html = (
                    "🗑 <b>گزارش حذف پیام (Anti-Delete)</b>\n"
                    "<blockquote>"
                    f"👤 <b>فرستنده:</b> <a href='tg://user?id={info['sender_id']}'>{esc(info['sender_name'])}</a> (<code>{info['sender_id']}</code>)\n"
                    f"⏰ <b>ساعت ارسال:</b> <code>{info['time']}</code>\n"
                    f"📝 <b>محتوای حذف‌شده:</b>\n<code>{esc(info['text'])}</code>"
                    "</blockquote>"
                )
                media_path = info.get("media_path")
                if media_path and os.path.exists(media_path):
                    await user_client.send_file(NOTIFY_CHANNEL_ID, media_path, caption=log_html, parse_mode=ZHTML)
                    try:
                        os.remove(media_path)
                    except OSError:
                        pass
                else:
                    await user_client.send_message(NOTIFY_CHANNEL_ID, log_html, parse_mode=ZHTML)

                MESSAGE_CACHE.pop((chat_id, cached_msg_id), None)


@user_client.on(events.MessageEdited(incoming=True))
async def message_edited_handler(event: events.MessageEdited.Event):
    if not event.is_private or not db.data["backup"]["anti_edit_pv"]:
        return
    old_info = MESSAGE_CACHE.get((event.chat_id, event.id))
    new_text = event.raw_text or ""
    if old_info and old_info["text"] != new_text:
        log_html = (
            "✏️ <b>گزارش ویرایش پیام (Anti-Edit)</b>\n"
            "<blockquote>"
            f"👤 <b>فرستنده:</b> <a href='tg://user?id={old_info['sender_id']}'>{esc(old_info['sender_name'])}</a>\n"
            f"🔴 <b>متن قبلی:</b> <code>{esc(old_info['text'])}</code>\n"
            f"🟢 <b>متن جدید:</b> <code>{esc(new_text)}</code>"
            "</blockquote>"
        )
        await user_client.send_message(NOTIFY_CHANNEL_ID, log_html, parse_mode=ZHTML)
        old_info["text"] = new_text


# ==============================================================================
# 8. RESILIENT BACKGROUND LOOPS (CLOCK, BIO ROTATOR, FAKE ACTION, AUTO-MSG)
# ==============================================================================

async def profile_clock_loop():
    """Updates user profile name and bio every minute with full FloodWait protection."""
    last_minute = ""
    bio_index = 0
    while True:
        try:
            now_min = datetime.now().strftime("%H:%M")
            prof = db.data["profile"]

            if now_min != last_minute:
                last_minute = now_min
                t_str = format_clock()

                if prof["time_name"] or prof["time_bio"]:
                    kwargs = {}
                    if prof["time_name"]:
                        base_n = prof["base_name"] or "User"
                        kwargs["first_name"] = f"{base_n} | {t_str}"
                    if prof["time_bio"]:
                        bios = prof.get("bios_list") or []
                        if bios:
                            chosen_bio = bios[bio_index % len(bios)]
                            bio_index += 1
                        else:
                            chosen_bio = prof["base_bio"] or ""
                        full_bio = f"{chosen_bio} | ⏰ {t_str}".strip(" |")
                        kwargs["about"] = full_bio[:70]

                    await user_client(UpdateProfileRequest(**kwargs))

            if prof["online_mode"]:
                await user_client(UpdateStatusRequest(offline=False))

        except FloodWaitError as fw:
            logger.warning(f"FloodWait in profile loop: sleeping {fw.seconds}s")
            await asyncio.sleep(fw.seconds + 5)
        except Exception as e:
            logger.warning(f"Profile loop warning: {e}")

        await asyncio.sleep(20)


async def auto_message_loop():
    """Periodically sends scheduled messages to target chats with FloodWait handling."""
    while True:
        try:
            am = db.data["auto_msg"]
            if am["enabled"] and am["targets"] and am["text"]:
                for chat_id in list(am["targets"]):
                    try:
                        await user_client.send_message(chat_id, am["text"])
                        await asyncio.sleep(1.5)
                    except FloodWaitError as fw:
                        await asyncio.sleep(fw.seconds + 2)
                    except Exception as e:
                        logger.warning(f"Auto-msg error for {chat_id}: {e}")
                await asyncio.sleep(max(am["interval_min"], 1) * 60)
            else:
                await asyncio.sleep(15)
        except Exception as e:
            logger.warning(f"Auto message loop warning: {e}")
            await asyncio.sleep(30)


# ==============================================================================
# 9. MAIN ENTRYPOINT
# ==============================================================================

async def main():
    global OWNER_ID, BOT_USERNAME, ACCOUNT_PREMIUM

    print("====================================================")
    print("   🪐 Starting KetaSelf Ultra v4.2 (Telegram 2026)  ")
    print("====================================================")

    await user_client.start()
    me = await user_client.get_me()
    OWNER_ID = me.id
    ACCOUNT_PREMIUM = bool(getattr(me, "premium", False))
    try:
        await asyncio.wait_for(user_client.get_dialogs(limit=100), timeout=60)  # warm entity cache for t.me/c/ links
    except Exception as e:
        logger.warning(f"Dialog warm-up skipped: {e}")

    if not db.data["profile"]["base_name"]:
        db.data["profile"]["base_name"] = me.first_name or "User"
        db.save()

    await bot_client.start(bot_token=BOT_TOKEN)
    bot_me = await bot_client.get_me()
    BOT_USERNAME = bot_me.username

    logger.info(f"✅ UserClient Active: {me.first_name} (ID: {OWNER_ID})")
    logger.info(f"✅ HelperBot Active:  @{BOT_USERNAME}")
    logger.info(f"💡 Commands: {db.data['prefix']}help · {db.data['prefix']}fetch · {db.data['prefix']}queue · {db.data['prefix']}panel")

    asyncio.create_task(profile_clock_loop())
    asyncio.create_task(auto_message_loop())

    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 KetaSelf Ultra stopped cleanly.")