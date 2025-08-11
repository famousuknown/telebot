import os
import io
import asyncio
import requests
from gtts import gTTS
from io import BytesIO
from pydub import AudioSegment
import speech_recognition as sr
import tempfile
from deep_translator import GoogleTranslator
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

# Load env
load_dotenv()

# Environment variables (try several names for ElevenLabs key in case of mismatch)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG_DEFAULT = os.getenv("TARGET_LANG", "en")
ELEVENLABS_API_KEY = (
    os.getenv("ELEVEN_API_KEY")
    or os.getenv("ELEVEN_API_KEY")
    or os.getenv("ELEVEN_KEY")
)

# ElevenLabs endpoints
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
ELEVENLABS_TTS_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{}"

recognizer = sr.Recognizer()

# --- Helpers: UI menus ---
def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translation", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translation", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Voice → Translation + TTS", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice Cloning", callback_data="mode_voice_clone"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

back_button_markup = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")]]
)

def get_language_menu():
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇪🇸 Spanish", callback_data="lang_es")],
        [InlineKeyboardButton("🇮🇹 Italian", callback_data="lang_it")],
        [InlineKeyboardButton("🇩🇪 German", callback_data="lang_de")],
        [InlineKeyboardButton("🇫🇷 French", callback_data="lang_fr")],
        [InlineKeyboardButton("🏠 Back", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- /start: set defaults (autodetect target from Telegram language) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Try to set default target language from Telegram user language_code
    user_lang_code = None
    if update.effective_user and update.effective_user.language_code:
        user_lang_code = update.effective_user.language_code.split("-")[0][:2].lower()
    # store defaults in user_data
    context.user_data["mode"] = None
    context.user_data["target_lang"] = user_lang_code or TARGET_LANG_DEFAULT
    # send menu
    await update.message.reply_text(
        "👋 Welcome! Choose a mode:\n\n"
        f"(Detected UI language: {user_lang_code or 'N/A'} — default target set accordingly.)",
        reply_markup=get_main_menu(),
    )

# --- Mode selection ---
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_mode = query.data
    context.user_data["mode"] = selected_mode

    # if we need language choice next, show language menu
    if selected_mode in ("mode_voice_tts", "mode_voice_clone"):
        await query.edit_message_text(text="🌍 Choose the target language:", reply_markup=get_language_menu())
        return

    mode_names = {
        "mode_text": "Text → Translation",
        "mode_voice": "Voice → Translation",
        "mode_voice_tts": "Voice → Translation + TTS",
        "mode_voice_clone": "Voice Cloning",
    }

    await query.edit_message_text(
        text=f"✅ Selected mode: *{mode_names.get(selected_mode, selected_mode)}*",
        parse_mode="Markdown",
        reply_markup=back_button_markup,
    )

# --- Language selection handler ---
async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # callback_data like "lang_en"
    parts = query.data.split("_")
    if len(parts) >= 2:
        lang_code = parts[1]
    else:
        lang_code = TARGET_LANG_DEFAULT
    context.user_data["target_lang"] = lang_code
    await query.edit_message_text(text=f"✅ Target language set to: {lang_code.upper()}", reply_markup=back_button_markup)

# --- Back to menu handler ---
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = None
    await query.edit_message_text("👋 Main menu:", reply_markup=get_main_menu())

# --- Text messages handler ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)
    if mode == "mode_text":
        original_text = update.message.text
        translated = GoogleTranslator(source="auto", target=target_lang).translate(original_text)
        await update.message.reply_text(f"🌐 Translation ({target_lang}): {translated}", reply_markup=back_button_markup)
    else:
        await update.message.reply_text(
            "⚠️ Please select 'Text → Translation' first (/start).", reply_markup=back_button_markup
        )

# --- Utility: try STT with multiple languages (best-effort) ---
async def recognize_with_fallback(wav_io: BytesIO):
    """Try to recognize speech; first try default, then try a list of common languages."""
    wav_io.seek(0)
    with sr.AudioFile(wav_io) as source:
        audio_data = recognizer.record(source)

    # 1) Try default (no language specified)
    try:
        text = recognizer.recognize_google(audio_data)
        return text
    except Exception:
        pass

    # 2) Try a prioritized list
    candidates = ["ru-RU", "en-US", "es-ES", "it-IT", "de-DE", "fr-FR"]
    for lang in candidates:
        try:
            text = recognizer.recognize_google(audio_data, language=lang)
            return text
        except Exception:
            continue

    # If nothing worked, raise UnknownValueError
    raise sr.UnknownValueError()

# --- ElevenLabs: clone voice (runs in thread to avoid blocking) ---
def _clone_user_voice_sync(eleven_api_key: str, user_id: int, audio_file_path: str):
    headers = {"xi-api-key": eleven_api_key} if eleven_api_key else {}
    voice_name = f"user_{user_id}_voice"
    files = {
        "name": (None, voice_name),
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg"),
    }
    resp = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files, timeout=60)
    return resp

async def clone_user_voice(eleven_api_key: str, user_id: int, audio_file_path: str):
    resp = await asyncio.to_thread(_clone_user_voice_sync, eleven_api_key, user_id, audio_file_path)
    return resp

# --- ElevenLabs: TTS with cloned voice (sync helper) ---
def _eleven_tts_sync(eleven_api_key: str, voice_id: str, text: str):
    url = ELEVENLABS_TTS_URL_TEMPLATE.format(voice_id)
    headers = {"xi-api-key": eleven_api_key, "Content-Type": "application/json"} if eleven_api_key else {"Content-Type": "application/json"}
    payload = {"text": text, "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    return resp

async def eleven_tts(eleven_api_key: str, voice_id: str, text: str):
    resp = await asyncio.to_thread(_eleven_tts_sync, eleven_api_key, voice_id, text)
    return resp

# --- Unified voice handler (handles voice->translate, tts, cloning) ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("voice received")
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)

    if mode is None:
        await update.message.reply_text("⚠️ Please select a mode first (/start).", reply_markup=back_button_markup)
        return

    # download voice to memory
    voice = await update.message.voice.get_file()
    buf = BytesIO()
    await voice.download_to_memory(out=buf)
    buf.seek(0)

    # convert ogg → wav
    audio = AudioSegment.from_ogg(buf)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        # Recognize with fallback attempts
        recognized_text = await recognize_with_fallback(wav_io)
    except sr.UnknownValueError:
        await update.message.reply_text("Could not recognize speech.", reply_markup=back_button_markup)
        return
    except Exception as e:
        await update.message.reply_text(f"Recognition error: {e}", reply_markup=back_button_markup)
        return

    # Translate the recognized text
    translated_text = GoogleTranslator(source="auto", target=target_lang).translate(recognized_text)

    # Branch per mode
    if mode == "mode_voice":
        await update.message.reply_text(
            f"🗣 Recognized: {recognized_text}\n\n🌐 Translation ({target_lang}): {translated_text}",
            reply_markup=back_button_markup,
        )
        return

    if mode == "mode_voice_tts":
        # use gTTS for quick TTS (language = target_lang)
        try:
            tts = gTTS(translated_text, lang=target_lang)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts.save(tmp.name)
                tmp_path = tmp.name

            with open(tmp_path, "rb") as f:
                await update.message.reply_voice(voice=f, reply_markup=back_button_markup)
            os.remove(tmp_path)
        except Exception as e:
            await update.message.reply_text(f"TTS error: {e}", reply_markup=back_button_markup)
        return

    if mode == "mode_voice_clone":
        # length check (pydub length in ms)
        duration_sec = len(audio) / 1000.0
        if duration_sec < 30:
            await update.message.reply_text("⚠️ At least 30 seconds of audio required for cloning.", reply_markup=back_button_markup)
            return

        await update.message.reply_text("⏳ Uploading sample and cloning voice, please wait...", reply_markup=back_button_markup)

        # export to mp3 temporary file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
            audio.export(tmp_mp3.name, format="mp3")
            mp3_path = tmp_mp3.name

        # clone via ElevenLabs (blocking call in thread)
        try:
            resp = await clone_user_voice(ELEVENLABS_API_KEY, update.effective_user.id, mp3_path)
            # remove temp mp3
            try:
                os.remove(mp3_path)
            except Exception:
                pass

            if resp.status_code != 200:
                await update.message.reply_text(f"❌ Cloning error: {resp.text}", reply_markup=back_button_markup)
                return

            data = resp.json()
            voice_id = data.get("voice_id") or data.get("id") or data.get("voiceId")
            if not voice_id:
                await update.message.reply_text(f"❌ Could not get voice_id from response: {data}", reply_markup=back_button_markup)
                return

            context.user_data["cloned_voice_id"] = voice_id

            # now generate TTS from translated_text
            tts_resp = await eleven_tts(ELEVENLABS_API_KEY, voice_id, translated_text)
            if tts_resp.status_code == 200:
                audio_bytes = BytesIO(tts_resp.content)
                audio_bytes.name = "cloned.mp3"
                await update.message.reply_voice(voice=audio_bytes, reply_markup=back_button_markup)
            else:
                await update.message.reply_text(f"❌ TTS generation error: {tts_resp.text}", reply_markup=back_button_markup)

        except Exception as e:
            await update.message.reply_text(f"Error during cloning/TTS: {e}", reply_markup=back_button_markup)
        return

# --- Run bot ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(handle_language_selection, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Bot started...")
    app.run_polling()