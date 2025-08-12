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
import logging

# -------------------- Логирование --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- Переменные окружения --------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"
DEFAULT_TARGET = os.getenv("TARGET_LANG", "en")

# Проверка обязательных переменных окружения
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN is missing from environment variables!")
    exit(1)

recognizer = sr.Recognizer()

# -------------------- Список языков --------------------
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

# -------------------- Клавиатуры --------------------
def build_lang_keyboard(prefix: str):
    buttons = []
    row = []
    i = 0
    for name, code in LANGS.items():
        row.append(InlineKeyboardButton(name, callback_data=f"{prefix}{code}"))
        i += 1
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

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

# -------------------- /start --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    await update.message.reply_text(
        "👋 Welcome! Choose a mode. You can set 'From' and 'To' languages using the buttons below.",
        reply_markup=get_main_menu(),
    )

# -------------------- Обработка выбора режима --------------------
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("mode_"):
        context.user_data["mode"] = data
        mode_readable = {
            "mode_text": "Text → Translate",
            "mode_voice": "Voice → Translate",
            "mode_voice_tts": "Voice → Translate + TTS",
            "mode_voice_clone": "Voice cloning (experimental)",
        }.get(data, data)
        await query.edit_message_text(
            text=f"✅ Selected mode: *{mode_readable}*\n\nFrom: `{context.user_data.get('source_lang') or 'auto-detect'}`\nTo: `{context.user_data.get('target_lang')}`",
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON,
        )
        return

    if data == "change_source":
        await query.edit_message_text(
            text="Select source language:",
            reply_markup=build_lang_keyboard("src_"),
        )
        return

    if data == "change_target":
        await query.edit_message_text(
            text="Select target language:",
            reply_markup=build_lang_keyboard("tgt_"),
        )
        return

# -------------------- Обработка выбора языка --------------------
async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
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

    if data == "back_to_menu":
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

# -------------------- Обработка текста --------------------
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
        logger.error(f"Translation error: {e}")
        await update.message.reply_text(f"Translation error: {str(e)}", reply_markup=BACK_BUTTON)

# -------------------- Обработка голоса --------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode or not mode.startswith("mode_voice"):
        await update.message.reply_text("⚠️ Choose a voice mode first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    try:
        # Скачивание голосового файла
        voice = await update.message.voice.get_file()
        voice_file = BytesIO()
        await voice.download_to_memory(out=voice_file)
        voice_file.seek(0)

        # Конвертация из OGG в WAV
        audio = AudioSegment.from_ogg(voice_file)
        wav_io = BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)

        # Распознавание речи
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            try:
                sr_lang = None if src == "auto" else src
                text = recognizer.recognize_google(audio_data, language=sr_lang) if sr_lang else recognizer.recognize_google(audio_data)
            except sr.UnknownValueError:
                await update.message.reply_text("Could not understand audio.", reply_markup=BACK_BUTTON)
                return
            except sr.RequestError as e:
                logger.error(f"Speech recognition service error: {e}")
                await update.message.reply_text("Speech recognition service unavailable.", reply_markup=BACK_BUTTON)
                return

        # Перевод текста
        try:
            translated = GoogleTranslator(source=src if src != "auto" else "auto", target=tgt).translate(text)
        except Exception as e:
            logger.error(f"Translation error: {e}")
            await update.message.reply_text(f"Translation error: {str(e)}", reply_markup=BACK_BUTTON)
            return

        # Обработка в зависимости от режима
        if mode == "mode_voice":
            await update.message.reply_text(f"🗣 Recognized: {text}\n\n🌐 Translation ({src} → {tgt}): {translated}", reply_markup=BACK_BUTTON)

        elif mode == "mode_voice_tts":
            try:
                # Попытка создать TTS с полным языковым кодом
                try:
                    tts = gTTS(translated, lang=tgt)
                except:
                    # Если не удалось, используем только основную часть языкового кода
                    tts_lang = tgt.split("-")[0] if "-" in tgt else tgt
                    tts = gTTS(translated, lang=tts_lang)

                # Сохранение и отправка аудиофайла
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name

                with open(tmp_file_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file, reply_markup=BACK_BUTTON)
                
                # Удаление временного файла
                os.remove(tmp_file_path)
                
            except Exception as e:
                logger.error(f"TTS error: {e}")
                await update.message.reply_text(f"TTS generation error: {str(e)}", reply_markup=BACK_BUTTON)

        elif mode == "mode_voice_clone":
            if not ELEVENLABS_API_KEY:
                await update.message.reply_text("⚠️ ElevenLabs API key not configured.", reply_markup=BACK_BUTTON)
                return
                
            await update.message.reply_text("⏳ Preparing voice cloning...", reply_markup=BACK_BUTTON)
            duration_sec = len(audio) / 1000.0
            if duration_sec < 30:
                await update.message.reply_text("⚠️ Need at least 30 seconds of audio for cloning.", reply_markup=BACK_BUTTON)
                return

            # Сохранение аудио как MP3 для клонирования
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                audio.export(tmp_mp3.name, format="mp3")
                mp3_path = tmp_mp3.name

            try:
                # Клонирование или использование существующего голоса
                existing = context.user_data.get("cloned_voice_id")
                voice_id = existing or await clone_user_voice(update.effective_user.id, mp3_path)

                if voice_id:
                    context.user_data["cloned_voice_id"] = voice_id
                    
                    # Синтез речи с клонированным голосом
                    synth_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
                    payload = {"text": translated, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
                    
                    r = requests.post(synth_url, headers=headers, json=payload, timeout=60)
                    if r.status_code == 200:
                        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
                            tmp_out.write(r.content)
                            tmp_out_path = tmp_out.name

                        with open(tmp_out_path, "rb") as af:
                            await update.message.reply_voice(voice=af, reply_markup=BACK_BUTTON)
                        os.remove(tmp_out_path)
                    else:
                        logger.error(f"ElevenLabs synthesis error: {r.text}")
                        await update.message.reply_text(f"❌ Voice synthesis error: {r.status_code}", reply_markup=BACK_BUTTON)
                else:
                    await update.message.reply_text("❌ Voice cloning failed.", reply_markup=BACK_BUTTON)
                    
            except Exception as e:
                logger.error(f"Voice cloning error: {e}")
                await update.message.reply_text(f"❌ Voice cloning error: {str(e)}", reply_markup=BACK_BUTTON)
            finally:
                # Удаление временного файла
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)

    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await update.message.reply_text(f"Error processing voice message: {str(e)}", reply_markup=BACK_BUTTON)

# -------------------- Клонирование голоса --------------------
async def clone_user_voice(user_id: int, audio_file_path: str):
    if not ELEVENLABS_API_KEY:
        logger.error("ElevenLabs API key is missing.")
        return None

    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    voice_name = f"user_{user_id}_voice"
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            files = {
                "name": (None, voice_name),
                "files": (os.path.basename(audio_file_path), audio_file, "audio/mpeg"),
            }
            
            resp = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files, timeout=60)
            
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("voice_id") or data.get("id") or data.get("voice", {}).get("voice_id")
        else:
            logger.error(f"Cloning error {resp.status_code}: {resp.text}")
            return None
            
    except Exception as e:
        logger.error(f"Exception during cloning: {e}")
        return None

# -------------------- Запуск --------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|change_source|change_target)$"))
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^(src_|tgt_|back_to_menu)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("🤖 Bot started...")
    app.run_polling()