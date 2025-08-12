import os
import logging
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

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------------
# Environment / config
# -------------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")  # set in Railway env (or .env locally)
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
DEFAULT_TARGET = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

# -------------------------
# Supported languages (display name -> code used by translators/tts)
# Add languages here as needed.
# -------------------------
LANGS = {
    "English": "en",
    "Russian": "ru",
    "Arabic": "ar",
    "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW",
    "Spanish": "es",
    "French": "fr",
    "Italian": "it",
    "German": "de",
    "Portuguese": "pt",
    "Hindi": "hi",
    "Pashto": "ps",
    # add more if you need
}

# -------------------------
# Helpers: keyboard builders
# -------------------------
def build_lang_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard with language options.
    prefix: 'src_' or 'tgt_'
    callback_data will be like 'src_en' or 'tgt_ru' or 'src_zh-CN'
    """
    buttons = []
    row = []
    i = 0
    for name, code in LANGS.items():
        cb = f"{prefix}{code}"
        row.append(InlineKeyboardButton(name, callback_data=cb))
        i += 1
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # add a back button to return to main menu
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)


def get_main_menu() -> InlineKeyboardMarkup:
    """Return main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translate", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translate", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Voice → Translate + TTS", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice cloning (experimental)", callback_data="mode_voice_clone"),
        ],
        [
            InlineKeyboardButton("🔁 Change source language", callback_data="change_source"),
            InlineKeyboardButton("🌐 Change target language", callback_data="change_target"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


BACK_BUTTON = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])


# -------------------------
# Utility: map simple codes to speech_recognition expected codes
# -------------------------
def sr_lang_from_code(code: str | None) -> str | None:
    """Map short codes to formats accepted by Google recognizer (best-effort).
    If cannot map, return None to let recognizer auto-detect.
    """
    if not code or code == "auto":
        return None
    # If code already contains region (like zh-CN, zh-TW), use it
    if "-" in code:
        return code
    mapping = {
        "en": "en-US",
        "ru": "ru-RU",
        "es": "es-ES",
        "fr": "fr-FR",
        "it": "it-IT",
        "de": "de-DE",
        "pt": "pt-PT",
        "hi": "hi-IN",
        "ps": "ps-AF",
        "ar": "ar-SA",
        "zh": "zh-CN",
    }
    return mapping.get(code)


# -------------------------
# /start handler
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu and reset mode (user_data)."""
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    logger.info("User %s started or requested menu", update.effective_user.id if update.effective_user else "unknown")
    await update.message.reply_text(
        "👋 Welcome! Choose a mode. You can set 'From' and 'To' languages using the buttons below.",
        reply_markup=get_main_menu(),
    )


# -------------------------
# Mode selection callbacks
# -------------------------
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mode buttons and 'change source/target' requests."""
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info("Callback data (mode selection): %s", data)

    if data.startswith("mode_"):
        mode = data  # e.g. mode_text, mode_voice, etc.
        context.user_data["mode"] = mode
        mode_readable = {
            "mode_text": "Text → Translate",
            "mode_voice": "Voice → Translate",
            "mode_voice_tts": "Voice → Translate + TTS",
            "mode_voice_clone": "Voice cloning (experimental)",
        }.get(mode, mode)
        await query.edit_message_text(
            text=f"✅ Selected mode: *{mode_readable}*\n\nFrom: `{context.user_data.get('source_lang') or 'auto-detect'}`\nTo: `{context.user_data.get('target_lang')}`",
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON,
        )
        return

    if data == "change_source":
        await query.edit_message_text(
            text="Select source language (the language you will speak/type):",
            reply_markup=build_lang_keyboard("src_"),
        )
        return

    if data == "change_target":
        await query.edit_message_text(
            text="Select target language (the language you want to receive):",
            reply_markup=build_lang_keyboard("tgt_"),
        )
        return

    # If other, fallback to menu
    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return


# -------------------------
# Language choice handler (src_/tgt_)
# -------------------------
async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info("Callback data (lang choice): %s", data)

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

    if data.startswith("src_"):
        code = data[len("src_") :]
        context.user_data["source_lang"] = code
        await query.edit_message_text(
            text=f"✅ Source language set to `{code}`", parse_mode="Markdown", reply_markup=get_main_menu()
        )
        return

    if data.startswith("tgt_"):
        code = data[len("tgt_") :]
        context.user_data["target_lang"] = code
        await query.edit_message_text(
            text=f"✅ Target language set to `{code}`", parse_mode="Markdown", reply_markup=get_main_menu()
        )
        return


# -------------------------
# Text handler
# -------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Translate user text when in text mode."""
    mode = context.user_data.get("mode")
    if mode != "mode_text":
        await update.message.reply_text(
            "⚠️ Please select the mode 'Text → Translate' first (/start).", reply_markup=BACK_BUTTON
        )
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET
    original_text = update.message.text
    try:
        translated = GoogleTranslator(source=src if src != "auto" else "auto", target=tgt).translate(original_text)
        await update.message.reply_text(f"🌐 Translation ({src} → {tgt}):\n\n{translated}", reply_markup=BACK_BUTTON)
    except Exception as e:
        logger.exception("Text translation failed")
        await update.message.reply_text(f"Translation error: {e}", reply_markup=BACK_BUTTON)


# -------------------------
# Voice handler (main, robust + logs)
# -------------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages: recognize -> translate -> respond (text, tts, or cloning)."""
    logger.info("handle_voice called")
    mode = context.user_data.get("mode")
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("User %s mode=%s", user_id, mode)

    if not mode:
        await update.message.reply_text("⚠️ Choose a mode first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    # Download voice file
    try:
        voice = await update.message.voice.get_file()
        voice_file = BytesIO()
        await voice.download_to_memory(out=voice_file)
        voice_file.seek(0)
        logger.info("Voice downloaded to memory for user=%s", user_id)
    except Exception as e:
        logger.exception("Failed to download voice")
        await update.message.reply_text(f"❌ Failed to download voice: {e}", reply_markup=BACK_BUTTON)
        return

    # Convert ogg -> wav (in memory)
    try:
        audio = AudioSegment.from_ogg(voice_file)
        duration_sec = len(audio) / 1000.0
        logger.info("Audio duration: %.2f s", duration_sec)
        wav_io = BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
    except Exception as e:
        logger.exception("Failed to convert audio")
        await update.message.reply_text(f"❌ Audio convert error: {e}", reply_markup=BACK_BUTTON)
        return

    # Speech recognition
    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            sr_lang = sr_lang_from_code(src)
            logger.info("Using recognizer language: %s", sr_lang)
            if sr_lang:
                text = recognizer.recognize_google(audio_data, language=sr_lang)
            else:
                text = recognizer.recognize_google(audio_data)
            logger.info("Recognized text: %s", text)
    except sr.UnknownValueError:
        await update.message.reply_text("Could not understand audio.", reply_markup=BACK_BUTTON)
        return
    except Exception as e:
        logger.exception("Recognition error")
        await update.message.reply_text(f"Recognition error: {e}", reply_markup=BACK_BUTTON)
        return

    # Translate
    try:
        translated = GoogleTranslator(source=(src if src != "auto" else "auto"), target=tgt).translate(text)
        logger.info("Translated text: %s", translated)
    except Exception as e:
        logger.exception("Translation error")
        await update.message.reply_text(f"Translation error: {e}", reply_markup=BACK_BUTTON)
        return

    # Respond according to mode
    try:
        if mode == "mode_voice":
            await update.message.reply_text(
                f"🗣 Recognized: {text}\n\n🌐 Translation ({src} → {tgt}): {translated}", reply_markup=BACK_BUTTON
            )
            return

        if mode == "mode_voice_tts":
            # Generate TTS with gTTS
            tts_lang = tgt
            try:
                tts = gTTS(translated, lang=tts_lang)
            except Exception:
                # fallback to two-letter part
                tts = gTTS(translated, lang=tts_lang.split("-")[0])
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts.save(tmp_file.name)
                tmp_file_path = tmp_file.name
            with open(tmp_file_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file, reply_markup=BACK_BUTTON)
            os.remove(tmp_file_path)
            return

        if mode == "mode_voice_clone":
            # Voice cloning branch
            await update.message.reply_text("⏳ Preparing voice cloning... this may take a while.", reply_markup=BACK_BUTTON)
            logger.info("Starting cloning branch for user=%s", user_id)

            if duration_sec < 30:
                await update.message.reply_text(
                    "⚠️ For voice cloning we need at least 30 seconds of audio. Please send longer sample.", reply_markup=BACK_BUTTON
                )
                return

            # Save temp mp3 to upload
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                    audio.export(tmp_mp3.name, format="mp3")
                    mp3_path = tmp_mp3.name
                logger.info("Saved mp3 for cloning: %s", mp3_path)
            except Exception as e:
                logger.exception("Failed to save mp3")
                await update.message.reply_text(f"Error preparing audio for cloning: {e}", reply_markup=BACK_BUTTON)
                return

            try:
                # try to reuse existing cloned voice id
                existing = context.user_data.get("cloned_voice_id")
                if existing:
                    voice_id = existing
                    logger.info("Reusing existing voice id: %s", voice_id)
                else:
                    voice_id = await clone_user_voice(user_id, mp3_path)
                    logger.info("clone_user_voice returned: %s", voice_id)

                if not voice_id:
                    await update.message.reply_text("❌ Voice cloning failed (no voice id). Check logs.", reply_markup=BACK_BUTTON)
                    return

                context.user_data["cloned_voice_id"] = voice_id
                await update.message.reply_text(f"✅ Voice cloned: {voice_id}. Generating TTS now...", reply_markup=BACK_BUTTON)

                # Synthesize translated text using ElevenLabs TTS
                try:
                    synth_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
                    payload = {"text": translated, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
                    r = requests.post(synth_url, headers=headers, json=payload, timeout=60)
                    logger.info("ElevenLabs synth response status: %s", r.status_code)
                    if r.status_code == 200:
                        tmp_out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                        tmp_out.write(r.content)
                        tmp_out.flush()
                        tmp_out_path = tmp_out.name
                        tmp_out.close()
                        with open(tmp_out_path, "rb") as af:
                            await update.message.reply_voice(voice=af, reply_markup=BACK_BUTTON)
                        os.remove(tmp_out_path)
                    else:
                        logger.error("ElevenLabs synth failed: %s %s", r.status_code, r.text)
                        await update.message.reply_text(f"❌ Cloning/TTS error: {r.text}", reply_markup=BACK_BUTTON)
                except Exception as e:
                    logger.exception("Error during ElevenLabs synth")
                    await update.message.reply_text(f"Error during ElevenLabs synth: {e}", reply_markup=BACK_BUTTON)
            finally:
                # cleanup sample
                try:
                    if os.path.exists(mp3_path):
                        os.remove(mp3_path)
                except Exception:
                    pass
            return

        # fallback if mode unknown
        await update.message.reply_text("Mode not supported.", reply_markup=BACK_BUTTON)

    except Exception as e:
        logger.exception("Error while responding to voice")
        await update.message.reply_text(f"Error while responding: {e}", reply_markup=BACK_BUTTON)


# -------------------------
# ElevenLabs cloning helper
# -------------------------
async def clone_user_voice(user_id: int, audio_file_path: str) -> str | None:
    """Upload audio sample to ElevenLabs to create a custom voice.
    Returns voice_id on success, None on failure.
    """
    if not ELEVENLABS_API_KEY:
        logger.error("ElevenLabs API key is missing (ELEVEN_API_KEY env var).")
        return None

    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    voice_name = f"user_{user_id}_voice"

    files = {
        "name": (None, voice_name),
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg"),
    }

    try:
        resp = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files, timeout=120)
        logger.info("clone_user_voice status: %s", resp.status_code)
        if resp.status_code in (200, 201):
            data = resp.json()
            voice_id = data.get("voice_id") or data.get("id") or (data.get("voice") or {}).get("voice_id")
            logger.info("Voice cloned: %s; response: %s", voice_id, data)
            return voice_id
        else:
            logger.error("❌ Cloning error: %s", resp.text)
            return None
    except Exception as e:
        logger.exception("Exception during cloning")
        return None
    finally:
        # close the file descriptor used in files
        try:
            files["files"][1].close()
        except Exception:
            pass


# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set. Please set it in Railway env or .env file.")
        raise SystemExit("Missing TELEGRAM_TOKEN")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))

    # Callback query handlers: modes / change source/target
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern=r'^(mode_|change_source|change_target)$'))
    # Language choice handler (source/target/back)
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern=r'^(src_|tgt_|back_to_menu)$'))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("🤖 Bot starting...")
    app.run_polling()