#!/usr/bin/env python3
"""
Интерактивный Telegram бот для управления синхронизацией
"""
import logging
import os
import subprocess
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config
from sync import ServerSync
from utils import NotificationHelper

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Авторизованные пользователи (добавьте свои ID)
AUTHORIZED_USERS = os.getenv('AUTHORIZED_USERS', '').split(',')

def is_authorized(user_id: int) -> bool:
    """Проверка авторизации пользователя"""
    return str(user_id) in AUTHORIZED_USERS or not AUTHORIZED_USERS[0]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этому боту")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Запустить синхронизацию", callback_data='sync_now'),
            InlineKeyboardButton("🔍 Тестовый запуск", callback_data='sync_dry')
        ],
        [
            InlineKeyboardButton("📊 Статус", callback_data='status'),
            InlineKeyboardButton("📋 Последние логи", callback_data='logs')
        ],
        [
            InlineKeyboardButton("ℹ️ Помощь", callback_data='help')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! 👋\n\n"
        f"<b>Управление синхронизацией Zabbix → NetBox</b>\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    user = query.from_user
    
    if not is_authorized(user.id):
        await query.answer("❌ Нет доступа", show_alert=True)
        return
    
    await query.answer()
    
    if query.data == 'sync_now':
        await query.edit_message_text("⏳ Запускаю синхронизацию...")
        await run_sync(query, context, dry_run=False)
    
    elif query.data == 'sync_dry':
        await query.edit_message_text("⏳ Запускаю тестовый прогон...")
        await run_sync(query, context, dry_run=True)
    
    elif query.data == 'status':
        await show_status(query, context)
    
    elif query.data == 'logs':
        await show_logs(query, context)
    
    elif query.data == 'help':
        await show_help(query, context)

async def run_sync(query, context: ContextTypes.DEFAULT_TYPE, dry_run: bool = False):
    """Запуск синхронизации"""
    try:
        # Создаем объект синхронизации
        sync = ServerSync()
        
        # Подключаемся к сервисам
        if not sync.connect_services():
            await query.edit_message_text("❌ Не удалось подключиться к сервисам")
            return
        
        # Настройки для запуска
        if dry_run:
            config.DRY_RUN = True
            config.HOST_LIMIT = 5  # Ограничиваем для теста
        
        # Запускаем синхронизацию
        stats = sync.run_sync()
        
        # Формируем отчет
        message = NotificationHelper.format_sync_summary(
            stats['new_hosts'],
            stats['changed_hosts'],
            len(stats['new_hosts']) + len(stats['changed_hosts']),
            len(stats['error_hosts']),
            stats['new_models'],
            format_type='HTML'
        )
        
        if dry_run:
            message = "🔸 <b>ТЕСТОВЫЙ ПРОГОН</b>\n\n" + message
        
        await query.edit_message_html(message)
        
    except Exception as e:
        logger.error(f"Ошибка синхронизации: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    
    finally:
        if 'sync' in locals():
            sync.disconnect_services()

async def show_status(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать статус системы"""
    try:
        import redis
        
        status_lines = ["📊 <b>Статус системы</b>\n"]
        
        # Проверка Redis
        try:
            r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB)
            r.ping()
            host_count = len(list(r.scan_iter(f"{config.REDIS_KEY_PREFIX}*")))
            status_lines.append(f"✅ Redis: OK ({host_count} хостов в кеше)")
        except:
            status_lines.append("❌ Redis: Недоступен")
        
        # Проверка последнего запуска
        log_dir = config.LOG_DIR
        if os.path.exists(log_dir):
            logs = sorted([f for f in os.listdir(log_dir) if f.endswith('.log')])
            if logs:
                last_log = logs[-1]
                last_time = datetime.strptime(last_log.split('_')[1].split('.')[0], '%Y%m%d')
                status_lines.append(f"📅 Последний запуск: {last_time.strftime('%Y-%m-%d')}")
        
        # Проверка Zabbix и NetBox
        sync = ServerSync()
        if sync.connect_services():
            status_lines.append("✅ Zabbix: Подключен")
            status_lines.append("✅ NetBox: Подключен")
            sync.disconnect_services()
        else:
            status_lines.append("⚠️ Проблемы с подключением к сервисам")
        
        await query.edit_message_html("\n".join(status_lines))
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка получения статуса: {str(e)}")

async def show_logs(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать последние логи"""
    try:
        log_dir = config.LOG_DIR
        if not os.path.exists(log_dir):
            await query.edit_message_text("📋 Логи не найдены")
            return
        
        logs = sorted([f for f in os.listdir(log_dir) if f.endswith('.log')])
        if not logs:
            await query.edit_message_text("📋 Логи не найдены")
            return
        
        last_log_file = os.path.join(log_dir, logs[-1])
        
        # Читаем последние 50 строк
        with open(last_log_file, 'r') as f:
            lines = f.readlines()
            last_lines = lines[-50:] if len(lines) > 50 else lines
        
        # Фильтруем важные строки
        important_lines = []
        for line in last_lines:
            if any(x in line for x in ['ERROR', 'WARNING', '✓', '✗', 'Результаты']):
                # Убираем timestamp для краткости
                if ' - ' in line:
                    line = line.split(' - ', 2)[-1]
                important_lines.append(line.strip())
        
        if important_lines:
            message = "📋 <b>Последние логи:</b>\n\n<code>"
            message += "\n".join(important_lines[-20:])  # Последние 20 важных строк
            message += "</code>"
        else:
            message = "📋 Нет важных событий в логах"
        
        await query.edit_message_html(message)
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка чтения логов: {str(e)}")

async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку"""
    help_text = """
ℹ️ <b>Справка по боту</b>

<b>Команды:</b>
/start - Главное меню
/sync - Запустить синхронизацию
/status - Показать статус
/help - Эта справка

<b>Кнопки:</b>
▶️ <b>Запустить синхронизацию</b> - полная синхронизация
🔍 <b>Тестовый запуск</b> - dry-run режим (5 хостов)
📊 <b>Статус</b> - состояние системы
📋 <b>Последние логи</b> - важные события

<b>Настройки:</b>
• Zabbix: {zabbix_url}
• NetBox: {netbox_url}
• Redis: {redis_host}:{redis_port}
• Лимит хостов: {limit}

<b>Расписание:</b>
Автоматический запуск каждый час через cron.
    """.format(
        zabbix_url=config.ZABBIX_URL,
        netbox_url=config.NETBOX_URL,
        redis_host=config.REDIS_HOST,
        redis_port=config.REDIS_PORT,
        limit=config.HOST_LIMIT or "Без ограничений"
    )
    
    await query.edit_message_html(help_text)

async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /sync"""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ У вас нет доступа")
        return
    
    await update.message.reply_text("⏳ Запускаю синхронизацию...")
    
    # Создаем фиктивный query объект для переиспользования функции
    class FakeQuery:
        async def edit_message_text(self, text):
            await update.message.reply_text(text)
        async def edit_message_html(self, text):
            await update.message.reply_html(text)
    
    await run_sync(FakeQuery(), context, dry_run=False)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ У вас нет доступа")
        return
    
    class FakeQuery:
        async def edit_message_html(self, text):
            await update.message.reply_html(text)
        async def edit_message_text(self, text):
            await update.message.reply_text(text)
    
    await show_status(FakeQuery(), context)

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("sync", sync_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", lambda u, c: show_help(u, c)))
    application.add_handler(CallbackQueryHandler(button))
    
    # Запускаем бота
    logger.info("🤖 Telegram бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()