import os
import json
import asyncio
import tempfile
from io import BytesIO
from typing import Optional

import requests
from gtts import gTTS
from pydub import AudioSegment
import speech_recognition as sr
from deep_translator import GoogleTranslator
from langdetect import detect, LangDetectException

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv

# === Load environment ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG_DEFAULT = os.getenv("TARGET_LANG", "en")
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")  # Put your ElevenLabs key here

# === Constants / ElevenLabs endpoints ===
ELEVEN_VOICE_CREATE_URL = "https://api.elevenlabs.io/v1/voices/add"
ELEVEN_TTS_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

CLONED_DB_PATH = "cloned_voices.json"

# === helpers for persistence ===
def load_cloned_db():
    if os.path.exists(CLONED_DB_PATH):
        try:
            with open(CLONED_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cloned_db(db):
    with open(CLONED_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# === speech recognizer and translator ===
recognizer = sr.Recognizer()

def detect_language_of_text(text: str) -> Optional[str]:
    try:
        lang = detect(text)
        return lang
    except LangDetectException:
        return None

# === Inline keyboards (menus) ===

def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translate", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translate", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Voice → TTS", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice cloning (pro)", callback_data="mode_voice_clone"),
        ],
        [
            InlineKeyboardButton("🌐 Change target language", callback_data="change_lang")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")]])

def get_language_menu():
    langs = [
        ("English", "en"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("French", "fr"),
        ("Italian", "it"),
        ("Chinese", "zh"),
        ("Arabic", "ar"),
    ]
    keyboard = []
    row = []
    for name, code in langs:
        row.append(InlineKeyboardButton(name, callback_data=f"set_lang:{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

# === ElevenLabs helpers (run blocking requests in thread to avoid blocking loop) ===

def _eleven_create_voice_sync(api_key: str, voice_name: str, mp3_path: str):
    headers = {"xi-api-key": api_key}
    files = {
        "name": (None, voice_name),
        "files": (os.path.basename(mp3_path), open(mp3_path, "rb"), "audio/mpeg"),
    }
    resp = requests.post(ELEVEN_VOICE_CREATE_URL, headers=headers, files=files, timeout=60)
    return resp

def _eleven_tts_sync(api_key: str, voice_id: str, text: str):
    url = ELEVEN_TTS_URL_TEMPLATE.format(voice_id=voice_id)
    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        # optional settings:
        "voice_settings": {"stability": 0.7, "similarity_boost": 0.75}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    return resp

async def create_voice_eleven(api_key: str, user_id: int, mp3_path: str) -> Optional[str]:
    voice_name = f"user_{user_id}_voice"
    resp = await asyncio.to_thread(_eleven_create_voice_sync, api_key, voice_name, mp3_path)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    if resp.status_code in (200, 201):
        # try common keys
        voice_id = data.get("voice_id") or data.get("id") or data.get("data", {}).get("voice_id")
        return voice_id
    else:
        # return None and let caller notify error
        raise RuntimeError(f"Cloning error: {data}")

async def synthesize_eleven(api_key: str, voice_id: str, text: str) -> bytes:
    resp = await asyncio.to_thread(_eleven_tts_sync, api_key, voice_id, text)
    if resp.status_code == 200:
        return resp.content
    else:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"TTS error: {err}")

# === Bot handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu and reset user's temporary state."""
    context.user_data["mode"] = None
    # keep user's target_lang if already set
    await update.message.reply_text("👋 Welcome! Choose a mode:", reply_markup=get_main_menu())

async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set operation mode based on button press."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "change_lang":
        await query.edit_message_text("Select target language:", reply_markup=get_language_menu())
        return

    if data.startswith("set_lang:"):
        _, code = data.split(":", 1)
        context.user_data["target_lang"] = code
        await query.edit_message_text(f"✅ Target language set to *{code}*.", parse_mode="Markdown", reply_markup=get_back_markup())
        return

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("👋 Main menu:", reply_markup=get_main_menu())
        return

    # mode selection (mode_text, mode_voice, mode_voice_tts, mode_voice_clone)
    context.user_data["mode"] = data
    friendly = {
        "mode_text": "Text → Translate",
        "mode_voice": "Voice → Translate",
        "mode_voice_tts": "Voice → TTS",
        "mode_voice_clone": "Voice cloning",
    }
    await query.edit_message_text(f"✅ Selected mode: *{friendly.get(data,'mode')}*", parse_mode="Markdown", reply_markup=get_back_markup())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages (translate if in text mode)."""
    mode = context.user_data.get("mode")
    user_target = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)

    if mode != "mode_text":
        await update.message.reply_text("⚠️ To translate text, choose *Text → Translate* in the menu (/start).", parse_mode="Markdown", reply_markup=get_back_markup())
        return

    original = update.message.text
    try:
        translated = GoogleTranslator(source='auto', target=user_target).translate(original)
        await update.message.reply_text(f"🌐 Translation ({user_target}):\n{translated}", reply_markup=get_back_markup())
    except Exception as e:
        await update.message.reply_text(f"Translation error: {e}", reply_markup=get_back_markup())

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages depending on mode (translate, tts, or clone)."""
    print("voice received")
    mode = context.user_data.get("mode")
    if mode is None:
        await update.message.reply_text("⚠️ Please choose a mode first (/start).", reply_markup=get_back_markup())
        return

    # target language for synthesis/translation for this user
    user_target = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)

    # download voice into memory
    file = await update.message.voice.get_file()
    voice_io = BytesIO()
    # use download_to_memory (async)
    await file.download_to_memory(out=voice_io)
    voice_io.seek(0)

    # convert ogg -> wav (speech_recognition prefers wav)
    try:
        audio = AudioSegment.from_ogg(voice_io)
    except Exception as e:
        await update.message.reply_text(f"Audio conversion error: {e}", reply_markup=get_back_markup())
        return

    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    # transcribe
    try:
        with sr.AudioFile(wav_io) as src:
            audio_data = recognizer.record(src)
            # attempt automatic recognition (no explicit language) then detect language
            text = recognizer.recognize_google(audio_data)
            src_lang = detect_language_of_text(text) or "unknown"
    except sr.UnknownValueError:
        await update.message.reply_text("Could not recognize speech.", reply_markup=get_back_markup())
        return
    except Exception as e:
        await update.message.reply_text(f"Recognition error: {e}", reply_markup=get_back_markup())
        return

    # do translation
    try:
        translated = GoogleTranslator(source='auto', target=user_target).translate(text)
    except Exception as e:
        await update.message.reply_text(f"Translation error: {e}", reply_markup=get_back_markup())
        return

    # Respond based on selected mode
    if mode == "mode_voice":
        await update.message.reply_text(f"🗣 Recognized ({src_lang}): {text}\n\n🌐 Translation ({user_target}): {translated}", reply_markup=get_back_markup())
        return

    if mode == "mode_voice_tts":
        # create TTS using gTTS (quick, free)
        try:
            tts_lang = user_target  # gTTS expects language code; ensure it's supported
            tts = gTTS(translated, lang=tts_lang)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpf:
                tts.save(tmpf.name)
                tmp_path = tmpf.name

            with open(tmp_path, "rb") as f:
                await update.message.reply_voice(voice=f, reply_markup=get_back_markup())

            os.remove(tmp_path)
        except Exception as e:
            await update.message.reply_text(f"TTS error (gTTS): {e}", reply_markup=get_back_markup())
        return

    if mode == "mode_voice_clone":
        # voice cloning path: check sample duration and existing cloned id
        duration_sec = len(audio) / 1000.0
        if duration_sec < 30:
            await update.message.reply_text("⚠️ For voice cloning we need at least 30 seconds of sample audio. Please send a longer recording.", reply_markup=get_back_markup())
            return

        await update.message.reply_text("⏳ Sample received. Creating/using your cloned voice (this may take a moment)...", reply_markup=get_back_markup())

        # persist and reuse cloned ids to avoid duplicates
        db = load_cloned_db()
        user_id = str(update.effective_user.id)
        existing_voice_id = db.get(user_id)

        try:
            if existing_voice_id:
                voice_id = existing_voice_id
            else:
                # produce mp3 (Eleven expects an audio file like mp3/mpeg)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                    audio.export(tmp_mp3.name, format="mp3")
                    mp3_path = tmp_mp3.name

                if not ELEVEN_API_KEY:
                    await update.message.reply_text("⚠️ Server misconfiguration: ELEVEN_API_KEY is not set.", reply_markup=get_back_markup())
                    os.remove(mp3_path)
                    return

                voice_id = await create_voice_eleven(ELEVEN_API_KEY, update.effective_user.id, mp3_path)
                # cleanup temp mp3
                os.remove(mp3_path)

                # save mapping
                if voice_id:
                    db[user_id] = voice_id
                    save_cloned_db(db)

            # synthesize translated text with cloned voice
            audio_bytes = await synthesize_eleven(ELEVEN_API_KEY, voice_id, translated)

            # send response audio
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out_tmp:
                out_tmp.write(audio_bytes)
                out_path = out_tmp.name

            with open(out_path, "rb") as f:
                await update.message.reply_voice(voice=f, reply_markup=get_back_markup())

            os.remove(out_path)
        except Exception as e:
            # pass the actual error message for debugging (you can hide in production)
            await update.message.reply_text(f"❌ Cloning/TTS error: {e}", reply_markup=get_back_markup())
        return

# === Entrypoint ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Command and callback handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|back_to_menu|change_lang|set_lang:)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()