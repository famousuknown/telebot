import os
from io import BytesIO
from pydub import AudioSegment
import speech_recognition as sr
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загружаем переменные из .env (если запускаем локально)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG = os.getenv("TARGET_LANG", "en")  # по умолчанию перевод на английский

translator = GoogleTranslator(source='auto', target='en')
recognizer = sr.Recognizer()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download(out=voice_file)
    voice_file.seek(0)

    # Преобразуем OGG → WAV
    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")  # распознаём по-русски
            translated = GoogleTranslator(source='auto', target='en').translate("Привет")

            await update.message.reply_text(f"🗣 Распознано: {text}\n\n🌐 Перевод ({TARGET_LANG}): {translated.text}")
    except sr.UnknownValueError:
        await update.message.reply_text("Не удалось распознать речь.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Бот запущен...")
    app.run_polling()