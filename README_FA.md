# کتا سلف — KetaSelf

سلف‌بات تلگرام با پنل اینلاین: دانلود از کانال‌های قفل‌شده، ذخیره‌ی مدیای
تایم‌دار و پیام‌های حذف‌شده، منشی خودکار، ساعت پروفایل، دانلود موزیک و
ویدیو، چت با هوش مصنوعی (`.ai`) و تبدیل متن به صدا (`.tts`).

**توجه:** سلف‌بات یعنی ورود با اکانت کاربری تلگرام (نه بات). این کار خلاف
قوانین تلگرام است و ممکن است اکانتت محدود یا بسته شود. با اکانت اصلی و
مهم خودت استفاده نکن؛ مسئولیتش با خودت است.

## چی لازم داری (همه مال خودت)

| چیز | از کجا |
|---|---|
| اکانت تلگرام | اکانت خودت |
| `API_ID` و `API_HASH` | https://my.telegram.org (وارد شو، Apps بساز) |
| بات کمکی + `BOT_TOKEN` | از @BotFather بساز و Inline Mode را فعال کن (`/setinline`) |
| کلیدهای Gemini | https://aistudio.google.com — حداقل ۱، حداکثر ۳۰ کلید (`.ai` و `.tts` هر دو از همین استخر می‌خوانند) |
| (اختیاری) توکن Apify | برای `.ai` و ابزار قیمت |

## مرحله ۱ — ساختن سشن (روی کامپیوتر خودت)

```bash
cp .env.example .env
# داخل .env مقدار API_ID ،API_HASH و BOT_TOKEN را پر کن
pip install -r requirements.txt
python3 setup_session.py
```

اسکریپت با شماره موبایل + کد تاییدی که تلگرام می‌فرستد وارد می‌شود و دو
رشته چاپ می‌کند: `SESSION_STRING` (اکانت کاربری) و `HELPER_SESSION_STRING`
(بات کمکی). این دو رشته را در متغیرهای محیطی هاست بگذار.

**هشدار: رشته‌ی سشن معادل رمز عبور اکانت تلگرام توست. هرگز آن را با کسی
به اشتراک نگذار، در چت نفرست و در گیت کامیت نکن. هر کس آن را داشته باشد
به اکانتت دسترسی کامل دارد.**

## مرحله ۲ — دیپلوی

### (الف) Railway — یک کلیک

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/achhlhzadh9-ctrl/Telegram-selfbot&envs=API_ID%2CAPI_HASH%2CBOT_TOKEN%2CGEMINI_API_KEYS%2CSESSION_STRING%2CHELPER_SESSION_STRING)

> اگر ریپو اسم دیگری دارد، در لینک بالا `achhlhzadh9-ctrl/Telegram-selfbot` را با همان
> `owner/repo` عوض کن.

بعد از ساخت پروژه:

1. متغیرها را پر کن: `API_ID` ،`API_HASH` ،`BOT_TOKEN` ،`GEMINI_API_KEYS`
   (کلیدها با کاما جدا) ،`SESSION_STRING` ،`HELPER_SESSION_STRING` و
   `DATA_DIR=/data`. بقیه‌ی متغیرها اختیاری‌اند (لیست کامل در `.env.example`).
2. یک Volume بساز و روی `/data` مانت کن (سشن و کانفیگ روی آن می‌ماند؛
   بدون Volume با هر دیپلوی پاک می‌شود). سرویس → Variables یا
   Settings → Volumes → New Volume → Mount Path: `/data`.
3. سرویس دیپلوی می‌شود. اگر اولین دیپلوی CRASHED شد، معمولاً یعنی یکی از
   متغیرهای الزامی خالی است — لاگ را بخوان و متغیر را کامل کن.

راه دستی (بدون دکمه): در Railway روی New Project → Deploy from GitHub repo
→ همین ریپو را انتخاب کن، بعد متغیرها و Volume را مثل بالا ست کن.

### (ب) Docker

```bash
docker build -t ketaself .
docker run -d --name ketaself --restart unless-stopped \
  -v ketaself-data:/data \
  -e API_ID=... -e API_HASH=... -e BOT_TOKEN=... \
  -e GEMINI_API_KEYS=... \
  -e SESSION_STRING=... -e HELPER_SESSION_STRING=... \
  -e DATA_DIR=/data \
  ketaself
```

### (ج) اجرای لوکال

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # و پرش کن
python3 ketaself.py
```

برای اجرای لوکال `SESSION_STRING` لازم نیست؛ اگر خالی باشد، سشن در فایل
محلی (`ketaself_user.session` و `ketaself_helper.session`) ذخیره می‌شود.
اولین اجرا شماره موبایل و کد تایید می‌خواهد.

## دستورهای اصلی

| دستور | کار |
|---|---|
| `.help` | راهنمای کامل |
| `.panel` | پنل اینلاین (از طریق بات کمکی) |
| `.ai <متن>` | چت با Gemini (مدل `gemini-3.8-flash`) |
| `.tts <متن>` | تبدیل متن به صدا (مدل `gemini-3.8-flash-tts`) |
| `.dl <لینک>` | دانلود از کانال قفل‌شده / خصوصی |
| `.fetch <لینک>` | دانلود مستقیم اینستا/یوتیوب/تیک‌تاک |

پیشوند دستورها پیش‌فرض `.` است و از پنل قابل تغییر است.

## متغیرها

لیست کامل با توضیح در [`.env.example`](.env.example) است. مهم‌ترین‌ها:

| متغیر | الزامی؟ | توضیح |
|---|---|---|
| `API_ID` ،`API_HASH` | بله | از my.telegram.org |
| `BOT_TOKEN` | بله | از @BotFather |
| `GEMINI_API_KEYS` | بله (برای `.ai` / `.tts`) | ۱ تا ۳۰ کلید، با کاما جدا |
| `SESSION_STRING` ،`HELPER_SESSION_STRING` | روی هاست: بله | خروجی `setup_session.py` |
| `DATA_DIR` | روی Railway: بله (`/data`) | محل سشن و کانفیگ |
| `MAKER_NAME` ،`MAKER_GITHUB_URL` | خیر | نام و لینک «ساخته شده توسط» در `/start` |
| `TTS_COPY_CHAT_ID` | خیر | آیدی چتی که خروجی `.tts` در آن هم کپی شود؛ خالی = غیرفعال |
| `TELEGRAM_PROXY_HOST` / `TELEGRAM_PROXY_PORT` | خیر | پروکسی SOCKS5 برای MTProto؛ خالی = مستقیم |
| `HTTP_PROXY_URL` | خیر | پروکسی SOCKS5 برای yt-dlp و تماس‌های HTTP؛ خالی = مستقیم |
| `APIFY_TOKEN` | خیر | برای `.ai` و ابزار قیمت |

## عیب‌یابی

- **بات بالا نمی‌آید / فوری CRASHED می‌شود:** متغیرهای الزامی را چک کن؛
  لاگ Railway معمولاً دقیق می‌گوید کدام متغیر یا سشن مشکل دارد.
- **`.ai` خطای 429 می‌دهد:** چرخش کلید خودکار است؛ کلید خراب ۱۰ دقیقه
  کنار گذاشته می‌شود. اگر همه‌ی کلیدها سهمیه‌شان تمام شده، کلید تازه
  اضافه کن.
- **سشن از کار افتاد:** `setup_session.py` را دوباره اجرا کن و رشته‌های
  تازه را جایگذاری کن.
- **دانلود یوتیوب/موزیک کار نمی‌کند:** `yt-dlp` و `ffmpeg` لازم‌اند
  (در Dockerfile هست). اگر در کشوری هستی که یوتیوب فیلتر است،
  `HTTP_PROXY_URL` را ست کن.
