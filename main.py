import os
from io import BytesIO
from pydub import AudioSegment
import speech_recognition as sr
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download(out=voice_file)
    voice_file.seek(0)

    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            translated = GoogleTranslator(source='auto', target=TARGET_LANG).translate(text)

            await update.message.reply_text(
                f"🗣 Распознано: {text}\n\n🌐 Перевод ({TARGET_LANG}): {translated}"
            )
    except sr.UnknownValueError:
        await update.message.reply_text("Не удалось распознать речь.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# 👇 Добавим реакцию на /start, чтобы проверить, что бот активен
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь мне голосовое сообщение на русском, и я переведу его.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Бот запущен...")
    app.run_polling()