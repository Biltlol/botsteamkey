import os
import re
import imaplib
import email
import asyncio
import random
import aiohttp
import json
from email.header import decode_header
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from bs4 import BeautifulSoup

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN')
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '')
CORRECT_PASSWORD = "N55epe7red67av48ai8poroli"

# Хранилище
authorized_users = set()
user_server_page = {}
user_configs = {}  # Хранение конфигов пользователей

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

async def get_hvh_servers_from_api():
    """Получает сервера через различные API"""
    servers = []
    
    # Попытка 1: Steam API (если есть ключ)
    if STEAM_API_KEY:
        try:
            url = f"https://api.steampowered.com/IGameServersService/GetServerList/v1/?key={STEAM_API_KEY}&filter=\\appid\\730\\gametype\\hvh"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'response' in data and 'servers' in data['response']:
                            for srv in data['response']['servers'][:20]:
                                servers.append({
                                    "name": srv.get('name', 'Unknown Server'),
                                    "ip": srv.get('addr', '0.0.0.0:0'),
                                    "players": f"{srv.get('players', 0)}/{srv.get('max_players', 0)}",
                                    "map": srv.get('map', 'unknown'),
                                    "game": srv.get('gametype', '')
                                })
                            if servers:
                                return servers
        except Exception as e:
            print(f"Steam API error: {e}")
    
    # Попытка 2: Battlemetrics API
    try:
        url = "https://api.battlemetrics.com/servers?filter[game]=cs2&filter[search]=hvh&page[size]=20"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'data' in data:
                        for srv in data['data']:
                            attrs = srv.get('attributes', {})
                            servers.append({
                                "name": attrs.get('name', 'Unknown Server'),
                                "ip": attrs.get('ip', '0.0.0.0') + ':' + str(attrs.get('port', '0')),
                                "players": f"{attrs.get('players', 0)}/{attrs.get('maxPlayers', 0)}",
                                "map": attrs.get('details', {}).get('map', 'unknown'),
                                "game": "CS2 HvH"
                            })
                        if servers:
                            return servers
    except Exception as e:
        print(f"Battlemetrics API error: {e}")
    
    # Fallback: Возвращаем статичные популярные сервера
    return get_fallback_servers()

def get_fallback_servers():
    """Резервные HvH сервера"""
    return [
        {"name": "🇺🇸 CS2HVHSERVERS.COM [SCOUT]", "ip": "162.248.95.39:27015", "players": "8/64", "map": "de_mirage", "game": "hvh"},
        {"name": "🇺🇸 CS2HVHSERVERS.COM [SCOUT #2]", "ip": "162.248.95.40:27015", "players": "6/64", "map": "de_dust2", "game": "hvh"},
        {"name": "🇪🇺 CS2HVHSERVERS.COM [MIRAGE]", "ip": "51.210.104.183:27015", "players": "12/64", "map": "de_mirage", "game": "hvh"},
        {"name": "🇷🇺 REHVH.RU | SPREAD", "ip": "185.185.69.70:27015", "players": "4/32", "map": "de_mirage", "game": "hvh"},
        {"name": "🇷🇺 Nixware HvH DM", "ip": "185.185.69.71:27015", "players": "12/32", "map": "dm_nixware", "game": "hvh"},
        {"name": "🇪🇺 HvH • Mirage • No RF", "ip": "51.210.104.184:27015", "players": "6/24", "map": "de_mirage", "game": "hvh"},
        {"name": "🇺🇸 HvH Premium Server", "ip": "162.248.95.41:27015", "players": "10/20", "map": "de_inferno", "game": "hvh"},
        {"name": "🇷🇺 HvH Arena | Best", "ip": "185.185.69.72:27015", "players": "15/32", "map": "de_ancient", "game": "hvh"},
        {"name": "🇪🇺 EU HvH #1 | 128 Tick", "ip": "51.210.104.185:27015", "players": "8/32", "map": "de_vertigo", "game": "hvh"},
        {"name": "🇺🇸 NA HvH West Coast", "ip": "162.248.95.42:27015", "players": "5/32", "map": "de_nuke", "game": "hvh"},
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

def generate_crosshair():
    """Генерирует случайный кросхейр"""
    styles = ['Classic', 'Classic Dynamic', 'Classic Static', 'Default', 'Default Static']
    colors = ['Green', 'Yellow', 'Blue', 'Cyan', 'Red']
    
    style = random.choice(styles)
    color = random.choice(colors)
    size = random.randint(1, 5)
    gap = random.randint(-3, 3)
    thickness = random.choice([0, 0.5, 1, 1.5, 2])
    
    commands = [
        f"cl_crosshair_drawoutline 1",
        f"cl_crosshair_outlinethickness 1",
        f"cl_crosshaircolor {colors.index(color)}",
        f"cl_crosshairsize {size}",
        f"cl_crosshairgap {gap}",
        f"cl_crosshairthickness {thickness}",
        f"cl_crosshairstyle {styles.index(style) + 2}",
        f"cl_crosshairdot 0"
    ]
    
    return {
        "style": style,
        "color": color,
        "size": size,
        "gap": gap,
        "thickness": thickness,
        "commands": "\n".join(commands)
    }

def generate_viewmodel():
    """Генерирует настройки вьюмодели"""
    presets = {
        "Classic": {
            "fov": 60,
            "x": 2.5,
            "y": 0,
            "z": -1.5
        },
        "Cozy": {
            "fov": 68,
            "x": 2,
            "y": 2,
            "z": -2
        },
        "Desktop": {
            "fov": 60,
            "x": 1,
            "y": 1,
            "z": -1
        },
        "Random": {
            "fov": random.randint(54, 68),
            "x": round(random.uniform(0.5, 3), 1),
            "y": round(random.uniform(-2, 2), 1),
            "z": round(random.uniform(-3, 0), 1)
        }
    }
    
    preset_name = random.choice(list(presets.keys()))
    vm = presets[preset_name]
    
    commands = [
        f"viewmodel_fov {vm['fov']}",
        f"viewmodel_offset_x {vm['x']}",
        f"viewmodel_offset_y {vm['y']}",
        f"viewmodel_offset_z {vm['z']}",
        f"viewmodel_presetpos 0"
    ]
    
    return {
        "preset": preset_name,
        "commands": "\n".join(commands)
    }

def generate_hvh_binds():
    """Генерирует полезные бинды для HvH"""
    binds = {
        "Основные": [
            'bind "mouse3" "+jump; -attack; -jump"  // Jump throw',
            'bind "v" "+voicerecord"  // Voice chat',
            'bind "c" "slot12"  // Healthshot',
            'bind "x" "slot10"  // Zeus'
        ],
        "Чит команды": [
            'bind "HOME" "exec legit.cfg"  // Legit config',
            'bind "END" "exec rage.cfg"  // Rage config',
            'bind "PGUP" "toggle cl_righthand 0 1"  // Switch hands',
            'bind "PGDN" "disconnect"  // Quick DC'
        ],
        "Утилиты": [
            'bind "F1" "buy vesthelm; buy vest;"  // Buy armor',
            'bind "F2" "buy defuser;"  // Buy kit',
            'bind "F3" "buy taser;"  // Buy zeus',
            'bind "F4" "buy molotov; buy incgrenade;"  // Buy molly'
        ],
        "Коммуникация": [
            'bind "KP_INS" "say gg"',
            'bind "KP_END" "say nice"',
            'bind "KP_DOWNARROW" "say nt"',
            'bind "KP_PGDN" "say rush b"'
        ]
    }
    
    return binds

def get_resolver_tips():
    """База знаний по резолверам"""
    tips = {
        "Основы": [
            "🎯 Используй Body Aim против AA (Anti-Aim)",
            "🔄 Переключайся между Pitch Up/Down для обхода",
            "⚡ Delay Shot помогает против Fake Lag",
            "🎲 Safe Point на дальних дистанциях"
        ],
        "Против читеров": [
            "🛡️ Baim в голову если противник крутится",
            "⏱️ Используй Hitchance 60%+ для надежности",
            "🔫 Магнум/Scout лучше для HvH",
            "📊 Минимум damage: 40-50 HP"
        ],
        "Настройки AA": [
            "↔️ Jitter для обхода резолверов",
            "🔃 Fake angles 58° оптимально",
            "⚙️ Body yaw на Static",
            "🎭 Fake duck только на стопе"
        ]
    }
    
    return tips

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню бота"""
    user_id = update.effective_user.id
    
    if user_id in authorized_users:
        keyboard = [
            [InlineKeyboardButton("🎮 HvH Servers", callback_data="hvh_servers")],
            [InlineKeyboardButton("⚙️ Config Manager", callback_data="config_menu")],
            [InlineKeyboardButton("🎯 Crosshair Gen", callback_data="crosshair_gen"),
             InlineKeyboardButton("📷 Viewmodel Gen", callback_data="viewmodel_gen")],
            [InlineKeyboardButton("⌨️ Bind Generator", callback_data="bind_gen")],
            [InlineKeyboardButton("🧠 Resolver Tips", callback_data="resolver_tips")],
            [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
            [InlineKeyboardButton("🌤️ Погода", callback_data="weather"),
             InlineKeyboardButton("💰 Валюты", callback_data="currency")],
            [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🤖 <b>HvH Bot - Главное меню</b>\n\n"
            "Выберите функцию:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "👋 Привет! Я бот для HvH игроков.\n\n"
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
    
    elif query.data.startswith("connect_"):
        server_ip = query.data.replace("connect_", "")
        connect_url = f"steam://connect/{server_ip}"
        
        keyboard = [
            [InlineKeyboardButton("🔗 Подключиться", url=connect_url)],
            [InlineKeyboardButton("◀️ К серверам", callback_data="hvh_servers")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎮 <b>Подключение к серверу</b>\n\n"
            f"📡 IP: <code>{server_ip}</code>\n\n"
            f"Нажмите кнопку ниже для подключения через Steam",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    # Config Manager
    elif query.data == "config_menu":
        configs = user_configs.get(user_id, [])
        
        keyboard = [
            [InlineKeyboardButton("➕ Сохранить конфиг", callback_data="config_save")],
            [InlineKeyboardButton("📂 Мои конфиги", callback_data="config_list")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚙️ <b>Config Manager</b>\n\n"
            f"Сохранено конфигов: {len(configs)}\n\n"
            f"Здесь вы можете сохранять настройки своих читов",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    elif query.data == "config_save":
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="config_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💾 <b>Сохранение конфига</b>\n\n"
            "Отправьте ваш конфиг в формате:\n"
            "<code>Название конфига\n"
            "cl_interp 0\n"
            "rate 128000\n"
            "...</code>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        context.user_data['saving_config'] = True
    
    elif query.data == "config_list":
        configs = user_configs.get(user_id, [])
        
        if not configs:
            keyboard = [
                [InlineKeyboardButton("➕ Создать первый", callback_data="config_save")],
                [InlineKeyboardButton("◀️ Назад", callback_data="config_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📂 У вас пока нет сохраненных конфигов",
                reply_markup=reply_markup
            )
        else:
            text = "📂 <b>Ваши конфиги:</b>\n\n"
            keyboard = []
            
            for i, cfg in enumerate(configs[-10:], 1):
                text += f"{i}. {cfg['name']} ({cfg['date']})\n"
                keyboard.append([InlineKeyboardButton(f"📄 {cfg['name']}", callback_data=f"config_view_{i-1}")])
            
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="config_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
    
    elif query.data.startswith("config_view_"):
        idx = int(query.data.replace("config_view_", ""))
        configs = user_configs.get(user_id, [])
        
        if idx < len(configs):
            cfg = configs[idx]
            keyboard = [
                [InlineKeyboardButton("🗑️ Удалить", callback_data=f"config_delete_{idx}")],
                [InlineKeyboardButton("◀️ К списку", callback_data="config_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📄 <b>{cfg['name']}</b>\n"
                f"📅 Создан: {cfg['date']}\n\n"
                f"<code>{cfg['content']}</code>",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
    
    elif query.data.startswith("config_delete_"):
        idx = int(query.data.replace("config_delete_", ""))
        if user_id in user_configs and idx < len(user_configs[user_id]):
            del user_configs[user_id][idx]
            await query.answer("✅ Конфиг удален")
            await query.edit_message_text("✅ Конфиг удален успешно")
            await asyncio.sleep(1)
            # Возврат к списку
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="config_list")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Конфиг удален", reply_markup=reply_markup)
    
    # Crosshair Generator
    elif query.data == "crosshair_gen":
        crosshair = generate_crosshair()
        
        keyboard = [
            [InlineKeyboardButton("🔄 Новый кросхейр", callback_data="crosshair_gen")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎯 <b>Crosshair Generator</b>\n\n"
            f"Стиль: {crosshair['style']}\n"
            f"Цвет: {crosshair['color']}\n"
            f"Размер: {crosshair['size']}\n"
            f"Зазор: {crosshair['gap']}\n"
            f"Толщина: {crosshair['thickness']}\n\n"
            f"<b>Команды для консоли:</b>\n"
            f"<code>{crosshair['commands']}</code>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    # Viewmodel Generator
    elif query.data == "viewmodel_gen":
        viewmodel = generate_viewmodel()
        
        keyboard = [
            [InlineKeyboardButton("🔄 Новая вьюмодель", callback_data="viewmodel_gen")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📷 <b>Viewmodel Generator</b>\n\n"
            f"Пресет: {viewmodel['preset']}\n\n"
            f"<b>Команды для консоли:</b>\n"
            f"<code>{viewmodel['commands']}</code>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    # Bind Generator
    elif query.data == "bind_gen":
        binds = generate_hvh_binds()
        
        text = "⌨️ <b>Bind Generator</b>\n\n"
        for category, bind_list in binds.items():
            text += f"<b>{category}:</b>\n"
            for bind in bind_list:
                text += f"<code>{bind}</code>\n"
            text += "\n"
        
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
    
    # Resolver Tips
    elif query.data == "resolver_tips":
        tips = get_resolver_tips()
        
        text = "🧠 <b>Resolver Tips & Tricks</b>\n\n"
        for category, tip_list in tips.items():
            text += f"<b>{category}:</b>\n"
            for tip in tip_list:
                text += f"{tip}\n"
            text += "\n"
        
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
    
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
    
    # Выход
    elif query.data == "logout":
        if user_id in authorized_users:
            authorized_users.remove(user_id)
        await query.edit_message_text("👋 Вы вышли из системы. Введите /start для входа.")
    
    # Назад в меню
    elif query.data == "back_to_menu":
        keyboard = [
            [InlineKeyboardButton("🎮 HvH Servers", callback_data="hvh_servers")],
            [InlineKeyboardButton("⚙️ Config Manager", callback_data="config_menu")],
            [InlineKeyboardButton("🎯 Crosshair Gen", callback_data="crosshair_gen"),
             InlineKeyboardButton("📷 Viewmodel Gen", callback_data="viewmodel_gen")],
            [InlineKeyboardButton("⌨️ Bind Generator", callback_data="bind_gen")],
            [InlineKeyboardButton("🧠 Resolver Tips", callback_data="resolver_tips")],
            [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
            [InlineKeyboardButton("🌤️ Погода", callback_data="weather"),
             InlineKeyboardButton("💰 Валюты", callback_data="currency")],
            [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🤖 <b>HvH Bot - Главное меню</b>\n\n"
            "Выберите функцию:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def show_servers(query, user_id):
    """Показывает список серверов с возможностью подключения"""
    servers = await get_hvh_servers_from_api()
    page = user_server_page.get(user_id, 0)
    per_page = 5
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_servers = servers[start_idx:end_idx]
    
    text = "🎮 <b>CS2 HvH Servers</b>\n\n"
    
    keyboard = []
    for i, server in enumerate(page_servers, start=start_idx + 1):
        text += f"{i}. <b>{server['name']}</b>\n"
        text += f"   👥 {server['players']} | 🗺️ {server['map']}\n"
        text += f"   📡 <code>{server['ip']}</code>\n\n"
        
        # Кнопка подключения для каждого сервера
        keyboard.append([InlineKeyboardButton(
            f"🔗 Подключиться к #{i}", 
            callback_data=f"connect_{server['ip']}"
        )])
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="servers_prev"))
    if end_idx < len(servers):
        nav_buttons.append(InlineKeyboardButton("Ещё ▶️", callback_data="servers_next"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="hvh_servers")])
    keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text += f"📄 Страница {page + 1}/{(len(servers) - 1) // per_page + 1}"
    
    await query.edit_message_text(
        text,
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
                [InlineKeyboardButton("🎮 HvH Servers", callback_data="hvh_servers")],
                [InlineKeyboardButton("⚙️ Config Manager", callback_data="config_menu")],
                [InlineKeyboardButton("🎯 Crosshair Gen", callback_data="crosshair_gen"),
                 InlineKeyboardButton("📷 Viewmodel Gen", callback_data="viewmodel_gen")],
                [InlineKeyboardButton("⌨️ Bind Generator", callback_data="bind_gen")],
                [InlineKeyboardButton("🧠 Resolver Tips", callback_data="resolver_tips")],
                [InlineKeyboardButton("🔑 Steam Code", callback_data="steam_code")],
                [InlineKeyboardButton("🌤️ Погода", callback_data="weather"),
                 InlineKeyboardButton("💰 Валюты", callback_data="currency")],
                [InlineKeyboardButton("🚪 Выход", callback_data="logout")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ <b>Авторизация успешна!</b>\n\n"
                "🤖 Главное меню HvH бота:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Неверный пароль. Попробуйте снова.")
        return
    
    # Сохранение конфига
    if context.user_data.get('saving_config'):
        context.user_data['saving_config'] = False
        
        lines = message_text.strip().split('\n')
        if len(lines) >= 2:
            config_name = lines[0]
            config_content = '\n'.join(lines[1:])
            
            if user_id not in user_configs:
                user_configs[user_id] = []
            
            user_configs[user_id].append({
                'name': config_name,
                'content': config_content,
                'date': datetime.now().strftime('%d.%m.%Y %H:%M')
            })
            
            keyboard = [[InlineKeyboardButton("◀️ К конфигам", callback_data="config_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ <b>Конфиг '{config_name}' сохранен!</b>\n\n"
                f"Всего конфигов: {len(user_configs[user_id])}",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "❌ Неверный формат. Первая строка - название, остальное - содержимое конфига."
            )
    
    # Погода
    elif context.user_data.get('awaiting_city'):
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
        print("⚠️ Предупреждение: WEATHER_API_KEY не задан")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 HvH Bot запущен!")
    print(f"📧 Email: {EMAIL_ADDRESS}")
    print(f"🌤️ Weather API: {'✅' if WEATHER_API_KEY else '❌'}")
    print(f"🎮 Steam API: {'✅' if STEAM_API_KEY else '❌'}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
