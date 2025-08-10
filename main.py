import os
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

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# default target language (can be changed by user with UI)
TARGET_LANG_DEFAULT = os.getenv("TARGET_LANG", "en")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

recognizer = sr.Recognizer()

# ---------------------------
# Helper: detect Telegram interface language
# ---------------------------
def get_user_language(update: Update):
    """
    Detects Telegram interface language of the user.
    Returns two-letter code like 'en', 'ru', 'es', etc.
    """
    lang_code = update.effective_user.language_code
    if lang_code:
        return lang_code.split("-")[0]
    return "en"  # default

# ---------------------------
# UI: main menu and language menu
# ---------------------------
def get_main_menu():
    """Return main menu markup."""
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translate", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translate", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 TTS Translation", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice Cloning", callback_data="mode_voice_clone"),
        ],
        [
            InlineKeyboardButton("🌍 Choose translation language", callback_data="choose_target_lang"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_language_menu():
    """Return a markup with popular target languages (you can extend this list)."""
    keyboard = [
        [
            InlineKeyboardButton("English", callback_data="set_target_en"),
            InlineKeyboardButton("Русский", callback_data="set_target_ru"),
            InlineKeyboardButton("Español", callback_data="set_target_es"),
        ],
        [
            InlineKeyboardButton("Français", callback_data="set_target_fr"),
            InlineKeyboardButton("Deutsch", callback_data="set_target_de"),
            InlineKeyboardButton("Italiano", callback_data="set_target_it"),
        ],
        [
            InlineKeyboardButton("日本語", callback_data="set_target_ja"),
            InlineKeyboardButton("中文", callback_data="set_target_zh"),
            InlineKeyboardButton("Back", callback_data="back_to_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

back_button_markup = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")]
])

# ---------------------------
# /start handler
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Welcome message: detect user's interface language and set defaults in user_data.
    """
    user_lang = get_user_language(update)
    context.user_data["user_lang"] = user_lang
    # default per-user target language (can be changed)
    context.user_data["target_lang"] = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)
    context.user_data["mode"] = None

    await update.message.reply_text(
        f"👋 Welcome! (Interface language: {user_lang})\nChoose mode:",
        reply_markup=get_main_menu()
    )

# ---------------------------
# Mode selection handlers
# ---------------------------
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pressing a mode button from main menu."""
    query = update.callback_query
    await query.answer()
    selected_mode = query.data
    context.user_data["mode"] = selected_mode

    mode_names = {
        "mode_text": "Text → Translate",
        "mode_voice": "Voice → Translate",
        "mode_voice_tts": "Voice → Translate + TTS",
        "mode_voice_clone": "Voice Cloning",
    }

    await query.edit_message_text(
        text=f"✅ Selected mode: *{mode_names[selected_mode]}*",
        parse_mode="Markdown",
        reply_markup=back_button_markup
    )

async def handle_choose_target_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show language selection keyboard."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🌍 Choose target language:", reply_markup=get_language_menu())

async def handle_set_target_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user's chosen target language (callback_data: set_target_xx)."""
    query = update.callback_query
    await query.answer()
    data = query.data  # e.g. "set_target_en"
    if not data.startswith("set_target_"):
        await query.edit_message_text("Invalid selection.", reply_markup=get_main_menu())
        return
    lang_code = data.split("_")[-1]
    context.user_data["target_lang"] = lang_code
    await query.edit_message_text(f"✅ Target language set to *{lang_code}*.", parse_mode="Markdown", reply_markup=get_main_menu())

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return user to main menu and reset mode (but keep target_lang)."""
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = None
    await query.edit_message_text("👋 Main menu:", reply_markup=get_main_menu())

# ---------------------------
# Text handler
# ---------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Translate text messages when in text mode."""
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)

    if mode == "mode_text":
        original_text = update.message.text
        translated = GoogleTranslator(source='auto', target=target_lang).translate(original_text)
        await update.message.reply_text(
            f"🌐 Translation ({target_lang}): {translated}",
            reply_markup=back_button_markup
        )
    else:
        await update.message.reply_text(
            "⚠️ To translate text, choose 'Text → Translate' from the menu (/start).",
            reply_markup=back_button_markup
        )

# ---------------------------
# ElevenLabs voice cloning helper
# ---------------------------
async def clone_user_voice(user_id: int, audio_file_path: str):
    """
    Upload user audio to ElevenLabs cloning endpoint and return voice_id.
    This function expects ELEVENLABS_API_KEY to be set and the account to have cloning access.
    """
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    voice_name = f"user_{user_id}_voice"
    files = {
        "name": (None, voice_name),
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg")
    }
    response = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files)
    if response.status_code == 200:
        data = response.json()
        voice_id = data.get("voice_id") or data.get("id") or data.get("uuid")
        print(f"✅ Voice cloned successfully. ID: {voice_id}")
        return voice_id
    else:
        print(f"❌ Error cloning voice: {response.text}")
        return None

# ---------------------------
# Voice handler
# ---------------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process incoming voice message depending on selected mode."""
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", TARGET_LANG_DEFAULT)

    if mode is None:
        await update.message.reply_text("⚠️ Please select mode with /start.", reply_markup=back_button_markup)
        return

    # Download voice file from Telegram
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    # download_to_memory is used by the library — keep this
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    # Convert OGG to WAV for recognition
    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            # Use Google's recognizer to detect original speech (set language auto or a default if needed)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)

        if mode == "mode_voice":
            await update.message.reply_text(
                f"🗣 Recognized: {text}\n\n🌐 Translation ({target_lang}): {translated}",
                reply_markup=back_button_markup
            )

        elif mode == "mode_voice_tts":
            # If user has a cloned voice, use ElevenLabs TTS with it; otherwise fallback to gTTS
            cloned_voice_id = context.user_data.get("cloned_voice_id")
            if cloned_voice_id and ELEVENLABS_API_KEY:
                headers = {
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json"
                }
                payload = {
                    "text": translated,
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.75
                    }
                }
                tts_response = requests.post(f"{ELEVENLABS_TTS_URL}/{cloned_voice_id}", headers=headers, json=payload)
                if tts_response.status_code == 200:
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                        tmp_file.write(tts_response.content)
                        tmp_path = tmp_file.name
                    with open(tmp_path, "rb") as audio_file:
                        await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)
                    os.remove(tmp_path)
                else:
                    await update.message.reply_text("❌ Error generating speech with ElevenLabs. Falling back to gTTS.")
                    tts = gTTS(translated, lang=target_lang)
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                        tts.save(tmp_file.name)
                        tmp_file_path = tmp_file.name
                    with open(tmp_file_path, "rb") as audio_file:
                        await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)
                    os.remove(tmp_file_path)
            else:
                tts = gTTS(translated, lang=target_lang)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name
                with open(tmp_file_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)
                os.remove(tmp_file_path)

        elif mode == "mode_voice_clone":
            # For cloning we require at least 30 seconds of audio
            duration_sec = len(audio) / 1000.0
            if duration_sec < 30:
                await update.message.reply_text("⚠️ Need at least 30 sec audio for cloning.", reply_markup=back_button_markup)
                return
            await update.message.reply_text("⏳ Processing voice cloning...")

            # Export to mp3 for ElevenLabs
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                audio.export(tmp_mp3.name, format="mp3")
                mp3_path = tmp_mp3.name

            # Call cloning helper
            voice_id = await clone_user_voice(update.effective_user.id, mp3_path)
            if voice_id:
                context.user_data["cloned_voice_id"] = voice_id
                await update.message.reply_text("✅ Voice cloned successfully.", reply_markup=back_button_markup)
            else:
                await update.message.reply_text("❌ Error cloning voice.", reply_markup=back_button_markup)

            # cleanup
            try:
                os.remove(mp3_path)
            except Exception:
                pass

    except sr.UnknownValueError:
        await update.message.reply_text("Could not recognize speech.", reply_markup=back_button_markup)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}", reply_markup=back_button_markup)

# ---------------------------
# Run the bot
# ---------------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # command handlers
    app.add_handler(CommandHandler("start", start))

    # callback handlers: modes, language selection, back button
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(handle_choose_target_lang, pattern="^choose_target_lang$"))
    app.add_handler(CallbackQueryHandler(handle_set_target_language, pattern="^set_target_[a-z]{2}$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))

    # text & voice
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot is running...")
    app.run_polling()