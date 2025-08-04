import os
from io import BytesIO
from pydub import AudioSegment
import speech_recognition as sr
from deep_translator import GoogleTranslator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import os
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# === КНОПКИ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📄 Текст → Перевод", callback_data="mode_text"),
            InlineKeyboardButton("🎤 Голос → Перевод", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🗣 Озвучка перевода", callback_data="mode_voice_tts"),
            InlineKeyboardButton("🧬 Имитация голоса", callback_data="mode_voice_clone"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите режим работы бота:", reply_markup=reply_markup)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    
    if mode == "mode_voice":
        # распознать речь → перевести → вернуть текст
        pass
    elif mode == "mode_voice_tts":
        # распознать → перевести → озвучить
        pass
    elif mode == "mode_voice_clone":
        await update.message.reply_text("🎛 Имитация голоса пока не реализована.")
    else:
        await update.message.reply_text("⚠️ Сначала выберите режим с помощью /start.")

# === ОБРАБОТКА ВЫБОРА ===
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_mode = query.data
    context.user_data["mode"] = selected_mode

    mode_names = {
        "mode_text": "Текст → Перевод",
        "mode_voice": "Голос → Перевод",
        "mode_voice_tts": "Голос → Перевод + Озвучка",
        "mode_voice_clone": "Имитация голоса (в будущем)",
    }

    await query.edit_message_text(text=f"✅ Выбран режим: *{mode_names[selected_mode]}*", parse_mode="Markdown")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("получено голосовое!!!") #это поможет проверить вызов функции

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
    app.add_handler(CallbackQueryHandler(handle_mode_selection))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("🤖 Бот запущен...")
    app.run_polling()