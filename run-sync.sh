#!/bin/bash
# Wrapper script для автоматической синхронизации Zabbix → NetBox
# Запускается через cron каждые 2 дня

set -e  # Остановить при ошибках

# Директория проекта
PROJECT_DIR="/home/admintelegrambot/cloud-services/prods-z-n"

# Лог файл
LOG_FILE="/var/log/zabbix-netbox-sync.log"

# Начало синхронизации
echo "========================================" | tee -a "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Начало синхронизации" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# Переход в директорию проекта
cd "$PROJECT_DIR" || {
    echo "ОШИБКА: Не удалось перейти в $PROJECT_DIR" | tee -a "$LOG_FILE"
    exit 1
}

# Запуск синхронизации через Docker Compose
if docker compose run --rm sync-app; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ✅ Синхронизация завершена успешно" | tee -a "$LOG_FILE"
    EXIT_CODE=0
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ❌ Синхронизация завершилась с ошибкой" | tee -a "$LOG_FILE"
    EXIT_CODE=1
fi

# Очистка старых логов (оставить последние 30 дней)
find "$PROJECT_DIR/logs" -name "sync_*.log" -mtime +30 -delete 2>/dev/null || true

echo "" | tee -a "$LOG_FILE"
exit $EXIT_CODE
