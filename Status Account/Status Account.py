import os
import uuid
import logging
import sys
import requests
import traceback
import json
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from tg_bot import keyboards

NAME = "Status Account"
VERSION = "1.0"
DESCRIPTION = "Позволяет переключать FunPay аккаунт между режимами онлайн и оффлайн"
CREDITS = "tinechelovec"
UUID = "c879be19-0b75-43f2-88d7-7a3806b59426"
SETTINGS_PAGE = False

logger = logging.getLogger(f"FPC.{__name__}")

ONLINE_STATUS_FILE = "storage/cache/status_accaunt.txt"
LAST_MESSAGE_FILE = "storage/cache/status_accaunt_message.json"
FORCE_OFFLINE = False
cardinal_instance = None
INITIALIZED = False

original_requests_get = requests.get
original_requests_post = requests.post


orig_edit_plugin = keyboards.edit_plugin

def custom_edit_plugin(c, uuid, offset=0, ask_to_delete=False):
    kb = orig_edit_plugin(c, uuid, offset, ask_to_delete)
    if uuid == UUID:
        dev_btn = InlineKeyboardButton(text="👽 Разработчик", url=f"https://t.me/{CREDITS[1:]}")
        kb.keyboard[0] = [dev_btn]
    return kb

def save_message_info(chat_id, message_id):
    try:
        with open(LAST_MESSAGE_FILE, "w") as f:
            json.dump({"chat_id": chat_id, "message_id": message_id}, f)
    except Exception as e:
        logger.error(f"Ошибка при сохранении информации о сообщении: {str(e)}")

def load_message_info():
    try:
        if os.path.exists(LAST_MESSAGE_FILE):
            with open(LAST_MESSAGE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке информации о сообщении: {str(e)}")
    return None

def set_status(cardinal, message_obj, status="offline", skip_notification=False):
    try:
        global FORCE_OFFLINE, cardinal_instance
        cardinal_instance = cardinal
        
        is_offline = status == "offline"
        FORCE_OFFLINE = is_offline
        payload = {
            "onlines": "disable" if is_offline else "enable",
            "csrf_token": cardinal.account.csrf_token
        }
        
        headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest"
        }
        cookies = {
            'golden_key': cardinal.account.golden_key,
            'PHPSESSID': cardinal.account.phpsessid
        }
        
        response = requests.post(
            "https://funpay.com/runner/",
            data=payload,
            headers=headers,
            cookies=cookies,
            proxies=cardinal.proxy
        )
        
        if is_offline:
            cardinal.run_id += 1
        
        with open(ONLINE_STATUS_FILE, "w") as f:
            f.write(status)
        
        if hasattr(message_obj, 'chat') and hasattr(message_obj, 'from_user'):
            chat_id = message_obj.chat.id
            username = message_obj.from_user.username
        else:
            chat_id = cardinal.telegram.bot.get_chat_id()
            username = message_obj.author.username if hasattr(message_obj.author, 'username') else "Unknown"
        
        if not skip_notification:
            if is_offline:
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🟢 Вернуться онлайн", callback_data="go_online"))
                cardinal.telegram.bot.send_message(
                    chat_id, 
                    "✅ Аккаунт переведен в режим *ОФФЛАЙН*\n\n"
                    "⚠️ В оффлайн режиме *не работает автовыдача, уведомление, автоподнятие*", 
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                sent_message = cardinal.telegram.bot.send_message(
                    chat_id, 
                    "✅ Выполняется переход в режим *ОНЛАЙН*...\n\n⏳ Перезапуск бота...",
                    parse_mode="Markdown"
                )
                save_message_info(chat_id, sent_message.message_id)
        
        if not is_offline:
            python_executable = sys.executable
            os.execv(python_executable, [python_executable] + sys.argv)
            
    except Exception as e:
        logger.error(f"Ошибка при установке статуса {status}: {str(e)}")
        if hasattr(message_obj, 'chat'):
            cardinal.telegram.bot.send_message(
                message_obj.chat.id, 
                f"❌ Ошибка при изменении статуса: {str(e)}"
            )

def cmd_offline(cardinal, message):
    set_status(cardinal, message, "offline")

def cmd_online(cardinal, message):
    set_status(cardinal, message, "online")

def handle_bot_commands(cardinal, event, *args):
    message = event.message
    if not hasattr(message, 'text') or not message.text or not message.text.startswith('/'):
        return
        
    if message.text.startswith("/offline"):
        set_status(cardinal, message, "offline")
    elif message.text.startswith("/online"):
        set_status(cardinal, message, "online")

def init_plugin(cardinal, *args):
    global INITIALIZED, cardinal_instance, original_requests_get, original_requests_post, FORCE_OFFLINE
    if INITIALIZED:
        return
        
    INITIALIZED = True
    cardinal_instance = cardinal
    
    try:
        def patched_requests_get(*args, **kwargs):
            if args and 'funpay.com' in args[0] and FORCE_OFFLINE:
                class MockResponse:
                    def __init__(self):
                        self.text = '{"objects":[],"response":false}'
                        self.content = self.text.encode('utf-8')
                        self.status_code = 200
                        self.ok = True
                    def json(self):
                        return {"objects":[],"response":False}
                return MockResponse()
            return original_requests_get(*args, **kwargs)
        
        def patched_requests_post(*args, **kwargs):
            if args and 'funpay.com' in args[0] and FORCE_OFFLINE:
                if 'data' in kwargs and isinstance(kwargs['data'], dict) and 'onlines' in kwargs['data']:
                    return original_requests_post(*args, **kwargs)
                    
                class MockResponse:
                    def __init__(self):
                        self.text = '{"objects":[],"response":false}'
                        self.content = self.text.encode('utf-8')
                        self.status_code = 200
                        self.ok = True
                    def json(self):
                        return {"objects":[],"response":False}
                return MockResponse()
            return original_requests_post(*args, **kwargs)
        
        requests.get = patched_requests_get
        requests.post = patched_requests_post
        
        import telebot
        original_process_new_updates = telebot.TeleBot.process_new_updates
        
        def patched_process_new_updates(self, updates):
            for update in updates:
                if hasattr(update, 'callback_query') and update.callback_query and update.callback_query.data == "go_online":
                    try:
                        self.answer_callback_query(update.callback_query.id, text="Переключение в онлайн режим...")
                        
                        edited_msg = self.edit_message_text(
                            chat_id=update.callback_query.message.chat.id,
                            message_id=update.callback_query.message.message_id,
                            text="✅ Выполняется переход в режим *ОНЛАЙН*...\n\n⏳ Перезапуск бота...",
                            parse_mode="Markdown"
                        )
                        
                        save_message_info(update.callback_query.message.chat.id, update.callback_query.message.message_id)
                        
                        global cardinal_instance
                        if cardinal_instance:
                            set_status(cardinal_instance, update.callback_query.message, "online", skip_notification=True)
                    except Exception as e:
                        logger.error(f"Ошибка обработки callback: {str(e)}")
            return original_process_new_updates(self, updates)
        
        telebot.TeleBot.process_new_updates = patched_process_new_updates
    except Exception as e:
        logger.error(f"Ошибка инициализации перехватчиков: {str(e)}")
    
    commands = [
        ("offline", "перейти в режим оффлайн", True),
        ("online", "перейти в режим онлайн", True)
    ]
    cardinal.add_telegram_commands(UUID, commands)
    
    bot = cardinal.telegram.bot
    @bot.message_handler(commands=['offline'])
    def offline_command(message):
        cmd_offline(cardinal, message)
    
    @bot.message_handler(commands=['online'])
    def online_command(message):
        cmd_online(cardinal, message)
    
    try:
        message_info = load_message_info()
        if message_info and os.path.exists(ONLINE_STATUS_FILE):
            with open(ONLINE_STATUS_FILE, "r") as f:
                status = f.read().strip()
                if status == "online":
                    try:
                        cardinal.telegram.bot.edit_message_text(
                            chat_id=message_info["chat_id"],
                            message_id=message_info["message_id"],
                            text="✅ *Бот успешно запущен!*\n\n"
                                "🟢 Аккаунт находится в режиме *ОНЛАЙН*\n\n"
                                "▶️ Все автоматические функции активны",
                            parse_mode="Markdown"
                        )
                        if os.path.exists(LAST_MESSAGE_FILE):
                            os.remove(LAST_MESSAGE_FILE)
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении сообщения: {str(e)}")
    except Exception as e:
        logger.error(f"Ошибка при проверке перезапуска: {str(e)}")
    
    try:
        if os.path.exists(ONLINE_STATUS_FILE):
            with open(ONLINE_STATUS_FILE, "r") as f:
                status = f.read().strip()
                if status == "offline":
                    headers = {
                        "accept": "*/*", 
                        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "x-requested-with": "XMLHttpRequest"
                    }
                    cookies = {
                        'golden_key': cardinal.account.golden_key,
                        'PHPSESSID': cardinal.account.phpsessid
                    }
                    payload = {
                        "onlines": "disable",
                        "csrf_token": cardinal.account.csrf_token
                    }
                    requests.post(
                        "https://funpay.com/runner/",
                        data=payload,
                        headers=headers,
                        cookies=cookies,
                        proxies=cardinal.proxy
                    )
                    FORCE_OFFLINE = True
                    cardinal.run_id += 1
    except Exception as e:
        logger.error(f"Ошибка восстановления статуса: {str(e)}")

def on_delete(cardinal, *args):
    try:
        global original_requests_get, original_requests_post
        requests.get = original_requests_get
        requests.post = original_requests_post
        
        import telebot
        if hasattr(telebot.TeleBot, 'process_new_updates') and telebot.TeleBot.process_new_updates != getattr(telebot.TeleBot, 'original_process_new_updates', None):
            if hasattr(telebot.TeleBot, 'original_process_new_updates'):
                telebot.TeleBot.process_new_updates = telebot.TeleBot.original_process_new_updates
    except Exception as e:
        logger.error(f"Ошибка при удалении плагина: {str(e)}")

BIND_TO_POST_INIT = [init_plugin]
BIND_TO_NEW_MESSAGE = [handle_bot_commands]
BIND_TO_DELETE = [on_delete] 