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

# Load env vars
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"

# Default target language if not chosen
DEFAULT_TARGET = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

# Supported languages mapping
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
}

# Build keyboard of language options
def build_lang_keyboard(prefix: str):
    buttons, row = [], []
    for i, (name, code) in enumerate(LANGS.items(), start=1):
        row.append(InlineKeyboardButton(name, callback_data=f"{prefix}{code}"))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Main menu
def get_main_menu():
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
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

BACK_BUTTON = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    await update.message.reply_text(
        "👋 Welcome! Choose a mode. You can set 'From' and 'To' languages using the buttons below.",
        reply_markup=get_main_menu(),
    )

# Mode selection
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("mode_"):
        mode = data
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

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

# Language choice
async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

    if data.startswith("src_"):
        code = data[len("src_"):]
        context.user_data["source_lang"] = code
        await query.edit_message_text(
            text=f"✅ Source language set to `{code}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

    if data.startswith("tgt_"):
        code = data[len("tgt_"):]
        context.user_data["target_lang"] = code
        await query.edit_message_text(
            text=f"✅ Target language set to `{code}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

# Handle text translation
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode != "mode_text":
        await update.message.reply_text("⚠️ Please select the mode 'Text → Translate' first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    try:
        translated = GoogleTranslator(source=src, target=tgt).translate(update.message.text)
        await update.message.reply_text(f"🌐 Translation ({src} → {tgt}):\n\n{translated}", reply_markup=BACK_BUTTON)
    except Exception as e:
        await update.message.reply_text(f"Translation error: {str(e)}", reply_markup=BACK_BUTTON)

# Handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("⚠️ Choose a mode first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    # Download and convert
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    # Recognition
    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)

            # ✅ Always use chosen source_lang for voice
            if src != "auto":
                recog_lang = src
            else:
                recog_lang = None

            if recog_lang:
                text = recognizer.recognize_google(audio_data, language=recog_lang)
            else:
                text = recognizer.recognize_google(audio_data)
    except sr.UnknownValueError:
        await update.message.reply_text("Could not understand audio.", reply_markup=BACK_BUTTON)
        return
    except Exception as e:
        await update.message.reply_text(f"Recognition error: {str(e)}", reply_markup=BACK_BUTTON)
        return

    # Translate
    try:
        translated = GoogleTranslator(source=src if src != "auto" else "auto", target=tgt).translate(text)
    except Exception as e:
        await update.message.reply_text(f"Translation error: {str(e)}", reply_markup=BACK_BUTTON)
        return

    # Respond
    try:
        if mode == "mode_voice":
            await update.message.reply_text(f"🗣 Recognized: {text}\n\n🌐 Translation ({src} → {tgt}): {translated}", reply_markup=BACK_BUTTON)

        elif mode == "mode_voice_tts":
            try:
                tts = gTTS(translated, lang=tgt)
            except Exception:
                tts = gTTS(translated, lang=tgt.split("-")[0])

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts.save(tmp_file.name)
                tmp_file_path = tmp_file.name

            with open(tmp_file_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file, reply_markup=BACK_BUTTON)
            os.remove(tmp_file_path)

    except Exception as e:
        await update.message.reply_text(f"Error while responding: {str(e)}", reply_markup=BACK_BUTTON)

# Run bot
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|change_source|change_target|back_to_menu)"))
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^(src_|tgt_|back_to_menu)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Bot started...")
    app.run_polling()