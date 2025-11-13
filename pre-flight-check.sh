#!/bin/bash
# Pre-flight checklist script
# Запустите этот скрипт ПЕРЕД синхронизацией для проверки готовности

echo "======================================"
echo "🔍 Pre-Flight Checklist для v1.1.0"
echo "======================================"
echo ""

# 1. Проверка Python зависимостей
echo "1. Проверка зависимостей..."
if python -c "import pyzabbix, pynetbox, redis, dotenv" 2>/dev/null; then
    echo "   ✅ Все зависимости установлены"
else
    echo "   ❌ Некоторые зависимости отсутствуют!"
    echo "   Запустите: pip install -r requirements.txt"
    exit 1
fi

# 2. Проверка .env файла
echo ""
echo "2. Проверка .env конфигурации..."

required_vars=(
    "ZABBIX_URL"
    "ZABBIX_USER"
    "ZABBIX_PASSWORD"
    "NETBOX_URL"
    "NETBOX_TOKEN"
)

missing=0
for var in "${required_vars[@]}"; do
    if grep -q "^${var}=" .env 2>/dev/null; then
        echo "   ✅ $var найден"
    else
        echo "   ❌ $var отсутствует!"
        missing=1
    fi
done

# Проверка новых настроек
new_vars=(
    "ENABLE_PHYSICAL_DELETION"
    "CHECK_RACK_CONFLICTS"
    "ORPHANED_IP_ACTION"
)

echo ""
echo "   Новые настройки v1.1.0:"
for var in "${new_vars[@]}"; do
    if grep -q "^${var}=" .env 2>/dev/null; then
        value=$(grep "^${var}=" .env | cut -d'=' -f2)
        echo "   ✅ $var = $value"
    else
        echo "   ⚠️  $var не найден (будет использовано значение по умолчанию)"
    fi
done

if [ $missing -eq 1 ]; then
    echo ""
    echo "   ❌ Критические переменные отсутствуют!"
    exit 1
fi

# 3. Проверка бэкапа
echo ""
echo "3. Проверка бэкапов..."
if [ -d "/backup" ] && [ "$(ls -A /backup/*.sql 2>/dev/null)" ]; then
    latest_backup=$(ls -t /backup/*.sql 2>/dev/null | head -1)
    echo "   ✅ Найден бэкап: $latest_backup"
else
    echo "   ⚠️  Бэкап NetBox не найден!"
    echo "   РЕКОМЕНДУЕТСЯ создать бэкап:"
    echo "   pg_dump netbox > /backup/netbox_\$(date +%Y%m%d_%H%M%S).sql"
fi

# 4. Проверка Git статуса
echo ""
echo "4. Проверка Git..."
if git rev-parse --git-dir > /dev/null 2>&1; then
    current_branch=$(git branch --show-current)
    echo "   ✅ Git репозиторий: ветка $current_branch"

    if [ "$current_branch" == "claude/project-logic-analysis-011CV5GjbVGGhUPFT3uuevqp" ]; then
        echo "   ✅ Находитесь на правильной ветке с исправлениями"
    else
        echo "   ⚠️  Вы на ветке $current_branch"
        echo "   Переключитесь на: git checkout claude/project-logic-analysis-011CV5GjbVGGhUPFT3uuevqp"
    fi
else
    echo "   ⚠️  Не Git репозиторий"
fi

# 5. Проверка синтаксиса Python
echo ""
echo "5. Проверка синтаксиса кода..."
if python -m py_compile sync.py config.py utils.py 2>/dev/null; then
    echo "   ✅ Синтаксис Python корректен"
else
    echo "   ❌ Ошибки синтаксиса Python!"
    exit 1
fi

# 6. DRY_RUN проверка
echo ""
echo "6. Проверка режима DRY_RUN..."
if grep -q "^DRY_RUN=true" .env 2>/dev/null; then
    echo "   ✅ DRY_RUN=true (безопасный режим)"
    echo "   💡 Первый запуск будет в тестовом режиме"
elif grep -q "^DRY_RUN=false" .env 2>/dev/null; then
    echo "   ⚠️  DRY_RUN=false (production режим)"
    echo "   ⚠️  ВНИМАНИЕ: Изменения будут применены к NetBox!"
else
    echo "   ℹ️  DRY_RUN не установлен (по умолчанию: false)"
fi

# 7. ENABLE_PHYSICAL_DELETION проверка
echo ""
echo "7. Проверка настройки физического удаления..."
if grep -q "^ENABLE_PHYSICAL_DELETION=true" .env 2>/dev/null; then
    echo "   ⚠️  ENABLE_PHYSICAL_DELETION=true"
    echo "   ⚠️  ВНИМАНИЕ: Устройства будут УДАЛЯТЬСЯ физически!"
    echo "   ⚠️  Убедитесь что это то что вы хотите!"
elif grep -q "^ENABLE_PHYSICAL_DELETION=false" .env 2>/dev/null; then
    echo "   ✅ ENABLE_PHYSICAL_DELETION=false (безопасно)"
else
    echo "   ✅ ENABLE_PHYSICAL_DELETION не установлен (по умолчанию: false)"
fi

# Финальная сводка
echo ""
echo "======================================"
echo "📋 ФИНАЛЬНЫЙ ЧЕКЛИСТ:"
echo "======================================"
echo ""
echo "Перед запуском убедитесь что:"
echo ""
echo "  1. ✅ Создан бэкап базы NetBox"
echo "  2. ✅ В NetBox UI добавлено поле 'decommissioned_date'"
echo "  3. ✅ Файл .env содержит все необходимые настройки"
echo "  4. ✅ DRY_RUN=true для первого запуска"
echo "  5. ✅ ENABLE_PHYSICAL_DELETION=false (если не уверены)"
echo ""
echo "======================================"
echo "🚀 Готовы к запуску!"
echo "======================================"
echo ""
echo "Команды для запуска:"
echo ""
echo "  # Тестовый запуск:"
echo "  DRY_RUN=true python main.py --verbose"
echo ""
echo "  # Production запуск:"
echo "  python main.py"
echo ""
