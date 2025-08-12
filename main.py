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
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVENLABS_VOICE_CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"

DEFAULT_TARGET = os.getenv("TARGET_LANG", "en")

recognizer = sr.Recognizer()

# Универсальная функция для безопасного создания меню
async def safe_send_menu(query_or_message, context, is_query=True):
    """Безопасно отправляет главное меню"""
    menu_text = get_status_text(context)
    menu_markup = get_main_menu()
    
    if is_query:
        query = query_or_message
        try:
            await query.edit_message_text(
                text=menu_text,
                parse_mode="Markdown", 
                reply_markup=menu_markup
            )
        except Exception:
            await query.answer("Opening menu...")
            await query.message.reply_text(
                text=menu_text,
                parse_mode="Markdown",
                reply_markup=menu_markup
            )
    else:
        message = query_or_message
        await message.reply_text(
            text=menu_text,
            parse_mode="Markdown",
            reply_markup=menu_markup
        )
LANGS = {
    "🇺🇸 English": "en",
    "🇷🇺 Русский": "ru", 
    "🇸🇦 العربية": "ar",
    "🇨🇳 中文 (简体)": "zh-CN",
    "🇹🇼 中文 (繁體)": "zh-TW",
    "🇪🇸 Español": "es",
    "🇫🇷 Français": "fr",
    "🇮🇹 Italiano": "it",
    "🇩🇪 Deutsch": "de",
    "🇵🇹 Português": "pt",
    "🇮🇳 हिन्दी": "hi",
    "🇦🇫 پښتو": "ps",
}

# Функция для получения красивого имени языка
def get_lang_display_name(code):
    for name, lang_code in LANGS.items():
        if lang_code == code:
            return name
    return code

# Функция для быстрого выбора популярных языков
def get_quick_lang_keyboard(prefix: str, show_skip=False):
    popular_langs = [
        ("🇺🇸 English", "en"),
        ("🇷🇺 Русский", "ru"),
        ("🇨🇳 中文", "zh-CN"),
        ("🇸🇦 العربية", "ar"),
        ("🇪🇸 Español", "es"),
        ("🇫🇷 Français", "fr"),
    ]
    
    buttons = []
    for i in range(0, len(popular_langs), 2):
        row = []
        for j in range(2):
            if i + j < len(popular_langs):
                name, code = popular_langs[i + j]
                row.append(InlineKeyboardButton(name, callback_data=f"{prefix}{code}"))
        buttons.append(row)
    
    # Кнопка "Больше языков"
    buttons.append([InlineKeyboardButton("🌍 More languages", callback_data=f"{prefix}more")])
    
    # Кнопка Skip для целевого языка (если уже выбран)
    if show_skip:
        buttons.append([InlineKeyboardButton("⏭️ Keep current target", callback_data="skip_target")])
    
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Полный список языков
def build_lang_keyboard(prefix: str):
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
    
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Главное меню с эмодзи и понятными описаниями
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📝 Translate Text", callback_data="mode_text")],
        [InlineKeyboardButton("🎤 Voice → Text Translation", callback_data="mode_voice")],
        [InlineKeyboardButton("🔊 Voice → Voice Translation", callback_data="mode_voice_tts")], 
        [InlineKeyboardButton("🎭 AI Voice Clone", callback_data="mode_voice_clone")],
        [
            InlineKeyboardButton("⚙️ Languages", callback_data="settings_menu"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Меню настроек языков
def get_settings_menu():
    keyboard = [
        [InlineKeyboardButton("🗣 Source Language (I speak)", callback_data="change_source")],
        [InlineKeyboardButton("🌐 Target Language (I want)", callback_data="change_target")],
        [InlineKeyboardButton("🔄 Reset Voice Clone", callback_data="reset_clone")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# Показать текущий статус пользователя
def get_status_text(context):
    src = context.user_data.get("source_lang")
    tgt = context.user_data.get("target_lang", DEFAULT_TARGET)
    mode = context.user_data.get("mode")
    cloned = "✅ Yes" if context.user_data.get("cloned_voice_id") else "❌ No"
    
    src_display = get_lang_display_name(src) if src else "🤖 Auto-detect"
    tgt_display = get_lang_display_name(tgt)
    
    mode_names = {
        "mode_text": "📝 Text Translation",
        "mode_voice": "🎤 Voice → Text",
        "mode_voice_tts": "🔊 Voice → Voice",
        "mode_voice_clone": "🎭 AI Voice Clone",
    }
    mode_display = mode_names.get(mode, "❌ Not selected")
    
    return f"""📊 **Current Status:**

🔧 **Mode:** {mode_display}
🗣 **From:** {src_display}
🌐 **To:** {tgt_display}
🎭 **Voice Cloned:** {cloned}

Choose an option below:"""

BACK_BUTTON = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    
    welcome_text = """🤖 **AI Translator & Voice Clone Bot**

I can help you:
• 📝 Translate text
• 🎤 Transcribe & translate voice  
• 🔊 Convert voice to different languages
• 🎭 Clone your voice for any language

Ready to start? Choose what you'd like to do:"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu(),
    )

# Handle mode selection callbacks
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Settings menu
    if data == "settings_menu":
        await query.edit_message_text(
            text=get_status_text(context),
            parse_mode="Markdown",
            reply_markup=get_settings_menu(),
        )
        return

    # Help
    if data == "help":
        help_text = """ℹ️ **How to use:**

📝 **Text Mode:** Just type any text
🎤 **Voice Mode:** Send voice message
🔊 **Voice+TTS:** Voice → Text → Voice  
🎭 **Voice Clone:** Your voice in any language

⚙️ **Tips:**
• Set source language for better accuracy
• Voice cloning needs 30+ seconds first time
• After cloning, any length works
• **Keep voice under 60s for best recognition**

🔧 **Troubleshooting:**
• Can't understand audio? Check source language
• Bad translation? Try different source language
• Clone failed? Send longer/clearer audio
• **Partial recognition? Audio too long (60s+ limit)**
• Text cut off? Split into shorter messages

⏱️ **Audio Limits:**
• 🎤 Recognition: ~60 seconds max
• 🎭 First clone: 30+ seconds required  
• 🔊 After clone: any length works"""
        
        await query.edit_message_text(
            text=help_text,
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON,
        )
        return

    # Reset voice clone
    if data == "reset_clone":
        context.user_data["cloned_voice_id"] = None
        await query.answer("Voice clone reset!")  # Используем answer вместо edit
        await query.edit_message_text(
            text="✅ Voice clone reset! Next voice message will create a new clone.",
            reply_markup=get_settings_menu(),
        )
        return

    # Set the chosen mode
    if data.startswith("mode_"):
        mode = data
        context.user_data["mode"] = mode
        
        # Показываем что выбрано и готовы к работе
        mode_descriptions = {
            "mode_text": "📝 **Text Translation**\n\nJust send me any text and I'll translate it!",
            "mode_voice": "🎤 **Voice → Text Translation**\n\nSend voice message and get text translation back.",
            "mode_voice_tts": "🔊 **Voice → Voice Translation**\n\nSend voice message and get translated voice back using Google TTS.",
            "mode_voice_clone": "🎭 **AI Voice Clone**\n\nSend voice message and get it back in your cloned voice speaking the translated text!\n\n⚠️ First time needs 30+ seconds to clone your voice.",
        }
        
        description = mode_descriptions.get(mode, "")
        status = get_status_text(context)
        
        await query.edit_message_text(
            text=f"{description}\n\n{status}",
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON,
        )
        return

    # Change source language
    if data == "change_source":
        await query.edit_message_text(
            text="🗣 **Select source language** (the language you speak):\n\n*Quick selection:*",
            parse_mode="Markdown",
            reply_markup=get_quick_lang_keyboard("src_"),
        )
        return

    # Change target language  
    if data == "change_target":
        await query.edit_message_text(
            text="🌐 **Select target language** (the language you want):\n\n*Quick selection:*",
            parse_mode="Markdown", 
            reply_markup=get_quick_lang_keyboard("tgt_"),
        )
        return

    # Back to menu  
    if data == "back_to_menu":
        context.user_data["mode"] = None
        await safe_send_menu(query, context, is_query=True)
        return

# Handle language selection callbacks for src_/tgt_
async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_menu":
        context.user_data["mode"] = None
        await safe_send_menu(query, context, is_query=True)
        return

    # Показать все языки
    if data in ["src_more", "tgt_more"]:
        prefix = data.replace("_more", "_")
        lang_type = "source" if prefix == "src_" else "target"
        await query.edit_message_text(
            text=f"🌍 **All {lang_type} languages:**",
            parse_mode="Markdown",
            reply_markup=build_lang_keyboard(prefix),
        )
        return

    # Skip target selection (keep current)
    if data == "skip_target":
        current_target = context.user_data.get("target_lang", DEFAULT_TARGET)
        target_name = get_lang_display_name(current_target)
        await query.edit_message_text(
            text=f"⏭️ **Keeping current target:** {target_name}\n\n🎯 **Setup complete!**\n\n{get_status_text(context)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

    if data.startswith("src_"):
        code = data[len("src_") :]
        context.user_data["source_lang"] = code
        lang_name = get_lang_display_name(code)
        
        # Проверяем есть ли уже целевой язык
        current_target = context.user_data.get("target_lang")
        show_skip = bool(current_target)
        
        # Предлагаем сразу выбрать целевой язык
        await query.edit_message_text(
            text=f"✅ **Source language set:** {lang_name}\n\n🌐 **Now select target language** (the language you want):\n\n*Quick selection:*",
            parse_mode="Markdown",
            reply_markup=get_quick_lang_keyboard("tgt_", show_skip=show_skip),
        )
        return

    if data.startswith("tgt_"):
        code = data[len("tgt_") :]
        context.user_data["target_lang"] = code
        lang_name = get_lang_display_name(code)
        
        # Показываем что настройка завершена и возвращаемся в главное меню
        await query.edit_message_text(
            text=f"✅ **Target language set:** {lang_name}\n\n🎯 **Setup complete!**\n\n{get_status_text(context)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        return

# Handle text messages (when mode_text is active)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode != "mode_text":
        await update.message.reply_text(
            "⚠️ **Text mode not active**\n\nPlease select 📝 'Translate Text' first.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    original_text = update.message.text
    
    # Показываем что происходит
    processing_msg = await update.message.reply_text("🔄 Translating...")
    
    try:
        translated = GoogleTranslator(source=src, target=tgt).translate(original_text)
        
        src_display = get_lang_display_name(src) if src != "auto" else "🤖 Auto-detect"
        tgt_display = get_lang_display_name(tgt)
        
        result_text = f"""📝 **Translation Complete**

🗣 **From** {src_display}:
{original_text}

🌐 **To** {tgt_display}:
{translated}"""

        await processing_msg.edit_text(result_text, parse_mode="Markdown", reply_markup=BACK_BUTTON)
        
    except Exception as e:
        await processing_msg.edit_text(f"❌ Translation error: {str(e)}", reply_markup=BACK_BUTTON)

# Helper: clone user's voice using ElevenLabs
async def clone_user_voice(user_id: int, audio_file_path: str, source_language: str = None):
    if not ELEVENLABS_API_KEY:
        print("ElevenLabs API key is missing.")
        return None

    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    voice_name = f"user_{user_id}_voice"
    
    description = f"Cloned voice for user {user_id}"
    if source_language:
        lang_name = get_lang_display_name(source_language)
        description += f" - Source: {lang_name}"

    files = {
        "name": (None, voice_name),
        "description": (None, description),
        "files": (os.path.basename(audio_file_path), open(audio_file_path, "rb"), "audio/mpeg"),
    }

    try:
        resp = requests.post(ELEVENLABS_VOICE_CLONE_URL, headers=headers, files=files, timeout=60)
        if resp.status_code in (200, 201):
            data = resp.json()
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
        await update.message.reply_text(
            "⚠️ **No mode selected**\n\nPlease choose what you want to do first:",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    # Показываем статус обработки
    processing_msg = await update.message.reply_text("🎧 Processing your voice message...")

    # Download voice file
    voice = await update.message.voice.get_file()
    voice_file = BytesIO()
    await voice.download_to_memory(out=voice_file)
    voice_file.seek(0)

    # Convert ogg -> wav
    audio = AudioSegment.from_ogg(voice_file)
    
    # Проверяем длительность и предупреждаем
    duration_sec = len(audio) / 1000.0
    if duration_sec > 55:  # Google limit ~60 seconds
        await processing_msg.edit_text("⚠️ **Long audio detected**\n\n🎤 Your audio: {:.1f}s\n⏱️ Google limit: ~60s\n\n📝 Only first part may be recognized...\n\n🔍 Processing...".format(duration_sec), parse_mode="Markdown")
    
    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        # Speech recognition
        await processing_msg.edit_text("🔍 Recognizing speech...")
        
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            recog_lang = None if src == "auto" else src
            
            if recog_lang and "-" in recog_lang:
                sr_lang = recog_lang
            elif recog_lang:
                sr_lang = recog_lang
            else:
                sr_lang = None

            if sr_lang:
                text = recognizer.recognize_google(audio_data, language=sr_lang)
            else:
                text = recognizer.recognize_google(audio_data)
                
    except sr.UnknownValueError:
        await processing_msg.edit_text(
            "❌ **Could not understand audio**\n\nTry:\n• Speaking more clearly\n• Checking source language\n• Recording in quieter environment\n• **Shorter messages (under 60s)**",
            parse_mode="Markdown",
            reply_markup=BACK_BUTTON
        )
        return
    except Exception as e:
        await processing_msg.edit_text(f"❌ Recognition error: {str(e)}", reply_markup=BACK_BUTTON)
        return

    # Translate
    try:
        await processing_msg.edit_text("🌐 Translating...")
        translated = GoogleTranslator(source=src if src != "auto" else "auto", target=tgt).translate(text)
    except Exception as e:
        await processing_msg.edit_text(f"❌ Translation error: {str(e)}", reply_markup=BACK_BUTTON)
        return

    # Respond based on mode
    try:
        src_display = get_lang_display_name(src) if src != "auto" else "🤖 Auto-detect"
        tgt_display = get_lang_display_name(tgt)
        
        if mode == "mode_voice":
            result_text = f"""🎤 **Voice Translation Complete**

🗣 **Recognized** ({src_display}):
{text}

🌐 **Translated** ({tgt_display}):
{translated}"""
            
            await processing_msg.edit_text(result_text, parse_mode="Markdown", reply_markup=BACK_BUTTON)

        elif mode == "mode_voice_tts":
            await processing_msg.edit_text("🔊 Generating voice...")
            
            tts_lang = tgt
            try:
                tts = gTTS(translated, lang=tts_lang)
            except Exception:
                tts = gTTS(translated, lang=tts_lang.split("-")[0])

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts.save(tmp_file.name)
                tmp_file_path = tmp_file.name

            # Удаляем processing message и отправляем результат
            await processing_msg.delete()
            
            caption = f"🔊 {src_display} → {tgt_display}"
            with open(tmp_file_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file, caption=caption, reply_markup=BACK_BUTTON)
                
            # Отправляем текст отдельно если он длинный
            if len(text) > 100 or len(translated) > 100:
                details = f"📝 **Details:**\n\n🗣 **Original:** {text}\n\n🌐 **Translated:** {translated}"
                await update.message.reply_text(details, parse_mode="Markdown")

            os.remove(tmp_file_path)

        elif mode == "mode_voice_clone":
            # Проверяем язык источника
            if not src or src == "auto":
                await processing_msg.edit_text(
                    "⚠️ **Source language required for cloning**\n\nPlease set a specific source language in ⚙️ Settings first.",
                    parse_mode="Markdown",
                    reply_markup=get_settings_menu()
                )
                return
                
            user_id = update.effective_user.id
            existing = context.user_data.get("cloned_voice_id")
            
            if existing:
                # Голос уже клонирован
                await processing_msg.edit_text("🎭 Using your cloned voice...")
                voice_id = existing
            else:
                # Нужно клонировать голос
                duration_sec = len(audio) / 1000.0
                if duration_sec < 30:
                    await processing_msg.edit_text(
                        f"⚠️ **Need longer audio for cloning**\n\nFirst clone needs 30+ seconds.\nYour audio: {duration_sec:.1f} seconds\n\nAfter first clone, any length works!",
                        parse_mode="Markdown",
                        reply_markup=BACK_BUTTON
                    )
                    return

                await processing_msg.edit_text("🧬 Cloning your voice... (this takes time)")
                
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
                    audio.export(tmp_mp3.name, format="mp3")
                    mp3_path = tmp_mp3.name

                voice_id = await clone_user_voice(user_id, mp3_path, src)
                
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)

            if voice_id:
                context.user_data["cloned_voice_id"] = voice_id
                
                # Обновляем или удаляем processing message
                try:
                    await processing_msg.edit_text("🎤 Generating cloned voice...")
                except:
                    # Если не удалось отредактировать, отправляем новое
                    await processing_msg.delete()
                    processing_msg = await update.message.reply_text("🎤 Generating cloned voice...")
                
                synth_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
                
                payload = {
                    "text": translated, 
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5, 
                        "similarity_boost": 0.75
                    }
                }
                
                if tgt in ["zh-CN", "zh-TW"]:
                    payload["voice_settings"]["style"] = 0.2
                    payload["voice_settings"]["use_speaker_boost"] = True
                
                print(f"Using voice_id: {voice_id} for synthesis")  # Отладка
                print(f"Payload: {payload}")  # Отладка
                
                r = requests.post(synth_url, headers=headers, json=payload)
                print(f"ElevenLabs response status: {r.status_code}")  # Отладка
                
                if r.status_code == 200:
                    tmp_out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp_out.write(r.content)
                    tmp_out.flush()
                    tmp_out_path = tmp_out.name
                    tmp_out.close()

                    # Удаляем processing message
                    try:
                        await processing_msg.delete()
                    except:
                        pass

                    # Отправляем результат
                    caption = f"🎭 Your voice: {src_display} → {tgt_display}"
                    with open(tmp_out_path, "rb") as af:
                        await update.message.reply_voice(voice=af, caption=caption, reply_markup=BACK_BUTTON)
                    
                    # Детали отдельно если текст длинный
                    info_text = f"📝 **Original:** {text}\n\n🌐 **Translated:** {translated}"
                    if len(info_text) > 500:
                        await update.message.reply_text(info_text, parse_mode="Markdown")
                    
                    # Отправляем новое меню для удобства
                    await safe_send_menu(update.message, context, is_query=False)

                    os.remove(tmp_out_path)
                else:
                    print(f"ElevenLabs error response: {r.text}")  # Отладка
                    await processing_msg.edit_text(f"❌ **Voice synthesis failed**\n\n{r.text}", parse_mode="Markdown", reply_markup=BACK_BUTTON)
            else:
                await processing_msg.edit_text("❌ **Voice cloning failed**\n\nTry recording clearer/longer audio.", parse_mode="Markdown", reply_markup=BACK_BUTTON)

    except Exception as e:
        await processing_msg.edit_text(f"❌ Error: {str(e)}", reply_markup=BACK_BUTTON)

# Entry point
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|settings_menu|change_source|change_target|back_to_menu|help|reset_clone)"))
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^(src_|tgt_|back_to_menu|skip_target)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot started...")
    app.run_polling()