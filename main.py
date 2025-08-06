import os
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

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

# === Главное меню ===
def get_main_menu():
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
    return InlineKeyboardMarkup(keyboard)

# === Универсальная кнопка "Назад в меню" ===
back_button_markup = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
])

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    await update.message.reply_text("👋 Добро пожаловать! Выберите режим:", reply_markup=get_main_menu())

# === Обработка выбора режима ===
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

    await query.edit_message_text(
        text=f"✅ Выбран режим: *{mode_names[selected_mode]}*",
        parse_mode="Markdown",
        reply_markup=back_button_markup
    )

# === Обработка кнопки "Назад в меню" ===
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = None
    await query.edit_message_text("👋 Главное меню:", reply_markup=get_main_menu())

# === Текстовые сообщения ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    if mode == "mode_text":
        original_text = update.message.text
        translated = GoogleTranslator(source='auto', target=TARGET_LANG).translate(original_text)
        await update.message.reply_text(
            f"🌐 Перевод ({TARGET_LANG}): {translated}",
            reply_markup=back_button_markup
        )
    else:
        await update.message.reply_text(
            "⚠️ Чтобы переводить текст, выберите режим 📄 Текст → Перевод (/start).",
            reply_markup=back_button_markup
        )

# === Голосовые сообщения ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    if mode is None:
        await update.message.reply_text("⚠️ Сначала выберите режим с помощью /start.", reply_markup=back_button_markup)
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
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            translated = GoogleTranslator(source='auto', target=TARGET_LANG).translate(text)

            if mode == "mode_voice":
                await update.message.reply_text(
                    f"🗣 Распознано: {text}\n\n🌐 Перевод ({TARGET_LANG}): {translated}",
                    reply_markup=back_button_markup
                )

            elif mode == "mode_voice_tts":
                tts = gTTS(translated, lang=TARGET_LANG)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name

                with open(tmp_file_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)

                os.remove(tmp_file_path)

            elif mode == "mode_voice_clone":
                await update.message.reply_text(
                    "🧬 Имитация голоса пока не реализована.",
                    reply_markup=back_button_markup
                )

    except sr.UnknownValueError:
        await update.message.reply_text("Не удалось распознать речь.", reply_markup=back_button_markup)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}", reply_markup=back_button_markup)

# === Запуск ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Бот запущен...")
    app.run_polling()