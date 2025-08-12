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
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")  # ElevenLabs API key (if you use cloning)
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"

# Default target language if not chosen
DEFAULT_TARGET = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

# -------------------------
# Supported languages mapping
# display name -> translation/tts/eleven-code
# Add or remove languages here as you need
# -------------------------
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
    # add more as required...
}

# Utility to build keyboard of language options (returns InlineKeyboardMarkup)
def build_lang_keyboard(prefix: str):
    # prefix should be 'src_' or 'tgt_' to distinguish callbacks
    buttons = []
    row = []
    i = 0
    for name, code in LANGS.items():
        cb = f"{prefix}{code}"
        row.append(InlineKeyboardButton(name, callback_data=cb))
        i += 1
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # add Back to main menu button
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Main menu (re-usable)
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

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Initialize user state
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    await update.message.reply_text(
        "👋 Welcome! Choose a mode. You can set 'From' and 'To' languages using the buttons below.",
        reply_markup=get_main_menu(),
    )

# Handle mode selection callbacks
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Set the chosen mode
    if data.startswith("mode_"):
        mode = data  # mode_text / mode_voice / mode_voice_tts / mode_voice_clone
        context.user_data["mode"] = mode
        mode_readable = {
            "mode_text": "Text → Translate",
            "mode_voice": "Voice → Translate",
            "mode_voice_tts": "Voice → Translate + TTS",
            "mode_voice_clone": "Voice cloning (experimental)",
        }.get(mode, mode)
        # Inform the user and show Back button
        await query.edit_message_text(
            text=f"✅ Selected mode: *{mode_readable}*\n\nFrom: `{context.user_data.get('source_lang') or 'auto-detect'}`\nTo: `{context.user_data.get('target_lang')}`",
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON,
        )
        return

    # Change source language
    if data == "change_source":
        await query.edit_message_text(
            text="Select source language (the language you will speak/type):",
            reply_markup=build_lang_keyboard("src_"),
        )
        return

    # Change target language
    if data == "change_target":
        await query.edit_message_text(
            text="Select target language (the language you want to receive):",
            reply_markup=build_lang_keyboard("tgt_"),
        )
        return

    # Back to menu
    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

# Handle language selection callbacks for src_/tgt_
async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("Main menu:", reply_markup=get_main_menu())
        return

    if data.startswith("src_"):
        code = data[len("src_") :]
        context.user_data["source_lang"] = code
        await query.edit_message_text(
            text=f"✅ Source language set to `{code}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

    if data.startswith("tgt_"):
        code = data[len("tgt_") :]
        context.user_data["target_lang"] = code
        await query.edit_message_text(
            text=f"✅ Target language set to `{code}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

# Handle text messages (when mode_text is active)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode != "mode_text":
        await update.message.reply_text("⚠️ Please select the mode 'Text → Translate' first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    original_text = update.message.text
    try:
        # translate using deep_translator GoogleTranslator
        translated = GoogleTranslator(source=src, target=tgt).translate(original_text)
        await update.message.reply_text(f"🌐 Translation ({src} → {tgt}):\n\n{translated}", reply_markup=BACK_BUTTON)
    except Exception as e:
        await update.message.reply_text(f"Translation error: {str(e)}", reply_markup=BACK_BUTTON)

# Helper: clone user's voice using ElevenLabs (synchronous request)
async def clone_user_voice(user_id: int, audio_file_path: str, source_language: str = None):
    if not ELEVENLABS_API_KEY:
        print("ElevenLabs API key is missing.")
        return None

    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    voice_name = f"user_{user_id}_voice"
    
    # Добавляем информацию о языке в описание голоса
    description = f"Cloned voice for user {user_id}"
    if source_language:
        lang_name = [name for name, code in LANGS.items() if code == source_language]
        if lang_name:
            description += f" - Source language: {lang_name[0]} ({source_language})"

    files = {
        "name": (None, voice_name),
        "description": (None, description),  # Добавляем описание с языком
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg"),
    }

    try:
        resp = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files, timeout=60)
        if resp.status_code in (200, 201):
            data = resp.json()
            # Attempt to locate voice id in response
            voice_id = data.get("voice_id") or data.get("id") or data.get("voice", {}).get("voice_id")
            print(f"Voice cloned with source language {source_language}: {voice_id}")
            return voice_id
        else:
            print(f"❌ Cloning error: {resp.text}")
            return None
    except Exception as e:
        print(f"Exception during cloning: {e}")
        return None

# Handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("⚠️ Choose a mode first (/start).", reply_markup=BACK_BUTTON)
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    # Download voice file
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    # download_to_memory is supported in PTB File object
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    # Convert ogg -> wav
    audio = AudioSegment.from_ogg(voice_file)
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        # Speech recognition
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            # If user set explicit source language, use it; otherwise use 'ru-RU' by default if src=='auto' use 'auto' and let recognizer default
            recog_lang = None if src == "auto" else src
            if recog_lang and "-" in recog_lang:
                # speech_recognition expects codes like 'ru-RU'; convert 'zh-CN' -> 'zh-CN' OK, 'ps' -> 'ps' may not be supported
                sr_lang = recog_lang
            elif recog_lang:
                # try two-letter to sr format
                sr_lang = recog_lang
            else:
                sr_lang = None

            if sr_lang:
                text = recognizer.recognize_google(audio_data, language=sr_lang)
            else:
                text = recognizer.recognize_google(audio_data)  # autos
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

    # Respond based on mode
    try:
        if mode == "mode_voice":
            await update.message.reply_text(f"🗣 Recognized: {text}\n\n🌐 Translation ({src} → {tgt}): {translated}", reply_markup=BACK_BUTTON)

        elif mode == "mode_voice_tts":
            # Generate TTS with gTTS (may not support all codes; gTTS uses language codes like 'zh-CN' -> 'zh-cn' sometimes)
            tts_lang = tgt
            # gTTS expects e.g. 'zh-CN' as 'zh-cn' sometimes — try direct first
            try:
                tts = gTTS(translated, lang=tts_lang)
            except Exception:
                # fallback to two-letter
                tts = gTTS(translated, lang=tts_lang.split("-")[0])

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts.save(tmp_file.name)
                tmp_file_path = tmp_file.name

            with open(tmp_file_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file, reply_markup=BACK_BUTTON)

            os.remove(tmp_file_path)

        elif mode == "mode_voice_clone":
            # ПРОВЕРКА: убеждаемся что пользователь выбрал исходный язык
            if not src or src == "auto":
                await update.message.reply_text("⚠️ For voice cloning, please select a specific source language first. Use 'Change source language' button.", reply_markup=BACK_BUTTON)
                return
                
            await update.message.reply_text(f"⏳ Preparing voice cloning from {src} to {tgt}... this may take a while.", reply_markup=BACK_BUTTON)

            # voice cloning requires ElevenLabs subscription & API key
            # Ensure sample length at least 30s
            duration_sec = len(audio) / 1000.0
            if duration_sec < 30:
                await update.message.reply_text("⚠️ For voice cloning we need at least 30 seconds of audio. Please send longer sample.", reply_markup=BACK_BUTTON)
                return

            # Save temp mp3 to upload
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                audio.export(tmp_mp3.name, format="mp3")
                mp3_path = tmp_mp3.name

            # Try to reuse existing cloned voice id for this user
            user_id = update.effective_user.id
            existing = context.user_data.get("cloned_voice_id")
            if existing:
                voice_id = existing
            else:
                # передаем информацию о языке источника при клонировании
                voice_id = await clone_user_voice(user_id, mp3_path, src)

            if voice_id:
                context.user_data["cloned_voice_id"] = voice_id
                
                synth_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
                
                # используем multilingual модель и указываем язык
                payload = {
                    "text": translated, 
                    "model_id": "eleven_multilingual_v2",  # Поддерживает много языков
                    "voice_settings": {
                        "stability": 0.5, 
                        "similarity_boost": 0.75
                    }
                }
                
                # для некоторых языков добавляем дополнительные параметры
                if tgt in ["zh-CN", "zh-TW"]:
                    payload["voice_settings"]["style"] = 0.2
                    payload["voice_settings"]["use_speaker_boost"] = True
                
                r = requests.post(synth_url, headers=headers, json=payload)
                if r.status_code == 200:
                    tmp_out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp_out.write(r.content)
                    tmp_out.flush()
                    tmp_out_path = tmp_out.name
                    tmp_out.close()

                    # Отправляем информацию отдельным сообщением чтобы избежать лимита caption
                    info_text = f"🎤 Source language: {src}\n🗣 Recognized: {text}\n🌐 Translated to {tgt}: {translated}"
                    
                    # Проверяем длину caption и обрезаем если нужно
                    if len(info_text) > 1000:  # Оставляем запас
                        short_info = f"🎤 {src} → {tgt} (voice cloned)"
                        await update.message.reply_text(info_text, reply_markup=BACK_BUTTON)
                        with open(tmp_out_path, "rb") as af:
                            await update.message.reply_voice(voice=af, caption=short_info)
                    else:
                        with open(tmp_out_path, "rb") as af:
                            await update.message.reply_voice(voice=af, caption=info_text, reply_markup=BACK_BUTTON)

                    os.remove(tmp_out_path)
                else:
                    await update.message.reply_text(f"❌ Cloning/TTS error: {r.text}", reply_markup=BACK_BUTTON)
            else:
                await update.message.reply_text("❌ Voice cloning failed.", reply_markup=BACK_BUTTON)

            # cleanup sample
            if os.path.exists(mp3_path):
                os.remove(mp3_path)

    except Exception as e:
        await update.message.reply_text(f"Error while responding: {str(e)}", reply_markup=BACK_BUTTON)

# Entry point
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Command /start
    app.add_handler(CommandHandler("start", start))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|change_source|change_target|back_to_menu)"))
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^(src_|tgt_|back_to_menu)"))

    # Messages handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot started...")
    app.run_polling()