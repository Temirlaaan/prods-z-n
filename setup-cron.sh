#!/bin/bash
# Скрипт для установки cron задания

# ВАЖНО: Измените пути на правильные для вашей системы!
PROJECT_DIR="/home/admintelegrambot/cloud-services/prods-z-n"
SCRIPT_PATH="$PROJECT_DIR/run-sync.sh"
LOG_FILE="/var/log/zabbix-netbox-sync.log"

echo "Настройка cron для автоматической синхронизации..."
echo ""
echo "Параметры:"
echo "  - Скрипт: $SCRIPT_PATH"
echo "  - Расписание: Каждые 2 дня в 2:00 ночи"
echo "  - Лог файл: $LOG_FILE"
echo ""

# Проверка что скрипт существует
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ ОШИБКА: Скрипт $SCRIPT_PATH не найден!"
    echo "   Скопируйте run-sync.sh в правильную директорию"
    exit 1
fi

# Проверка что скрипт исполняемый
if [ ! -x "$SCRIPT_PATH" ]; then
    echo "❌ ОШИБКА: Скрипт $SCRIPT_PATH не исполняемый!"
    echo "   Запустите: chmod +x $SCRIPT_PATH"
    exit 1
fi

# Создание лог файла если не существует
if [ ! -f "$LOG_FILE" ]; then
    sudo touch "$LOG_FILE"
    sudo chown $USER:$USER "$LOG_FILE"
    echo "✅ Создан лог файл: $LOG_FILE"
fi

# Добавление в crontab
CRON_COMMAND="0 2 */2 * * $SCRIPT_PATH >> $LOG_FILE 2>&1"

# Получить текущий crontab
CURRENT_CRON=$(crontab -l 2>/dev/null || echo "")

# Проверить что задание еще не добавлено
if echo "$CURRENT_CRON" | grep -q "$SCRIPT_PATH"; then
    echo "⚠️  Задание уже существует в crontab!"
    echo ""
    echo "Текущие задания:"
    crontab -l | grep "$SCRIPT_PATH"
    exit 0
fi

# Добавить новое задание
(
    echo "$CURRENT_CRON"
    echo ""
    echo "# Zabbix → NetBox синхронизация (каждые 2 дня в 2:00)"
    echo "$CRON_COMMAND"
) | crontab -

echo "✅ Задание добавлено в crontab!"
echo ""
echo "Проверка:"
crontab -l
echo ""
echo "📅 Следующий запуск будет через 2 дня в 2:00 ночи"
echo ""
echo "Для тестирования запустите вручную:"
echo "  $SCRIPT_PATH"
