import os
import re
import imaplib
import email
import asyncio
import random
import aiohttp
from email.header import decode_header
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from bs4 import BeautifulSoup

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN')
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')  # OpenWeatherMap API
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '')  # Опционально
CORRECT_PASSWORD = "N55epe7red67av48ai8poroli"

# Хранилище
authorized_users = set()
user_server_page = {}

def check_steam_email():
    """Проверяет почту на наличие кодов от Steam"""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        mail.select("inbox")
        
        date = (datetime.now() - timedelta(minutes=10)).strftime("%d-%b-%Y")
        result, data = mail.search(None, f'(FROM "noreply@steampowered.com" SINCE {date})')
        
        if result != 'OK':
            return None
            
        email_ids = data[0].split()
        if not email_ids:
            return None
        
        latest_email_id = email_ids[-1]
        result, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        
        if result != 'OK':
            return None
            
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
                    break
        else:
            body = msg.get_payload(decode=True).decode()
        
        code_match = re.search(r'\b([A-Z0-9]{5})\b', body)
        if code_match:
            code = code_match.group(1)
            date_str = msg.get("Date")
            email_time = email.utils.parsedate_to_datetime(date_str)
            time_diff = datetime.now(email_time.tzinfo) - email_time
            
            if time_diff < timedelta(minutes=10):
                mail.close()
                mail.logout()
                return {
                    'code': code,
                    'time': email_time.strftime("%H:%M:%S")
                }
        
        mail.close()
        mail.logout()
        return None
        
    except Exception as e:
        print(f"Ошибка при проверке почты: {e}")
        return None

async def get_hvh_servers():
    """Парсит HvH сервера с monwave.ru"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        url = "https://monwave.ru/cs2/servers/tag/hvh"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    print(f"Monwave вернул статус {response.status}")
                    return get_fallback_servers()
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                servers = []
                
                # Ищем таблицу или список серверов
                # Возможные варианты структуры
                server_rows = (
                    soup.find_all('tr', class_=re.compile(r'server|row')) or
                    soup.find_all('div', class_=re.compile(r'server-item|server-row|server-card')) or
                    soup.find_all('a', href=re.compile(r'/cs2/servers/\d+\.\d+\.\d+\.\d+'))
                )
                
                print(f"Найдено элементов серверов: {len(server_rows)}")
                
                for row in server_rows[:30]:
                    try:
                        # Извлекаем текст из элемента
                        text_content = row.get_text(separator=' ', strip=True)
                        
                        # Ищем название сервера
                        name = None
                        name_elem = (
                            row.find('td', class_=re.compile(r'name|title|hostname')) or
                            row.find('div', class_=re.compile(r'name|title')) or
                            row.find('span', class_=re.compile(r'name|title'))
                        )
                        
                        if name_elem:
                            name = name_elem.get_text(strip=True)
                        elif len(text_content) > 10:
                            # Берём первые 50 символов как название
                            name = text_content[:50]
                        
                        if not name or len(name) < 5:
                            continue
                        
                        # Ищем количество игроков (формат X/Y)
                        players_match = re.search(r'(\d+)\s*/\s*(\d+)', text_content)
                        players = f"{players_match.group(1)}/{players_match.group(2)}" if players_match else "?/?"
                        
                        # Ищем карту (начинается с de_ или cs_)
                        map_match = re.search(r'(de_\w+|cs_\w+)', text_content, re.IGNORECASE)
                        map_name = map_match.group(1) if map_match else "Unknown"
                        
                        servers.append({
                            "name": f"🎮 {name.strip()[:60]}",
                            "players": players,
                            "map": map_name
                        })
                        
                    except Exception as e:
                        print(f"Ошибка парсинга строки: {e}")
                        continue
                
                if len(servers) >= 3:
                    print(f"Успешно спарсено {len(servers)} серверов")
                    return servers
                else:
                    print(f"Мало серверов ({len(servers)}), используем резервные")
                    return get_fallback_servers()
                
    except Exception as e:
        print(f"Ошибка парсинга Monwave: {e}")
        return get_fallback_servers()

def get_fallback_servers():
    """Резервные HvH сервера (актуальные на момент обновления)"""
    return [
        {"name": "🇺🇸 [NA | CHICAGO] CS2HVHSERVERS.COM [SCOUT]", "players": "8/64", "map": "de_mirage"},
        {"name": "🇺🇸 [NA | EAST] CS2HVHSERVERS.COM [SCOUT #2]", "players": "6/64", "map": "de_dust2"},  
        {"name": "🇪🇺 [EU] CS2HVHSERVERS.COM [MIRAGE] NO AWP", "players": "8/64", "map": "de_mirage"},
        {"name": "🇨🇳 [CN] Flux HvH™ | 鸟泊爆头服", "players": "6/24", "map": "de_dust2"},
        {"name": "🇨🇳 [CN] Flux HvH™ | 混战陪服 | 平衡Ping", "players": "14/24", "map": "de_dust2"},
        {"name": "🇷🇺 [RU] #3 REHVH.RU | SPREAD | [FP & DT FIX]", "players": "4/32", "map": "de_mirage"},
        {"name": "🇷🇺 [RU] Nixware HvH DM", "players": "12/32", "map": "dm_nixware"},
        {"name": "🇷🇺 [RU] [HvH club][NS & DT FIX][Mirage]", "players": "8/32", "map": "de_mirage"},
        {"name": "🇪🇺 [EU] CS2HVHSERVERS.COM NO AWP | NO DT", "players": "8/64", "map": "de_mirage"},
        {"name": "🇷🇺 [RU] EX HVH | RAPID FIRE | NOSPREAD", "players": "2/32", "map": "de_mirage"},
        {"name": "🇪🇺 CS2 HvH • Mirage • No Rapid Fire", "players": "6/24", "map": "de_mirage"},
        {"name": "🇺🇸 HvH Premium Server | No Lag", "players": "10/20", "map": "de_inferno"},
        {"name": "🇨🇳 [CN] Flux HvH™ | 死斗1服", "players": "1/24", "map": "de_nuke"},
        {"name": "🇺🇸 [Eternal] 伪吾匹配1服 #2服", "players": "1/16", "map": "de_vertigo"},
        {"name": "🇷🇺 [RU] HvH Arena | Best Servers", "players": "15/32", "map": "de_ancient"},
    ]

async def get_weather(city: str):
    """Получает реальную погоду через OpenWeatherMap API"""
    if not WEATHER_API_KEY:
        return {
            "error": "API ключ не настроен",
            "city": city,
            "temp": 0,
            "feels_like": 0,
            "condition": "❌ Ошибка",
            "humidity": 0,
            "wind": 0
        }
    
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"error": "Город не найден", "city": city}
                
                data = await response.json()
                
                # Иконки погоды
                condition_map = {
                    "Clear": "☀️ Ясно",
                    "Clouds": "☁️ Облачно",
                    "Rain": "🌧️ Дождь",
                    "Drizzle": "🌦️ Морось",
                    "Thunderstorm": "⛈️ Гроза",
                    "Snow": "❄️ Снег",
                    "Mist": "🌫️ Туман",
                    "Fog": "🌫️ Туман"
                }
                
                weather_main = data['weather'][0]['main']
                condition = condition_map.get(weather_main, data['weather'][0]['description'])
                
                return {
                    "city": data['name'],
                    "temp": round(data['main']['temp']),
                    "feels_like": round(data['main']['feels_like']),
                    "condition": condition,
                    "humidity": data['main']['humidity'],
                    "wind": round(data['wind']['speed'])
                }
    except Exception as e:
        print(f"Ошибка получения погоды: {e}")
        return {"error": str(e), "city": city}

async def get_currency_rates():
    """Получает реальные курсы валют с ЦБ РФ"""
    try:
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return get_fallback_rates()
                
                data = await response.json()
                
                return {
                    "USD": round(data['Valute']['USD']['Value'], 2),
                    "EUR": round(data['Valute']['EUR']['Value'], 2),
                    "CNY": round(data['Valute']['CNY']['Value'], 2),
                    "GBP": round(data['Valute']['GBP']['Value'], 2),
                    "date": data['Date']
                }
    except Exception as e:
        print(f"Ошибка получения курсов: {e}")
        return get_fallback_rates()

def get_fallback_rates():
    """Резервные курсы если API не работает"""
    return {
        "USD": 92.50,
        "EUR": 102.30,
        "CNY": 13.10,
        "GBP": 118.20,
        "date": datetime.now().isoformat()
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню бота"""
    user_id = update.effective_user.id
    
    if user_id in authorized_users:
        keyboard = [
            [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
            [InlineKeyboardButton("🎮 CS2 HvH Servers", callback_data="hvh_servers")],
            [InlineKeyboardButton("🌤️ Погода", callback_data="weather")],
            [InlineKeyboardButton("💰 Курсы валют", callback_data="currency")],
            [InlineKeyboardButton("🎲 Игра: Угадай число", callback_data="game_guess")],
            [InlineKeyboardButton("🎰 Слот-машина", callback_data="game_slots")],
            [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🤖 <b>Главное меню</b>\n\n"
            "Выберите действие:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "👋 Привет! Я многофункциональный бот.\n\n"
            "🔐 Для доступа введите пароль:"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in authorized_users and query.data != "logout":
        await query.edit_message_text("❌ Доступ запрещен. Введите /start и авторизуйтесь.")
        return
    
    # Steam Code
    if query.data == "steam_code":
        await query.edit_message_text("🔍 Проверяю почту...")
        result = check_steam_email()
        
        if result:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ <b>Найден код Steam!</b>\n\n"
                f"🔑 Код: <code>{result['code']}</code>\n"
                f"⏰ Время: {result['time']}\n\n"
                f"Нажмите на код чтобы скопировать.",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ Новых кодов не найдено.\n"
                "Проверяются письма от Steam за последние 10 минут.",
                reply_markup=reply_markup
            )
    
    # HvH Servers
    elif query.data == "hvh_servers":
        await query.edit_message_text("🔍 Загружаю сервера...")
        user_server_page[user_id] = 0
        await show_servers(query, user_id)
    
    elif query.data == "servers_next":
        user_server_page[user_id] = user_server_page.get(user_id, 0) + 1
        await show_servers(query, user_id)
    
    elif query.data == "servers_prev":
        user_server_page[user_id] = max(0, user_server_page.get(user_id, 0) - 1)
        await show_servers(query, user_id)
    
    # Погода
    elif query.data == "weather":
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🌍 <b>Погода</b>\n\n"
            "Введите название города (например: Москва, London, New York):",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        context.user_data['awaiting_city'] = True
    
    # Курсы валют
    elif query.data == "currency":
        await query.edit_message_text("💰 Загружаю курсы...")
        rates = await get_currency_rates()
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="currency")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        date_str = datetime.fromisoformat(rates['date']).strftime('%d.%m.%Y %H:%M')
        
        await query.edit_message_text(
            f"💰 <b>Курсы валют (ЦБ РФ)</b>\n\n"
            f"🇺🇸 USD: {rates['USD']} ₽\n"
            f"🇪🇺 EUR: {rates['EUR']} ₽\n"
            f"🇨🇳 CNY: {rates['CNY']} ₽\n"
            f"🇬🇧 GBP: {rates['GBP']} ₽\n\n"
            f"📅 Обновлено: {date_str}",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    # Игра: Угадай число
    elif query.data == "game_guess":
        number = random.randint(1, 100)
        context.user_data['guess_number'] = number
        context.user_data['guess_attempts'] = 0
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎲 <b>Игра: Угадай число!</b>\n\n"
            "Я загадал число от 1 до 100.\n"
            "Попробуй угадать! Введи число:",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        context.user_data['playing_guess'] = True
    
    # Слот-машина
    elif query.data == "game_slots":
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        slot1, slot2, slot3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        
        if slot1 == slot2 == slot3:
            result = "🎉 ДЖЕКПОТ! Все три совпали!"
        elif slot1 == slot2 or slot2 == slot3 or slot1 == slot3:
            result = "🎊 Два совпали! Неплохо!"
        else:
            result = "😢 Не повезло, попробуй ещё!"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Крутить ещё", callback_data="game_slots")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎰 <b>Слот-машина</b>\n\n"
            f"[ {slot1} | {slot2} | {slot3} ]\n\n"
            f"{result}",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    # Выход
    elif query.data == "logout":
        if user_id in authorized_users:
            authorized_users.remove(user_id)
        await query.edit_message_text("👋 Вы вышли из системы. Введите /start для входа.")
    
    # Назад в меню
    elif query.data == "back_to_menu":
        keyboard = [
            [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
            [InlineKeyboardButton("🎮 CS2 HvH Servers", callback_data="hvh_servers")],
            [InlineKeyboardButton("🌤️ Погода", callback_data="weather")],
            [InlineKeyboardButton("💰 Курсы валют", callback_data="currency")],
            [InlineKeyboardButton("🎲 Игра: Угадай число", callback_data="game_guess")],
            [InlineKeyboardButton("🎰 Слот-машина", callback_data="game_slots")],
            [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🤖 <b>Главное меню</b>\n\n"
            "Выберите действие:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def show_servers(query, user_id):
    """Показывает список серверов с пагинацией"""
    servers = await get_hvh_servers()
    page = user_server_page.get(user_id, 0)
    per_page = 10
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_servers = servers[start_idx:end_idx]
    
    text = "🎮 <b>CS2 HvH Servers</b>\n\n"
    for i, server in enumerate(page_servers, start=start_idx + 1):
        text += f"{i}. {server['name']}\n"
        text += f"   👥 {server['players']} | 🗺️ {server['map']}\n\n"
    
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="servers_prev"))
    if end_idx < len(servers):
        buttons.append(InlineKeyboardButton("Ещё ▶️", callback_data="servers_next"))
    
    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="hvh_servers")])
    keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text + f"📄 Страница {page + 1}/{(len(servers) - 1) // per_page + 1}",
        parse_mode='HTML',
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Авторизация
    if user_id not in authorized_users:
        if message_text == CORRECT_PASSWORD:
            authorized_users.add(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
                [InlineKeyboardButton("🎮 CS2 HvH Servers", callback_data="hvh_servers")],
                [InlineKeyboardButton("🌤️ Погода", callback_data="weather")],
                [InlineKeyboardButton("💰 Курсы валют", callback_data="currency")],
                [InlineKeyboardButton("🎲 Игра: Угадай число", callback_data="game_guess")],
                [InlineKeyboardButton("🎰 Слот-машина", callback_data="game_slots")],
                [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ <b>Авторизация успешна!</b>\n\n"
                "🤖 Главное меню:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Неверный пароль. Попробуйте снова.")
        return
    
    # Погода
    if context.user_data.get('awaiting_city'):
        context.user_data['awaiting_city'] = False
        
        loading_msg = await update.message.reply_text("🔍 Загружаю погоду...")
        weather = await get_weather(message_text)
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if 'error' in weather:
            await loading_msg.edit_text(
                f"❌ Ошибка: {weather['error']}\n\n"
                f"Проверьте название города и попробуйте снова.",
                reply_markup=reply_markup
            )
        else:
            await loading_msg.edit_text(
                f"🌤️ <b>Погода в городе {weather['city']}</b>\n\n"
                f"🌡️ Температура: {weather['temp']}°C\n"
                f"🤔 Ощущается как: {weather['feels_like']}°C\n"
                f"☁️ Состояние: {weather['condition']}\n"
                f"💧 Влажность: {weather['humidity']}%\n"
                f"💨 Ветер: {weather['wind']} м/с\n\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
    
    # Игра: Угадай число
    elif context.user_data.get('playing_guess'):
        try:
            guess = int(message_text)
            target = context.user_data['guess_number']
            context.user_data['guess_attempts'] += 1
            attempts = context.user_data['guess_attempts']
            
            if guess == target:
                context.user_data['playing_guess'] = False
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"🎉 <b>ПОЗДРАВЛЯЮ!</b>\n\n"
                    f"Вы угадали число {target} за {attempts} попыток!",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            elif guess < target:
                await update.message.reply_text(
                    f"📈 Моё число БОЛЬШЕ {guess}\n"
                    f"Попытка {attempts}. Попробуй ещё!"
                )
            else:
                await update.message.reply_text(
                    f"📉 Моё число МЕНЬШЕ {guess}\n"
                    f"Попытка {attempts}. Попробуй ещё!"
                )
        except ValueError:
            await update.message.reply_text("⚠️ Введите корректное число от 1 до 100!")
    
    else:
        await update.message.reply_text(
            "Используйте /start для открытия главного меню."
        )

def main():
    """Запуск бота"""
    if not BOT_TOKEN or not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("❌ Ошибка: Не заданы переменные окружения!")
        return
    
    if not WEATHER_API_KEY:
        print("⚠️ Предупреждение: WEATHER_API_KEY не задан, погода будет показывать ошибку")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Бот запущен!")
    print(f"📧 Email: {EMAIL_ADDRESS}")
    print(f"🌤️ Weather API: {'✅ Настроен' if WEATHER_API_KEY else '❌ Не настроен'}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
