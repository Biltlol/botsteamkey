import os
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN')  # Токен бота из @BotFather
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')  # Ваш Gmail
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')  # Пароль приложения Gmail
CORRECT_PASSWORD = "N55epe7red67av48ai8poroli"

# Хранилище авторизованных пользователей (в памяти)
authorized_users = set()

def check_steam_email():
    """Проверяет почту на наличие кодов от Steam"""
    try:
        # Подключение к Gmail
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        mail.select("inbox")
        
        # Поиск писем от Steam за последние 10 минут
        date = (datetime.now() - timedelta(minutes=10)).strftime("%d-%b-%Y")
        result, data = mail.search(None, f'(FROM "noreply@steampowered.com" SINCE {date})')
        
        if result != 'OK':
            return None
            
        email_ids = data[0].split()
        if not email_ids:
            return None
        
        # Проверяем последнее письмо
        latest_email_id = email_ids[-1]
        result, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        
        if result != 'OK':
            return None
            
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        
        # Получаем текст письма
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
                    break
        else:
            body = msg.get_payload(decode=True).decode()
        
        # Ищем код (обычно 5 символов)
        code_match = re.search(r'\b([A-Z0-9]{5})\b', body)
        if code_match:
            code = code_match.group(1)
            
            # Проверяем время письма
            date_str = msg.get("Date")
            email_time = email.utils.parsedate_to_datetime(date_str)
            time_diff = datetime.now(email_time.tzinfo) - email_time
            
            if time_diff < timedelta(minutes=10):
                mail.close()
                mail.logout()
                return {
                    'code': code,
                    'time': email_time.strftime("%H:%M:%S"),
                    'body_preview': body[:200]
                }
        
        mail.close()
        mail.logout()
        return None
        
    except Exception as e:
        print(f"Ошибка при проверке почты: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот для получения кодов Steam.\n\n"
        "Для доступа введите пароль.\n"
        "После авторизации используйте /getcode для получения кода."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Проверка пароля
    if user_id not in authorized_users:
        if message_text == CORRECT_PASSWORD:
            authorized_users.add(user_id)
            await update.message.reply_text(
                "✅ Авторизация успешна!\n"
                "Используйте /getcode для получения кода из почты."
            )
        else:
            await update.message.reply_text("❌ Неверный пароль. Попробуйте снова.")
    else:
        await update.message.reply_text(
            "Вы уже авторизованы. Используйте /getcode для получения кода."
        )

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getcode"""
    user_id = update.effective_user.id
    
    if user_id not in authorized_users:
        await update.message.reply_text(
            "❌ Доступ запрещен. Введите пароль для авторизации."
        )
        return
    
    await update.message.reply_text("🔍 Проверяю почту...")
    
    result = check_steam_email()
    
    if result:
        await update.message.reply_text(
            f"✅ Найден код Steam!\n\n"
            f"🔑 Код: <code>{result['code']}</code>\n"
            f"⏰ Время: {result['time']}\n\n"
            f"Нажмите на код чтобы скопировать.",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ Новых кодов не найдено.\n"
            "Проверяются письма от Steam за последние 10 минут."
        )

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /logout"""
    user_id = update.effective_user.id
    if user_id in authorized_users:
        authorized_users.remove(user_id)
        await update.message.reply_text("👋 Вы вышли из системы.")
    else:
        await update.message.reply_text("Вы не авторизованы.")

def main():
    """Запуск бота"""
    if not BOT_TOKEN or not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("Ошибка: Не заданы переменные окружения!")
        print("Необходимо установить: BOT_TOKEN, EMAIL_ADDRESS, EMAIL_PASSWORD")
        return
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getcode", get_code))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    print("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
