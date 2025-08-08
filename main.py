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

# === Загружаем переменные окружения из .env ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TARGET_LANG = os.getenv("TARGET_LANG", "en")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"

# === Инициализация распознавания речи ===
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

# === Универсальная кнопка "Назад" ===
back_button_markup = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
])

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    await update.message.reply_text(
        "👋 Добро пожаловать! Выберите режим:",
        reply_markup=get_main_menu()
    )

# === Выбор режима ===
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_mode = query.data
    context.user_data["mode"] = selected_mode

    mode_names = {
        "mode_text": "Текст → Перевод",
        "mode_voice": "Голос → Перевод",
        "mode_voice_tts": "Голос → Перевод + Озвучка",
        "mode_voice_clone": "Имитация голоса",
    }

    await query.edit_message_text(
        text=f"✅ Выбран режим: *{mode_names[selected_mode]}*",
        parse_mode="Markdown",
        reply_markup=back_button_markup
    )

# === Кнопка "Назад" ===
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = None
    await query.edit_message_text("👋 Главное меню:", reply_markup=get_main_menu())

# === Обработка текста ===
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

# === API-запрос к ElevenLabs для клонирования голоса ===
async def clone_user_voice(user_id: int, audio_file_path: str):
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    voice_name = f"user_{user_id}_voice"

    files = {
        "name": (None, voice_name),
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg")
    }

    response = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files)

    if response.status_code == 200:
        data = response.json()
        voice_id = data.get("voice_id")
        print(f"✅ Голос успешно клонирован. ID: {voice_id}")
        return voice_id
    else:
        print(f"❌ Ошибка клонирования: {response.text}")
        return None
# === Обработка голосовых сообщений ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    if mode is None:
        await update.message.reply_text("⚠️ Сначала выберите режим с помощью /start.", reply_markup=back_button_markup)
        return

    # Скачиваем голосовое
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    # Конвертируем в wav для распознавания
    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            translated = GoogleTranslator(source='auto', target=TARGET_LANG).translate(text)

            # === Режим: просто перевод ===
            if mode == "mode_voice":
                await update.message.reply_text(
                    f"🗣 Распознано: {text}\n\n🌐 Перевод ({TARGET_LANG}): {translated}",
                    reply_markup=back_button_markup
                )

            # === Режим: перевод с озвучкой (gTTS) ===
            elif mode == "mode_voice_tts":
                tts = gTTS(translated, lang=TARGET_LANG)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name
                with open(tmp_file_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file, reply_markup=back_button_markup)
                os.remove(tmp_file_path)

            # === Режим: клонирование голоса ===
            elif mode == "mode_voice_clone":
                duration_sec = len(audio) / 1000
                if duration_sec < 30:
                    await update.message.reply_text(
                        "⚠️ Для клонирования голоса требуется минимум 30 секунд аудио.",
                        reply_markup=back_button_markup
                    )
                    return

                await update.message.reply_text("⏳ Приступаю к клонированию голоса...")
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                    audio.export(tmp_mp3.name, format="mp3")
                    mp3_path = tmp_mp3.name

                voice_id = await clone_user_voice(update.effective_user.id, mp3_path)

                if voice_id:
                    context.user_data["cloned_voice_id"] = voice_id
                    await update.message.reply_text("✅ Голос успешно клонирован и сохранён.")
                else:
                    await update.message.reply_text("❌ Ошибка при клонировании.")

                os.remove(mp3_path)

    except sr.UnknownValueError:
        await update.message.reply_text("Не удалось распознать речь.", reply_markup=back_button_markup)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}", reply_markup=back_button_markup)

# === Запуск бота ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Бот запущен...")
    app.run_polling()