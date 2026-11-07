#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KetaSelf setup — ساختن StringSession برای دیپلوی روی هاست (Railway / Docker).

روی کامپیوتر خودت اجرا کن؛ یک بار با شماره موبایل + کد تایید تلگرام وارد
می‌شوی و دو رشته‌ی سشن چاپ می‌شود:

  SESSION_STRING         -> سشن اکانت کاربری (سلف‌بات)
  HELPER_SESSION_STRING  -> سشن بات کمکی (توکن بات)

این دو رشته را در متغیرهای محیطی هاست (Railway Variables یا .env سرور)
بگذار؛ دیگر نیازی به آپلود فایل سشن نیست.

هشدار امنیتی: رشته‌ی سشن معادل رمز عبور اکانت تلگرام توست. هرگز آن را با
کسی به اشتراک نگذار، در چت نفرست و در گیت کامیت نکن. این اسکریپت هرگز
مقدار API_ID و API_HASH را چاپ یا ذخیره نمی‌کند.

روش اجرا:
  1. cp .env.example .env   (و API_ID ،API_HASH ،BOT_TOKEN را پر کن)
  2. python3 setup_session.py
  3. دو رشته‌ی چاپ‌شده را کپی کن.
"""

import os
import asyncio
from getpass import getpass

from dotenv import load_dotenv

load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession


def _prompt_api_id() -> int:
    env_value = (os.getenv("API_ID", "") or "").strip()
    if env_value:
        return int(env_value)
    while True:
        raw = input("API_ID (از https://my.telegram.org): ").strip()
        try:
            return int(raw)
        except ValueError:
            print("عدد معتبر وارد کن.")


def _prompt_api_hash() -> str:
    env_value = (os.getenv("API_HASH", "") or "").strip()
    if env_value:
        return env_value
    return getpass("API_HASH (از https://my.telegram.org): ").strip()


def _prompt_bot_token() -> str:
    env_value = (os.getenv("BOT_TOKEN", "") or "").strip()
    if env_value:
        return env_value
    return getpass("BOT_TOKEN (از @BotFather): ").strip()


async def main() -> None:
    api_id = _prompt_api_id()
    api_hash = _prompt_api_hash()
    bot_token = _prompt_bot_token()

    phone = input("شماره موبایل اکانت تلگرام (با کد کشور، مثلا +98...): ").strip()

    print("\nدر حال ورود به اکانت کاربری... کد تایید را که تلگرام فرستاد وارد کن.")
    user = TelegramClient(StringSession(), api_id, api_hash)
    await user.start(phone=phone)
    me = await user.get_me()
    user_string = user.session.save()
    print(f"وارد شدی به‌عنوان: {me.first_name} (@{me.username})")
    await user.disconnect()

    print("\nدر حال ورود بات کمکی...")
    helper = TelegramClient(StringSession(), api_id, api_hash)
    await helper.start(bot_token=bot_token)
    bot_me = await helper.get_me()
    helper_string = helper.session.save()
    print(f"بات کمکی: @{bot_me.username}")
    await helper.disconnect()

    print("\n" + "=" * 70)
    print("این دو خط را در متغیرهای محیطی هاست بگذار (و جای امن دیگری نگه دار):")
    print("=" * 70)
    print("SESSION_STRING=" + user_string)
    print("HELPER_SESSION_STRING=" + helper_string)
    print("=" * 70)
    print("هشدار: این رشته‌ها را با هیچ‌کس به اشتراک نگذار.")


if __name__ == "__main__":
    asyncio.run(main())
