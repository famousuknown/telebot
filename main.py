import os
import logging
import requests
import tempfile
from langdetect import detect
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")

# User data keys
LANGUAGE, VOICE_CLONING = range(2)

# Supported target languages for translation
SUPPORTED_LANGUAGES = {
    "English": "en",
    "French": "fr",
    "Italian": "it",
    "Spanish": "es",
    "German": "de",
    "Chinese": "zh",
    "Arabic": "ar",
    "Russian": "ru"
}

# Store user's chosen target language and voice_id
user_settings = {}

# Start command handler
async def start(update: Update, context: CallbackContext):
    reply_keyboard = [["Change Language"]]
    await update.message.reply_text(
        "Welcome! 🎯\nPlease send a voice message to start voice cloning and translation.\n"
        "Use the button below to change your target language.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )

# Change language handler
async def change_language(update: Update, context: CallbackContext):
    languages_list = [[lang] for lang in SUPPORTED_LANGUAGES.keys()]
    await update.message.reply_text(
        "Select the language you want the translation to be in:",
        reply_markup=ReplyKeyboardMarkup(languages_list, resize_keyboard=True)
    )
    return LANGUAGE

# Save selected language
async def set_language(update: Update, context: CallbackContext):
    chosen_lang = update.message.text
    if chosen_lang in SUPPORTED_LANGUAGES:
        user_settings[update.message.from_user.id] = {
            "language": SUPPORTED_LANGUAGES[chosen_lang],
            "voice_id": user_settings.get(update.message.from_user.id, {}).get("voice_id")
        }
        await update.message.reply_text(f"✅ Language set to {chosen_lang}.\nSend a voice message now.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Invalid language. Please select from the list.")
        return LANGUAGE

# Process voice message
async def handle_voice(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in user_settings or "language" not in user_settings[user_id]:
        await update.message.reply_text("Please choose your target language first using 'Change Language'.")
        return

    # Download voice file from Telegram
    file = await context.bot.get_file(update.message.voice.file_id)
    with tempfile.NamedTemporaryFile(delete=False) as temp_audio:
        await file.download_to_drive(temp_audio.name)
        audio_path = temp_audio.name

    # Detect language of input audio
    detected_lang = detect_audio_language(audio_path)
    logger.info(f"Detected language: {detected_lang}")

    # Clone voice if not already cloned
    if not user_settings[user_id].get("voice_id"):
        voice_id = clone_voice(audio_path)
        if voice_id:
            user_settings[user_id]["voice_id"] = voice_id
        else:
            await update.message.reply_text("❌ Voice cloning failed.")
            return

    # Translate and generate speech
    translated_audio = translate_and_speak(audio_path, user_settings[user_id]["language"], user_settings[user_id]["voice_id"])
    if translated_audio:
        await update.message.reply_voice(voice=translated_audio)
    else:
        await update.message.reply_text("❌ Failed to translate and generate voice.")

# Detect language from audio file
def detect_audio_language(audio_path):
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            detected_lang = detect(text)
            return detected_lang
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
        return None

# Clone voice using ElevenLabs
def clone_voice(audio_path):
    try:
        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        files = {"files": open(audio_path, "rb")}
        data = {"name": f"user_voice_clone"}
        response = requests.post(url, headers=headers, files=files, data=data)
        if response.status_code == 200:
            voice_id = response.json().get("voice_id")
            return voice_id
        else:
            logger.error(f"Voice cloning error: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error cloning voice: {e}")
        return None

# Translate and generate speech
def translate_and_speak(audio_path, target_lang, voice_id):
    try:
        # Convert audio to text first
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)
            original_text = recognizer.recognize_google(audio_data)

        # Translate text
        from googletrans import Translator
        translator = Translator()
        translated_text = translator.translate(original_text, dest=target_lang).text

        # Generate speech in cloned voice
        tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": translated_text,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        tts_response = requests.post(tts_url, headers=headers, json=payload)
        if tts_response.status_code == 200:
            audio_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            audio_file.write(tts_response.content)
            audio_file.close()
            return open(audio_file.name, "rb")
        else:
            logger.error(f"TTS error: {tts_response.text}")
            return None
    except Exception as e:
        logger.error(f"Error in translate_and_speak: {e}")
        return None

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Change Language$"), change_language)],
        states={LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)]},
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    application.run_polling()

if __name__ == "__main__":
    main()