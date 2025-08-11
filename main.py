import os
import requests
from gtts import gTTS
from io import BytesIO
from pydub import AudioSegment
import speech_recognition as sr
import tempfile
from deep_translator import GoogleTranslator
from langdetect import detect
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

# === Load environment variables ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
recognizer = sr.Recognizer()

# Supported translation languages (more can be added here)
LANGUAGE_OPTIONS = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "de": "German",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
}

# === Main menu ===
def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translate", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translate", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Voice + TTS", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice Clone", callback_data="mode_voice_clone"),
        ],
        [
            InlineKeyboardButton("🌍 Change Language", callback_data="change_language"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# === Language selection keyboard ===
def get_language_keyboard():
    keyboard = []
    row = []
    for code, name in LANGUAGE_OPTIONS.items():
        row.append(InlineKeyboardButton(name, callback_data=f"lang_{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("target_lang", "en")
    context.user_data.setdefault("cloned_voice_id", None)
    await update.message.reply_text("👋 Welcome! Please choose a mode:", reply_markup=get_main_menu())

# === Mode selection ===
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "change_language":
        await query.edit_message_text("🌍 Choose target language:", reply_markup=get_language_keyboard())
        return
    selected_mode = query.data
    context.user_data["mode"] = selected_mode
    mode_names = {
        "mode_text": "Text → Translate",
        "mode_voice": "Voice → Translate",
        "mode_voice_tts": "Voice → Translate + TTS",
        "mode_voice_clone": "Voice Cloning",
    }
    await query.edit_message_text(
        text=f"✅ Mode selected: *{mode_names[selected_mode]}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")]])
    )

# === Language selection ===
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split("_")[1]
    context.user_data["target_lang"] = lang_code
    await query.edit_message_text(f"✅ Target language set to: {LANGUAGE_OPTIONS[lang_code]}", reply_markup=get_main_menu())

# === Back to menu ===
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👋 Main menu:", reply_markup=get_main_menu())

# === Text translation ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode == "mode_text":
        original_text = update.message.text
        translated = GoogleTranslator(source='auto', target=context.user_data["target_lang"]).translate(original_text)
        await update.message.reply_text(f"🌐 Translation ({context.user_data['target_lang']}): {translated}")
    else:
        await update.message.reply_text("⚠️ Please select text mode first via /start.")

# === Clone voice function ===
async def clone_user_voice(user_id: int, audio_file_path: str, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("cloned_voice_id"):
        return context.user_data["cloned_voice_id"]  # Use saved voice ID

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
        voice_id = data.get("voice_id")
        context.user_data["cloned_voice_id"] = voice_id
        return voice_id
    else:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Cloning error: {response.text}")
        return None

# === Handle voice messages ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("⚠️ Please choose a mode first with /start.")
        return

    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)

        # Auto-detect source language if not set manually
        detected_lang = detect(text)
        target_lang = context.user_data.get("target_lang", "en")
        if target_lang == detected_lang:
            target_lang = "en" if detected_lang != "en" else "es"  # Fallback if same as source

        translated = GoogleTranslator(source='auto', target=target_lang).translate(text)

        if mode == "mode_voice":
            await update.message.reply_text(f"🗣 Recognized: {text}\n🌐 Translation ({target_lang}): {translated}")

        elif mode == "mode_voice_tts":
            tts = gTTS(translated, lang=target_lang)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts.save(tmp_file.name)
                tmp_path = tmp_file.name
            with open(tmp_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file)
            os.remove(tmp_path)

        elif mode == "mode_voice_clone":
            duration_sec = len(audio) / 1000
            if duration_sec < 30 and not context.user_data.get("cloned_voice_id"):
                await update.message.reply_text("⚠️ Need at least 30 seconds of audio for first-time cloning.")
                return

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                audio.export(tmp_mp3.name, format="mp3")
                mp3_path = tmp_mp3.name

            voice_id = await clone_user_voice(update.effective_user.id, mp3_path, context)
            os.remove(mp3_path)

            if voice_id:
                headers = {
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json"
                }
                payload = {
                    "text": translated,
                    "voice_settings": {"stability": 0.75, "similarity_boost": 0.75}
                }
                response = requests.post(f"{ELEVENLABS_TTS_URL}/{voice_id}", headers=headers, json=payload)
                if response.status_code == 200:
                    audio_data = response.content
                    await update.message.reply_voice(voice=BytesIO(audio_data))
                else:
                    await update.message.reply_text(f"❌ TTS error: {response.text}")

    except sr.UnknownValueError:
        await update.message.reply_text("❌ Could not recognize speech.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# === Start bot ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Bot is running...")
    app.run_polling()