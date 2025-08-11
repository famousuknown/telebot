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
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")  # Ensure the correct name here
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

recognizer = sr.Recognizer()

# === Main menu ===
def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📄 Text → Translate", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Voice → Translate", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Voice + TTS", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Voice cloning", callback_data="mode_voice_clone"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# === Back to menu button ===
back_button_markup = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔙 Back to menu", callback_data="back_to_menu")]
])

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Auto-detect Telegram interface language
    user_lang = update.effective_user.language_code
    context.user_data["source_lang"] = user_lang
    context.user_data["target_lang"] = "en"  # Default target

    context.user_data["mode"] = None
    await update.message.reply_text(
        f"👋 Welcome! Your Telegram language is: {user_lang}\nChoose mode:",
        reply_markup=get_main_menu()
    )

# === Mode selection ===
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_mode = query.data
    context.user_data["mode"] = selected_mode

    mode_names = {
        "mode_text": "Text → Translate",
        "mode_voice": "Voice → Translate",
        "mode_voice_tts": "Voice → Translate + TTS",
        "mode_voice_clone": "Voice cloning",
    }

    await query.edit_message_text(
        text=f"✅ Mode selected: *{mode_names[selected_mode]}*",
        parse_mode="Markdown",
        reply_markup=back_button_markup
    )

# === Back to menu ===
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = None
    await query.edit_message_text("👋 Main menu:", reply_markup=get_main_menu())

# === Text messages ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", "en")

    if mode == "mode_text":
        original_text = update.message.text
        translated = GoogleTranslator(source='auto', target=target_lang).translate(original_text)
        await update.message.reply_text(
            f"🌐 Translation ({target_lang}): {translated}",
            reply_markup=back_button_markup
        )
    else:
        await update.message.reply_text(
            "⚠️ Please select 'Text → Translate' mode to translate text.",
            reply_markup=back_button_markup
        )

# === Clone voice ===
async def clone_user_voice(user_id: int, audio_file_path: str):
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
        print(f"✅ Voice cloned successfully. ID: {voice_id}")
        return voice_id
    else:
        print(f"❌ Error cloning voice: {response.text}")
        return None

# === Generate speech from text with cloned voice ===
def generate_speech_with_cloned_voice(text: str, voice_id: str):
    url = f"{ELEVENLABS_TTS_URL}/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "voice_settings": {"stability": 0.75, "similarity_boost": 0.75}
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return BytesIO(response.content)
    else:
        print(f"❌ Error generating speech: {response.text}")
        return None

# === Voice messages ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    target_lang = context.user_data.get("target_lang", "en")

    if mode is None:
        await update.message.reply_text("⚠️ Please select a mode with /start.", reply_markup=back_button_markup)
        return

    # Download voice file
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    # Convert to wav for speech recognition
    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="auto")

            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)

            if mode == "mode_voice":
                await update.message.reply_text(
                    f"🗣 Recognized: {text}\n\n🌐 Translation ({target_lang}): {translated}",
                    reply_markup=back_button_markup
                )

            elif mode == "mode_voice_tts":
                tts = gTTS(translated, lang=target_lang)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name
                with open(tmp_file_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)
                os.remove(tmp_file_path)

            elif mode == "mode_voice_clone":
                duration_sec = len(audio) / 1000
                if duration_sec < 30:
                    await update.message.reply_text("⚠️ Need at least 30 seconds of audio for cloning.")
                    return

                await update.message.reply_text("⏳ Audio accepted. Cloning in progress...")
                voice_id = await clone_user_voice(update.effective_user.id, save_temp_mp3(audio))

                if voice_id:
                    context.user_data["cloned_voice_id"] = voice_id
                    await update.message.reply_text("✅ Voice cloned successfully. Generating translated audio...")

                    # Generate speech in the cloned voice
                    audio_data = generate_speech_with_cloned_voice(translated, voice_id)
                    if audio_data:
                        await update.message.reply_voice(voice=audio_data, reply_markup=back_button_markup)
                    else:
                        await update.message.reply_text("❌ Failed to generate speech.")
                else:
                    await update.message.reply_text("❌ Voice cloning failed.")

    except sr.UnknownValueError:
        await update.message.reply_text("Could not recognize speech.", reply_markup=back_button_markup)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}", reply_markup=back_button_markup)

# === Helper: save audio to temp mp3 ===
def save_temp_mp3(audio_segment):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
        audio_segment.export(tmp_mp3.name, format="mp3")
        return tmp_mp3.name

# === Run bot ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Bot started...")
    app.run_polling()