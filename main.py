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
# Реферальная система и лимиты
FREE_VOICE_LIMIT = 3  # Лимит для обычных пользователей
PREMIUM_REFERRAL_CODES = {
    "blogger_alex": "Alex Tech",
    "blogger_maria": "Maria Voice", 
    "blogger_john": "John AI",
    "vip_access": "VIP User",
    # Добавляй сюда новые коды для блогеров
}

# Функция для проверки лимитов
def check_voice_limit(context, user_id):
    """Проверяет может ли пользователь использовать клонирование голоса"""
    # Проверяем премиум статус
    is_premium = context.user_data.get("is_premium", False)
    if is_premium:
        return True, None
    
    # Проверяем лимит для обычных пользователей
    voice_count = context.user_data.get("voice_cloning_count", 0)
    if voice_count >= FREE_VOICE_LIMIT:
        return False, f"""⚠️ **Free limit reached!**

🎭 You've used all {FREE_VOICE_LIMIT} free voice cloning attempts.

💫 **Get unlimited access:**
• Contact us for premium access
• Or ask your favorite tech blogger for a special link!

📱 **Free features still available:**
• Text translation
• Voice recognition  
• Basic voice-to-voice"""
    
    return True, None

def increment_voice_count(context):
    """Увеличивает счетчик использования клонирования"""
    if not context.user_data.get("is_premium", False):
        current = context.user_data.get("voice_cloning_count", 0)
        context.user_data["voice_cloning_count"] = current + 1

def get_remaining_attempts(context):
    """Возвращает количество оставшихся попыток"""
    if context.user_data.get("is_premium", False):
        return "Unlimited ✨"
    
    used = context.user_data.get("voice_cloning_count", 0)
    remaining = FREE_VOICE_LIMIT - used
    return max(0, remaining)
# Многоязычные тексты интерфейса с акцентом на клонирование
INTERFACE_TEXTS = {
    "en": {
        "welcome_title": "🎭✨ **AI VOICE CLONE BOT** ✨🎭",
        "welcome_text": "🌟 **Clone your voice and speak ANY language fluently!**\n\n🎭 **PREMIUM FEATURE:**\n• Clone your unique voice\n• Speak in perfect accent in any language\n• Keep your personality across languages\n\n📱 **Free Features:**\n• 📝 Basic text translation\n• 🎤 Voice recognition\n• 🔊 Simple text-to-speech\n\n✨ **Ready to clone your voice?**",
        
        # Новые тексты для клонирования
        "clone_info_title": "⭐ **VOICE CLONING - PREMIUM FEATURE** ⭐",
        "clone_info_text": """🎭 **What makes this special:**
• Your unique voice, not a robot
• Perfect accent in any target language  
• Maintains your speaking style and emotions
• Works with 50+ languages

🎯 **How it works:**
1. Record 30+ seconds in your native language
2. AI learns your voice characteristics  
3. Speak any text in perfect target language accent

💫 **Use cases:**
• Content creation in multiple languages
• Language learning with your own voice
• Professional voiceovers
• Personal messages to international friends

Ready to start?""",
        
        "clone_step1_title": "🎭 **Voice Clone Setup** (Step 1/2)",
        "clone_step1_text": "🗣️ **Select your native language:**\n\n*The language you'll record in (need 30+ seconds)*",
        
        "clone_step2_title": "🎭 **Voice Clone Setup** (Step 2/2)", 
        "clone_step2_text": "🎯 **Select target language:**\n\n*Your voice will speak this language*\n\n🗣️ **Your language:** {src_lang}",
        
        "clone_ready_title": "✅ **Voice Clone Ready!**",
        "clone_ready_text": """🎭 **Setup Complete:**
🗣️ **Your language:** {src_lang}
🎯 **Target language:** {tgt_lang}

📱 **Instructions:**
1. Record a voice message (30+ seconds for first clone)
2. Speak clearly in {src_lang}
3. AI will clone your voice speaking in {tgt_lang}

🎤 **Send your voice message now!**""",

        "separator_ignore": "This button does nothing",
        
        # Menu buttons
        "btn_translate_text": "📝 Translate Text",
        "btn_voice_text": "🎤 Voice → Text Translation",
        "btn_voice_voice": "🔊 Voice → Voice Translation", 
        "btn_voice_clone": "🎭 AI Voice Clone",
        "btn_languages": "⚙️ Languages",
        "btn_help": "ℹ️ Help",
        "btn_back": "🔙 Back to Menu",
        "btn_more_languages": "🌍 More languages",
        "btn_keep_target": "⏭️ Keep current target",
        
        # Settings menu
        "btn_source_lang": "🗣 Source Language (I speak)",
        "btn_target_lang": "🌐 Target Language (I want)",
        "btn_reset_clone": "🔄 Reset Voice Clone",
        "btn_change_interface": "🌐 Interface Language",
        
        # Status texts
        "status_title": "📊 **Current Status:**",
        "status_mode": "🔧 **Mode:**",
        "status_from": "🗣 **From:**",
        "status_to": "🌐 **To:**",
        "status_cloned": "🎭 **Voice Cloned:**",
        "status_footer": "Choose an option below:",
        
        "mode_text": "📝 Text Translation",
        "mode_voice": "🎤 Voice → Text",
        "mode_voice_tts": "🔊 Voice → Voice",
        "mode_voice_clone": "🎭 AI Voice Clone",
        "mode_not_selected": "❌ Not selected",
        "auto_detect": "🤖 Auto-detect",
        "yes": "✅ Yes",
        "no": "❌ No",
        
        # Mode descriptions (обновленные)
        "desc_text_mode": "📝 **Text Translation**\n\nSimple text translation between languages.\n\n*Free feature - basic functionality*",
        "desc_voice_mode": "🎤 **Voice → Text Translation**\n\nTranscribe voice and translate to text.\n\n*Free feature - basic functionality*",
        "desc_voice_tts_mode": "🔊 **Voice → Voice Translation**\n\nBasic voice translation with standard TTS.\n\n*Free feature - robotic voice*",
        
        # Language selection
        "select_source_lang": "🗣 **Select source language** (the language you speak):\n\n*Quick selection:*",
        "select_target_lang": "🌐 **Select target language** (the language you want):\n\n*Quick selection:*",
        "all_languages": "🌍 **All {lang_type} languages:**",
        "source_set": "✅ **Source language set:** {lang_name}\n\n🌐 **Now select target language** (the language you want):\n\n*Quick selection:*",
        "target_set": "✅ **Target language set:** {lang_name}\n\n🎯 **Setup complete!**",
        "keeping_target": "⏭️ **Keeping current target:** {lang_name}\n\n🎯 **Setup complete!**",
        
        # Processing messages
        "processing_voice": "🎧 Processing your voice message...",
        "translating": "🔄 Translating...",
        "recognizing": "🔍 Recognizing speech...",
        "generating_voice": "🔊 Generating voice...",
        "using_cloned_voice": "🎭 Using your cloned voice...",
        "cloning_voice": "🧬 Cloning your voice... (this takes time)",
        "generating_cloned": "🎤 Generating cloned voice...",
        
        # Results
        "translation_complete": "📝 **Translation Complete**",
        "voice_translation_complete": "🎤 **Voice Translation Complete**",
        "recognized": "🗣 **Recognized** ({src_lang}):",
        "translated": "🌐 **Translated** ({tgt_lang}):",
        "from_label": "🗣 **From** {src_lang}:",
        "to_label": "🌐 **To** {tgt_lang}:",
        "voice_caption": "🔊 {src_lang} → {tgt_lang}",
        "cloned_voice_caption": "🎭 Your voice: {src_lang} → {tgt_lang}",
        "details": "📝 **Details:**",
        "original": "🗣 **Original:** {text}",
        "translated_text": "🌐 **Translated:** {text}",
        
        # Errors and warnings
        "no_mode_selected": "⚠️ **No mode selected**\n\nPlease choose what you want to do first:",
        "text_mode_not_active": "⚠️ **Text mode not active**\n\nPlease select 📝 'Translate Text' first.",
        "long_audio_warning": "⚠️ **Long audio detected**\n\n🎤 Your audio: {duration:.1f}s\n⏱️ Google limit: ~60s\n\n📝 Only first part may be recognized...\n\n🔍 Processing...",
        "could_not_understand": "❌ **Could not understand audio**\n\nTry:\n• Speaking more clearly\n• Checking source language\n• Recording in quieter environment\n• **Shorter messages (under 60s)**",
        "recognition_error": "❌ Recognition error: {error}",
        "translation_error": "❌ Translation error: {error}",
        "source_lang_required": "⚠️ **Source language required for cloning**\n\nPlease set a specific source language in ⚙️ Settings first.",
        "need_longer_audio": "⚠️ **Need longer audio for cloning**\n\nFirst clone needs 30+ seconds.\nYour audio: {duration:.1f} seconds\n\nAfter first clone, any length works!",
        "voice_synthesis_failed": "❌ **Voice synthesis failed**\n\n{error}",
        "voice_cloning_failed": "❌ **Voice cloning failed**\n\nTry recording clearer/longer audio.",
        "clone_reset": "✅ Voice clone reset! Next voice message will create a new clone.",
        "voice_clone_reset_answer": "Voice clone reset!",
        "opening_menu": "Opening menu...",
        "error_occurred": "❌ Error: {error}",
        
        # Help text
        "help_title": "ℹ️ **How to use:**",
        "help_content": """🎭 **VOICE CLONING (Main Feature):**
1. Select Voice Clone from menu
2. Choose your language and target language
3. Record 30+ seconds clearly
4. Your voice is cloned!
5. Send any voice message - get it back in target language with YOUR voice

📝 **Other Features:**
• **Text Mode:** Type any text for translation
• **Voice Mode:** Voice recognition and translation
• **Voice+TTS:** Basic voice translation (robotic)

⚙️ **Tips:**
• Voice cloning needs 30+ seconds first time only
• After cloning, any voice length works
• Speak clearly for best results
• Use quiet environment for recording

🎯 **Voice Clone vs Regular TTS:**
• Voice Clone: YOUR unique voice in any language
• Regular TTS: Generic robotic voice

⏱️ **Limits:**
• First clone: 30+ seconds required
• Recognition: ~60 seconds max
• After clone: unlimited length""",
        
        # Interface language selection
        "select_interface_lang": "🌐 **Select interface language:**\n\nThis changes the bot's menu language (not translation languages):",
        
        # 🆕 НОВЫЕ КЛЮЧИ ДЛЯ РЕФЕРАЛЬНОЙ СИСТЕМЫ
        "limit_reached": """⚠️ **Free limit reached!**

🎭 You've used all {limit} free voice cloning attempts.

💫 **Get unlimited access:**
• Contact us for premium access  
• Or ask your favorite tech blogger for a special link!

📱 **Free features still available:**
• Text translation
• Voice recognition
• Basic voice-to-voice""",

        "premium_activated": """✨ **PREMIUM ACCESS ACTIVATED!** ✨

🎭 **Unlimited voice cloning**
🌟 **Referral code:** {code}
👤 **Blogger:** {blogger}

🚀 **You now have unlimited access to all features!**""",

        "attempts_remaining": "🎭 **Voice Clone Attempts:** {remaining}"
    },
    
    "ru": {
        "welcome_title": "🎭✨ **БОТ КЛОНИРОВАНИЯ ГОЛОСА** ✨🎭",
        "welcome_text": "🌟 **Клонируйте свой голос и говорите на ЛЮБОМ языке идеально!**\n\n🎭 **ПРЕМИУМ ФУНКЦИЯ:**\n• Клонируйте свой уникальный голос\n• Говорите с идеальным акцентом на любом языке\n• Сохраняйте свою личность во всех языках\n\n📱 **Бесплатные функции:**\n• 📝 Базовый перевод текста\n• 🎤 Распознавание речи\n• 🔊 Простой синтез речи\n\n✨ **Готовы клонировать свой голос?**",
        
        "clone_info_title": "⭐ **КЛОНИРОВАНИЕ ГОЛОСА - ПРЕМИУМ ФУНКЦИЯ** ⭐",
        "clone_info_text": """🎭 **Что делает это особенным:**
• Ваш уникальный голос, не робот
• Идеальный акцент на целевом языке
• Сохраняет ваш стиль речи и эмоции
• Работает с 50+ языками

🎯 **Как это работает:**
1. Запишите 30+ секунд на родном языке
2. ИИ изучает характеристики вашего голоса
3. Говорите любой текст с идеальным акцентом

💫 **Применение:**
• Создание контента на разных языках
• Изучение языков своим голосом
• Профессиональная озвучка
• Личные сообщения зарубежным друзьям

Готовы начать?""",
        
        "clone_step1_title": "🎭 **Настройка Клона Голоса** (Шаг 1/2)",
        "clone_step1_text": "🗣️ **Выберите ваш родной язык:**\n\n*Язык, на котором будете записывать (нужно 30+ секунд)*",
        
        "clone_step2_title": "🎭 **Настройка Клона Голоса** (Шаг 2/2)",
        "clone_step2_text": "🎯 **Выберите целевой язык:**\n\n*Ваш голос будет говорить на этом языке*\n\n🗣️ **Ваш язык:** {src_lang}",
        
        "clone_ready_title": "✅ **Клон Голоса Готов!**",
        "clone_ready_text": """🎭 **Настройка завершена:**
🗣️ **Ваш язык:** {src_lang}
🎯 **Целевой язык:** {tgt_lang}

📱 **Инструкции:**
1. Запишите голосовое сообщение (30+ секунд для первого клона)
2. Говорите чётко на {src_lang}
3. ИИ клонирует ваш голос для {tgt_lang}

🎤 **Отправьте голосовое сообщение сейчас!**""",

        "separator_ignore": "Эта кнопка ничего не делает",
        
        # Кнопки меню
        "btn_translate_text": "📝 Перевести Текст",
        "btn_voice_text": "🎤 Голос → Текст",
        "btn_voice_voice": "🔊 Голос → Голос", 
        "btn_voice_clone": "🎭 Клон Голоса ИИ",
        "btn_languages": "⚙️ Языки",
        "btn_help": "ℹ️ Помощь",
        "btn_back": "🔙 Назад в Меню",
        "btn_more_languages": "🌍 Больше языков",
        "btn_keep_target": "⏭️ Оставить текущий",
        
        # Settings menu
        "btn_source_lang": "🗣 Исходный Язык (Я говорю)",
        "btn_target_lang": "🌐 Целевой Язык (Хочу)",
        "btn_reset_clone": "🔄 Сбросить Клон Голоса",
        "btn_change_interface": "🌐 Язык Интерфейса",
        
        # Status texts
        "status_title": "📊 **Текущий Статус:**",
        "status_mode": "🔧 **Режим:**",
        "status_from": "🗣 **От:**",
        "status_to": "🌐 **К:**",
        "status_cloned": "🎭 **Голос Клонирован:**",
        "status_footer": "Выберите опцию ниже:",
        
        "mode_text": "📝 Перевод Текста",
        "mode_voice": "🎤 Голос → Текст",
        "mode_voice_tts": "🔊 Голос → Голос",
        "mode_voice_clone": "🎭 Клон Голоса ИИ",
        "mode_not_selected": "❌ Не выбрано",
        "auto_detect": "🤖 Авто-определение",
        "yes": "✅ Да", 
        "no": "❌ Нет",
        
        # Mode descriptions
        "desc_text_mode": "📝 **Перевод Текста**\n\nПростой перевод текста между языками.\n\n*Бесплатная функция - базовый функционал*",
        "desc_voice_mode": "🎤 **Голос → Текст**\n\nРаспознавание речи и перевод в текст.\n\n*Бесплатная функция - базовый функционал*",
        "desc_voice_tts_mode": "🔊 **Голос → Голос**\n\nБазовый голосовой перевод со стандартным TTS.\n\n*Бесплатная функция - роботизированный голос*",
        
        # Language selection
        "select_source_lang": "🗣 **Выберите исходный язык** (язык, на котором говорите):\n\n*Быстрый выбор:*",
        "select_target_lang": "🌐 **Выберите целевой язык** (язык, который хотите):\n\n*Быстрый выбор:*",
        "all_languages": "🌍 **Все {lang_type} языки:**",
        "source_set": "✅ **Исходный язык установлен:** {lang_name}\n\n🌐 **Теперь выберите целевой язык** (язык, который хотите):\n\n*Быстрый выбор:*",
        "target_set": "✅ **Целевой язык установлен:** {lang_name}\n\n🎯 **Настройка завершена!**",
        "keeping_target": "⏭️ **Оставляем текущий целевой:** {lang_name}\n\n🎯 **Настройка завершена!**",
        
        # Processing messages
        "processing_voice": "🎧 Обрабатываю ваше голосовое сообщение...",
        "translating": "🔄 Перевожу...",
        "recognizing": "🔍 Распознаю речь...",
        "generating_voice": "🔊 Генерирую голос...",
        "using_cloned_voice": "🎭 Использую ваш клонированный голос...",
        "cloning_voice": "🧬 Клонирую ваш голос... (это займет время)",
        "generating_cloned": "🎤 Генерирую клонированный голос...",
        
        # Results
        "translation_complete": "📝 **Перевод Завершен**",
        "voice_translation_complete": "🎤 **Голосовой Перевод Завершен**",
        "recognized": "🗣 **Распознано** ({src_lang}):",
        "translated": "🌐 **Переведено** ({tgt_lang}):",
        "from_label": "🗣 **От** {src_lang}:",
        "to_label": "🌐 **К** {tgt_lang}:",
        "voice_caption": "🔊 {src_lang} → {tgt_lang}",
        "cloned_voice_caption": "🎭 Ваш голос: {src_lang} → {tgt_lang}",
        "details": "📝 **Детали:**",
        "original": "🗣 **Оригинал:** {text}",
        "translated_text": "🌐 **Переведено:** {text}",
        
        # Errors and warnings
        "no_mode_selected": "⚠️ **Режим не выбран**\n\nПожалуйста, сначала выберите что хотите делать:",
        "text_mode_not_active": "⚠️ **Текстовый режим не активен**\n\nПожалуйста, сначала выберите 📝 'Перевести Текст'.",
        "long_audio_warning": "⚠️ **Обнаружена длинная аудиозапись**\n\n🎤 Ваше аудио: {duration:.1f}с\n⏱️ Лимит Google: ~60с\n\n📝 Может быть распознана только первая часть...\n\n🔍 Обрабатываю...",
        "could_not_understand": "❌ **Не удалось понять аудио**\n\nПопробуйте:\n• Говорить четче\n• Проверить исходный язык\n• Записать в тихой обстановке\n• **Короткие сообщения (до 60с)**",
        "recognition_error": "❌ Ошибка распознавания: {error}",
        "translation_error": "❌ Ошибка перевода: {error}",
        "source_lang_required": "⚠️ **Нужен исходный язык для клонирования**\n\nПожалуйста, сначала установите конкретный исходный язык в ⚙️ Настройках.",
        "need_longer_audio": "⚠️ **Нужно более длинное аудио для клонирования**\n\nДля первого клона нужно 30+ секунд.\nВаше аудио: {duration:.1f} секунд\n\nПосле первого клона работает любая длина!",
        "voice_synthesis_failed": "❌ **Не удалось синтезировать голос**\n\n{error}",
        "voice_cloning_failed": "❌ **Не удалось клонировать голос**\n\nПопробуйте записать четче/дольше.",
        "clone_reset": "✅ Клон голоса сброшен! Следующее голосовое сообщение создаст новый клон.",
        "voice_clone_reset_answer": "Клон голоса сброшен!",
        "opening_menu": "Открываю меню...",
        "error_occurred": "❌ Ошибка: {error}",
        
        # Help text
        "help_title": "ℹ️ **Как использовать:**",
        "help_content": """🎭 **КЛОНИРОВАНИЕ ГОЛОСА (Основная функция):**
1. Выберите Клон Голоса в меню
2. Выберите ваш язык и целевой язык  
3. Запишите 30+ секунд четко
4. Ваш голос клонирован!
5. Отправляйте любые голосовые - получайте обратно на целевом языке ВАШИМ голосом

📝 **Другие функции:**
• **Текст:** Печатайте текст для перевода
• **Голос:** Распознавание и перевод речи
• **Голос+TTS:** Базовый голосовой перевод (роботом)

⚙️ **Советы:**
• Клонирование требует 30+ секунд только первый раз
• После клонирования работает любая длина
• Говорите четко для лучших результатов
• Записывайте в тихом месте

🎯 **Клон Голоса против обычного TTS:**
• Клон Голоса: ВАШ уникальный голос на любом языке
• Обычный TTS: Общий роботизированный голос

⏱️ **Лимиты:**
• Первый клон: требует 30+ секунд
• Распознавание: ~60 секунд максимум
• После клона: без ограничений длины""",
        
        # Interface language selection
        "select_interface_lang": "🌐 **Выберите язык интерфейса:**\n\nЭто изменит язык меню бота (не языки перевода):",
        
        # 🆕 НОВЫЕ КЛЮЧИ ДЛЯ РЕФЕРАЛЬНОЙ СИСТЕМЫ
        "limit_reached": """⚠️ **Лимит исчерпан!**

🎭 Вы использовали все {limit} бесплатные попытки клонирования.

💫 **Получить безлимитный доступ:**
• Свяжитесь с нами для премиум доступа
• Или попросите у вашего любимого тех-блогера специальную ссылку!

📱 **Бесплатные функции доступны:**
• Перевод текста
• Распознавание речи  
• Базовый голосовой перевод""",

        "premium_activated": """✨ **ПРЕМИУМ ДОСТУП АКТИВИРОВАН!** ✨

🎭 **Безлимитное клонирование голоса**
🌟 **Реферальный код:** {code}
👤 **Блогер:** {blogger}

🚀 **Теперь у вас безлимитный доступ ко всем функциям!**""",

        "attempts_remaining": "🎭 **Попытки Клонирования:** {remaining}"
    },
    
    "es": {
        "welcome_title": "🎭✨ **BOT CLONADOR DE VOZ IA** ✨🎭",
        "welcome_text": "🌟 **¡Clona tu voz y habla CUALQUIER idioma perfectamente!**\n\n🎭 **FUNCIÓN PREMIUM:**\n• Clona tu voz única\n• Habla con acento perfecto en cualquier idioma\n• Mantén tu personalidad en todos los idiomas\n\n📱 **Funciones gratuitas:**\n• 📝 Traducción básica de texto\n• 🎤 Reconocimiento de voz\n• 🔊 Síntesis de voz simple\n\n✨ **¿Listo para clonar tu voz?**",
        "auto_detect": "🤖 Auto-detectar",
        "yes": "✅ Sí",
        "no": "❌ No",
        "help_title": "ℹ️ **Cómo usar:**",
        "help_content": "🎭 **CLONACIÓN DE VOZ:** Función principal del bot\n📝 **Otras funciones:** Traducción básica disponible",
        "select_interface_lang": "🌐 **Selecciona idioma de interfaz:**\n\nEsto cambia el idioma del menú (no los idiomas de traducción):",
        
        # 🆕 НОВЫЕ КЛЮЧИ ДЛЯ РЕФЕРАЛЬНОЙ СИСТЕМЫ
        "limit_reached": "⚠️ **¡Límite alcanzado!** Contacta para acceso premium.",
        "premium_activated": "✨ **¡ACCESO PREMIUM ACTIVADO!** ✨",  
        "attempts_remaining": "🎭 **Intentos:** {remaining}"
    }
}

# Функция получения локализованного текста
def get_text(context, key, **kwargs):
    """Получает локализованный текст для пользователя"""
    interface_lang = context.user_data.get("interface_lang", "en")
    
    # Если язык не поддерживается, используем английский
    if interface_lang not in INTERFACE_TEXTS:
        interface_lang = "en"
    
    # Получаем текст, если его нет - используем английский, если и его нет - возвращаем ключ
    text = INTERFACE_TEXTS.get(interface_lang, {}).get(key)
    if not text:
        text = INTERFACE_TEXTS.get("en", {}).get(key, key)
    
    # Подставляем параметры
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass  # Игнорируем ошибки форматирования
    
    return text

# Универсальная функция для безопасного создания меню
async def safe_send_menu(query_or_message, context, is_query=True):
    """Безопасно отправляет главное меню"""
    menu_text = get_status_text(context)
    menu_markup = get_main_menu(context)
    
    if is_query:
        query = query_or_message
        try:
            await query.edit_message_text(
                text=menu_text,
                parse_mode="Markdown", 
                reply_markup=menu_markup
            )
        except Exception:
            await query.answer(get_text(context, "opening_menu"))
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

# Языки интерфейса (поддерживаемые для UI)
INTERFACE_LANGS = {
    "🇺🇸 English": "en",
    "🇷🇺 Русский": "ru", 
    "🇪🇸 Español": "es",
}

# Функция для получения красивого имени языка
def get_lang_display_name(code):
    for name, lang_code in LANGS.items():
        if lang_code == code:
            return name
    return code

# Продолжение функции get_quick_lang_keyboard
def get_quick_lang_keyboard(context, prefix: str, show_skip=False):
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
    buttons.append([InlineKeyboardButton(get_text(context, "btn_more_languages"), callback_data=f"{prefix}more")])

    # Кнопка Skip для целевого языка (если уже выбран)
    if show_skip:
        buttons.append([InlineKeyboardButton(get_text(context, "btn_keep_target"), callback_data="skip_target")])

    buttons.append([InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Полный список языков
def build_lang_keyboard(context, prefix: str):
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
    
    buttons.append([InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# Пошаговый мастер настройки клонирования
def get_clone_step1_keyboard(context):
    """Шаг 1: Выбор языка источника для клонирования"""
    popular_langs = [
        ("🇺🇸 English", "en"),
        ("🇷🇺 Русский", "ru"),
        ("🇪🇸 Español", "es"),
        ("🇫🇷 Français", "fr"),
        ("🇩🇪 Deutsch", "de"),
        ("🇨🇳 中文", "zh-CN"),
    ]
    
    buttons = []
    for i in range(0, len(popular_langs), 2):
        row = []
        for j in range(2):
            if i + j < len(popular_langs):
                name, code = popular_langs[i + j]
                row.append(InlineKeyboardButton(name, callback_data=f"clone_src_{code}"))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton("🌍 More Languages", callback_data="clone_src_more")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def get_clone_step2_keyboard(context):
    """Шаг 2: Выбор целевого языка для клонирования"""
    popular_langs = [
        ("🇺🇸 English", "en"),
        ("🇷🇺 Русский", "ru"),
        ("🇪🇸 Español", "es"),
        ("🇫🇷 Français", "fr"),
        ("🇩🇪 Deutsch", "de"),
        ("🇨🇳 中文", "zh-CN"),
    ]
    
    buttons = []
    for i in range(0, len(popular_langs), 2):
        row = []
        for j in range(2):
            if i + j < len(popular_langs):
                name, code = popular_langs[i + j]
                row.append(InlineKeyboardButton(name, callback_data=f"clone_tgt_{code}"))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton("🌍 More Languages", callback_data="clone_tgt_more")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="mode_voice_clone")])
    return InlineKeyboardMarkup(buttons)

def get_clone_all_langs_keyboard(context, step):
    """Показать все языки для клонирования"""
    prefix = f"clone_{step}_"
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
    
    back_callback = "mode_voice_clone" if step == "src" else f"clone_step2"
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)

def get_interface_lang_keyboard():
    buttons = []
    for name, code in INTERFACE_LANGS.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"interface_{code}")])
    
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")])
    return InlineKeyboardMarkup(buttons)

# Главное меню с акцентом на клонирование голоса
def get_main_menu(context):
    keyboard = [
        # ✨ ПРЕМИУМ ФУНКЦИЯ - КЛОНИРОВАНИЕ ✨
        [InlineKeyboardButton("✨🎭 AI VOICE CLONE 🎭✨", callback_data="mode_voice_clone")],
        [InlineKeyboardButton("⭐ PREMIUM FEATURE ⭐", callback_data="clone_info")],
        
        # Разделитель
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="separator")],
        
        # Бесплатные функции (менее заметные)
        [InlineKeyboardButton("📝 Text Translation (Free)", callback_data="mode_text")],
        [
            InlineKeyboardButton("🎤 Voice→Text", callback_data="mode_voice"),
            InlineKeyboardButton("🔊 Voice→Voice", callback_data="mode_voice_tts")
        ],
        
        # Настройки внизу
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu(context):
    keyboard = [
        [InlineKeyboardButton(get_text(context, "btn_source_lang"), callback_data="change_source")],
        [InlineKeyboardButton(get_text(context, "btn_target_lang"), callback_data="change_target")],
        [InlineKeyboardButton(get_text(context, "btn_change_interface"), callback_data="change_interface")],
        [InlineKeyboardButton(get_text(context, "btn_reset_clone"), callback_data="reset_clone")],
        [InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# Показать текущий статус пользователя
def get_status_text(context):
    src = context.user_data.get("source_lang")
    tgt = context.user_data.get("target_lang", DEFAULT_TARGET)
    mode = context.user_data.get("mode")
    cloned = get_text(context, "yes") if context.user_data.get("cloned_voice_id") else get_text(context, "no")
    
    src_display = get_lang_display_name(src) if src else get_text(context, "auto_detect")
    tgt_display = get_lang_display_name(tgt)

    mode_names = {
        "mode_text": get_text(context, "mode_text"),
        "mode_voice": get_text(context, "mode_voice"),
        "mode_voice_tts": get_text(context, "mode_voice_tts"),
        "mode_voice_clone": get_text(context, "mode_voice_clone"),
    }
    mode_display = mode_names.get(mode, get_text(context, "mode_not_selected"))
    
    # НОВОЕ: Добавляем информацию о лимитах
    remaining = get_remaining_attempts(context)
    attempts_info = get_text(context, "attempts_remaining", remaining=remaining)

    return f"""{get_text(context, "status_title")}

{get_text(context, "status_mode")} {mode_display}
{get_text(context, "status_from")} {src_display}
{get_text(context, "status_to")} {tgt_display}
{get_text(context, "status_cloned")} {cloned}
{attempts_info}

{get_text(context, "status_footer")}"""


def get_back_button(context):
    return InlineKeyboardMarkup([[InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")]])

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Инициализация пользовательских данных
    context.user_data.setdefault("mode", None)
    context.user_data.setdefault("source_lang", None)
    context.user_data.setdefault("target_lang", DEFAULT_TARGET)
    context.user_data.setdefault("voice_cloning_count", 0)
    context.user_data.setdefault("is_premium", False)
    
    # Определяем язык интерфейса пользователя
    user_lang = update.effective_user.language_code or "en"
    supported_interface_langs = list(INTERFACE_LANGS.values())
    if user_lang not in supported_interface_langs:
        lang_base = user_lang.split('-')[0] if '-' in user_lang else user_lang
        if lang_base in supported_interface_langs:
            user_lang = lang_base
        else:
            user_lang = "en"
    
    context.user_data.setdefault("interface_lang", user_lang)
    
    # НОВОЕ: Обработка реферальных кодов
    args = context.args
    if args and len(args) > 0:
        referral_code = args[0]
        
        # Проверяем валидность реферального кода
        if referral_code in PREMIUM_REFERRAL_CODES:
            context.user_data["is_premium"] = True
            context.user_data["referral_code"] = referral_code
            context.user_data["blogger_name"] = PREMIUM_REFERRAL_CODES[referral_code]
            
            # Отправляем сообщение об активации премиума
            premium_msg = get_text(context, "premium_activated", 
                                 code=referral_code, 
                                 blogger=PREMIUM_REFERRAL_CODES[referral_code])
            
            await update.message.reply_text(
                premium_msg,
                parse_mode="Markdown"
            )
    
    # Обычное приветствие
    welcome_text = f"""{get_text(context, "welcome_title")}

{get_text(context, "welcome_text")}"""

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu(context),
    )
# Handle mode selection callbacks
async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # Игнорируем нажатие на разделитель
    if data == "separator":
        await query.answer(get_text(context, "separator_ignore"))
        return
    
    # Информация о клонировании
    if data == "clone_info":
        await query.edit_message_text(
            text=f"""{get_text(context, "clone_info_title")}

{get_text(context, "clone_info_text")}""",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Start Voice Clone", callback_data="mode_voice_clone")],
                [InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")]
            ]),
        )
        return
    
    # Settings menu
    if data == "settings_menu":
        await query.edit_message_text(
            text=get_status_text(context),
            parse_mode="Markdown",
            reply_markup=get_settings_menu(context),
        )
        return

    # Help
    if data == "help":
        help_text = f"""{get_text(context, "help_title")}

{get_text(context, "help_content")}"""

        await query.edit_message_text(
            text=help_text,
            parse_mode="Markdown",
            reply_markup=get_back_button(context),
        )
        return

    # Reset voice clone
    if data == "reset_clone":
        context.user_data["cloned_voice_id"] = None
        await query.answer(get_text(context, "voice_clone_reset_answer"))
        await query.edit_message_text(
            text=get_text(context, "clone_reset"),
            reply_markup=get_settings_menu(context),
        )
        return

    # Change interface language
    if data == "change_interface":
        await query.edit_message_text(
            text=get_text(context, "select_interface_lang"),
            parse_mode="Markdown",
            reply_markup=get_interface_lang_keyboard(),
        )
        return

    # Set the chosen mode - СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ КЛОНИРОВАНИЯ
    if data == "mode_voice_clone":
        # Запускаем пошаговый мастер клонирования
        await query.edit_message_text(
            text=f"""{get_text(context, "clone_step1_title")}

{get_text(context, "clone_step1_text")}""",
            parse_mode="Markdown",
            reply_markup=get_clone_step1_keyboard(context),
        )
        return
    
    # Остальные режимы (обычная обработка)
    if data.startswith("mode_"):
        mode = data
        context.user_data["mode"] = mode
        
        # Показываем что выбрано и готовы к работе
        mode_descriptions = {
            "mode_text": get_text(context, "desc_text_mode"),
            "mode_voice": get_text(context, "desc_voice_mode"),
            "mode_voice_tts": get_text(context, "desc_voice_tts_mode"),
        }
        
        description = mode_descriptions.get(mode, "")
        status = get_status_text(context)
        
        await query.edit_message_text(
            text=f"{description}\n\n{status}",
            parse_mode="Markdown",
            reply_markup=get_back_button(context),
        )
        return

    # Change source language
    if data == "change_source":
        await query.edit_message_text(
            text=get_text(context, "select_source_lang"),
            parse_mode="Markdown",
            reply_markup=get_quick_lang_keyboard(context, "src_"),
        )
        return

    # Change target language  
    if data == "change_target":
        await query.edit_message_text(
            text=get_text(context, "select_target_lang"),
            parse_mode="Markdown", 
            reply_markup=get_quick_lang_keyboard(context, "tgt_"),
        )
        return

    # Back to menu  
    if data == "back_to_menu":
        context.user_data["mode"] = None
        await safe_send_menu(query, context, is_query=True)
        return
# Handle clone setup steps
async def handle_clone_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "clone_step2":
        src_lang = get_lang_display_name(context.user_data.get("source_lang", ""))
        await query.edit_message_text(
            text=get_text(context, "clone_step2_text", src_lang=src_lang),
            parse_mode="Markdown",
            reply_markup=get_clone_step2_keyboard(context),
        )
        return
    
    # Показать все языки для шага 1
    if data == "clone_src_more":
        await query.edit_message_text(
            text=f"""{get_text(context, "clone_step1_title")}

🌍 **All languages:**""",
            parse_mode="Markdown",
            reply_markup=get_clone_all_langs_keyboard(context, "src"),
        )
        return
    
    # Показать все языки для шага 2
    if data == "clone_tgt_more":
        src_lang = get_lang_display_name(context.user_data.get("source_lang", ""))
        await query.edit_message_text(
            text=f"""{get_text(context, "clone_step2_title")}

🌍 **All languages:**

🗣️ **Your language:** {src_lang}""",
            parse_mode="Markdown",
            reply_markup=get_clone_all_langs_keyboard(context, "tgt"),
        )
        return
    
    # Выбран исходный язык
    if data.startswith("clone_src_"):
        code = data[len("clone_src_"):]
        context.user_data["source_lang"] = code
        lang_name = get_lang_display_name(code)
        
        # Переходим к шагу 2
        await query.edit_message_text(
            text=get_text(context, "clone_step2_text", src_lang=lang_name),
            parse_mode="Markdown",
            reply_markup=get_clone_step2_keyboard(context),
        )
        return
    
    # Выбран целевой язык - ЗАВЕРШЕНИЕ НАСТРОЙКИ
    if data.startswith("clone_tgt_"):
        code = data[len("clone_tgt_"):]
        context.user_data["target_lang"] = code
        context.user_data["mode"] = "mode_voice_clone"  # Устанавливаем режим
        
        src_lang = get_lang_display_name(context.user_data.get("source_lang"))
        tgt_lang = get_lang_display_name(code)
        
        # Показываем финальный экран с инструкциями
        await query.edit_message_text(
            text=get_text(context, "clone_ready_text", src_lang=src_lang, tgt_lang=tgt_lang),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Change Languages", callback_data="mode_voice_clone")],
                [InlineKeyboardButton(get_text(context, "btn_back"), callback_data="back_to_menu")]
            ]),
        )
        return

# Handle interface language changes
async def handle_interface_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_to_settings":
        await query.edit_message_text(
            text=get_status_text(context),
            parse_mode="Markdown",
            reply_markup=get_settings_menu(context),
        )
        return
    
    if data.startswith("interface_"):
        lang_code = data[len("interface_"):]
        context.user_data["interface_lang"] = lang_code
        
        # Показываем подтверждение на новом языке
        await query.edit_message_text(
            text=f"✅ {get_text(context, 'status_title')}\n\n{get_status_text(context)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(context),
        )
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
            text=get_text(context, "all_languages", lang_type=lang_type),
            parse_mode="Markdown",
            reply_markup=build_lang_keyboard(context, prefix),
        )
        return

    # Skip target selection (keep current)
    if data == "skip_target":
        current_target = context.user_data.get("target_lang", DEFAULT_TARGET)
        target_name = get_lang_display_name(current_target)
        await query.edit_message_text(
            text=get_text(context, "keeping_target", lang_name=target_name) + f"\n\n{get_status_text(context)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(context),
        )
        return

    if data.startswith("src_"):
        code = data[len("src_"):]
        context.user_data["source_lang"] = code
        lang_name = get_lang_display_name(code)
        
        # Проверяем есть ли уже целевой язык
        current_target = context.user_data.get("target_lang")
        show_skip = bool(current_target)
        
        # Предлагаем сразу выбрать целевой язык
        await query.edit_message_text(
            text=get_text(context, "source_set", lang_name=lang_name),
            parse_mode="Markdown",
            reply_markup=get_quick_lang_keyboard(context, "tgt_", show_skip=show_skip),
        )
        return

    if data.startswith("tgt_"):
        code = data[len("tgt_"):]
        context.user_data["target_lang"] = code
        lang_name = get_lang_display_name(code)
        
        # Показываем что настройка завершена и возвращаемся в главное меню
        await query.edit_message_text(
            text=get_text(context, "target_set", lang_name=lang_name) + f"\n\n{get_status_text(context)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(context),
        )
        return

# Handle text messages (when mode_text is active)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode != "mode_text":
        await update.message.reply_text(
            get_text(context, "text_mode_not_active"),
            parse_mode="Markdown",
            reply_markup=get_main_menu(context)
        )
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    original_text = update.message.text

    # Показываем что происходит
    processing_msg = await update.message.reply_text(get_text(context, "translating"))

    try:
        translated = GoogleTranslator(source=src, target=tgt).translate(original_text)
        
        src_display = get_lang_display_name(src) if src != "auto" else get_text(context, "auto_detect")
        tgt_display = get_lang_display_name(tgt)
        
        result_text = f"""{get_text(context, "translation_complete")}

{get_text(context, "from_label", src_lang=src_display)}
{original_text}

{get_text(context, "to_label", tgt_lang=tgt_display)}
{translated}"""

        await processing_msg.edit_text(result_text, parse_mode="Markdown", reply_markup=get_back_button(context))
        
    except Exception as e:
        await processing_msg.edit_text(get_text(context, "translation_error", error=str(e)), reply_markup=get_back_button(context))

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
    finally:
        # Закрываем файл если он открыт
        if 'files' in locals() and 'files' in files:
            try:
                files['files'][1].close()
            except:
                pass

# Handle voice messages
# Handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text(
            get_text(context, "no_mode_selected"),
            parse_mode="Markdown",
            reply_markup=get_main_menu(context)
        )
        return

    src = context.user_data.get("source_lang") or "auto"
    tgt = context.user_data.get("target_lang") or DEFAULT_TARGET

    # Показываем статус обработки
    processing_msg = await update.message.reply_text(get_text(context, "processing_voice"))

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
        await processing_msg.edit_text(
            get_text(context, "long_audio_warning", duration=duration_sec), 
            parse_mode="Markdown"
        )

    wav_io = BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        # Speech recognition
        await processing_msg.edit_text(get_text(context, "recognizing"))
        
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
            get_text(context, "could_not_understand"),
            parse_mode="Markdown",
            reply_markup=get_back_button(context)
        )
        return
    except Exception as e:
        await processing_msg.edit_text(
            get_text(context, "recognition_error", error=str(e)), 
            reply_markup=get_back_button(context)
        )
        return

    # Translate
    try:
        await processing_msg.edit_text(get_text(context, "translating"))
        translated = GoogleTranslator(source=src if src != "auto" else "auto", target=tgt).translate(text)
    except Exception as e:
        await processing_msg.edit_text(
            get_text(context, "translation_error", error=str(e)), 
            reply_markup=get_back_button(context)
        )
        return

    # Respond based on mode
    try:
        src_display = get_lang_display_name(src) if src != "auto" else get_text(context, "auto_detect")
        tgt_display = get_lang_display_name(tgt)
        
        if mode == "mode_voice":
            result_text = f"""{get_text(context, "voice_translation_complete")}

{get_text(context, "recognized", src_lang=src_display)}
{text}

{get_text(context, "translated", tgt_lang=tgt_display)}
{translated}"""

            await processing_msg.edit_text(result_text, parse_mode="Markdown", reply_markup=get_back_button(context))

        elif mode == "mode_voice_tts":
            await processing_msg.edit_text(get_text(context, "generating_voice"))
            
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
            
            caption = get_text(context, "voice_caption", src_lang=src_display, tgt_lang=tgt_display)
            with open(tmp_file_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file, caption=caption, reply_markup=get_back_button(context))
                
            # Отправляем текст отдельно если он длинный
            if len(text) > 100 or len(translated) > 100:
                details = f"""{get_text(context, "details")}

{get_text(context, "original", text=text)}

{get_text(context, "translated_text", text=translated)}"""
                await update.message.reply_text(details, parse_mode="Markdown")

            os.remove(tmp_file_path)

        elif mode == "mode_voice_clone":
            # Проверяем язык источника
            if not src or src == "auto":
                await processing_msg.edit_text(
                    get_text(context, "source_lang_required"),
                    parse_mode="Markdown",
                    reply_markup=get_settings_menu(context)
                )
                return
            
            # 🆕 ИСПРАВЛЕНО: Проверяем лимиты перед КАЖДЫМ использованием
            user_id = update.effective_user.id
            can_use, limit_msg = check_voice_limit(context, user_id)
            
            if not can_use:
                await processing_msg.edit_text(
                    limit_msg,
                    parse_mode="Markdown",
                    reply_markup=get_back_button(context)
                )
                return
            
            # 🆕 ИСПРАВЛЕНО: Увеличиваем счетчик перед обработкой (не только при клонировании)
            increment_voice_count(context)
                
            existing = context.user_data.get("cloned_voice_id")
            
            if existing:
                # Голос уже клонирован
                await processing_msg.edit_text(get_text(context, "using_cloned_voice"))
                voice_id = existing
            else:
                # Нужно клонировать голос
                duration_sec = len(audio) / 1000.0
                if duration_sec < 30:
                    await processing_msg.edit_text(
                        get_text(context, "need_longer_audio", duration=duration_sec),
                        parse_mode="Markdown",
                        reply_markup=get_back_button(context)
                    )
                    return

                await processing_msg.edit_text(get_text(context, "cloning_voice"))
                
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
                    await processing_msg.edit_text(get_text(context, "generating_cloned"))
                except:
                    # Если не удалось отредактировать, отправляем новое
                    await processing_msg.delete()
                    processing_msg = await update.message.reply_text(get_text(context, "generating_cloned"))
                
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
                
                print(f"Using voice_id: {voice_id} for synthesis")
                print(f"Payload: {payload}")
                
                r = requests.post(synth_url, headers=headers, json=payload)
                print(f"ElevenLabs response status: {r.status_code}")
                
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
                    caption = get_text(context, "cloned_voice_caption", src_lang=src_display, tgt_lang=tgt_display)
                    with open(tmp_out_path, "rb") as af:
                        await update.message.reply_voice(voice=af, caption=caption, reply_markup=get_back_button(context))
                    
                    # Детали отдельно если текст длинный
                    info_text = f"""{get_text(context, "original", text=text)}

{get_text(context, "translated_text", text=translated)}"""
                    if len(info_text) > 500:
                        await update.message.reply_text(info_text, parse_mode="Markdown")
                    
                    # Отправляем новое меню для удобства
                    await safe_send_menu(update.message, context, is_query=False)

                    os.remove(tmp_out_path)
                else:
                    print(f"ElevenLabs error response: {r.text}")
                    await processing_msg.edit_text(
                        get_text(context, "voice_synthesis_failed", error=r.text), 
                        parse_mode="Markdown", 
                        reply_markup=get_back_button(context)
                    )
            else:
                await processing_msg.edit_text(
                    get_text(context, "voice_cloning_failed"), 
                    parse_mode="Markdown", 
                    reply_markup=get_back_button(context)
                )
    except Exception as e:
        await processing_msg.edit_text(
            get_text(context, "error_occurred", error=str(e)), 
            reply_markup=get_back_button(context)
        )
# Entry point
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_mode_selection, pattern="^(mode_|settings_menu|change_source|change_target|back_to_menu|help|reset_clone|change_interface|clone_info|separator)"))
    app.add_handler(CallbackQueryHandler(handle_clone_setup, pattern="^(clone_src_|clone_tgt_|clone_.*_more)"))
    app.add_handler(CallbackQueryHandler(handle_interface_lang, pattern="^(interface_|back_to_settings)"))
    app.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^(src_|tgt_|back_to_menu|skip_target)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot started...")
    app.run_polling()