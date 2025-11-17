# Настройка автоматической синхронизации

## 📋 Что было создано

Для автоматизации синхронизации созданы 2 файла:

1. **`run-sync.sh`** - Основной скрипт запуска синхронизации
2. **`setup-cron.sh`** - Установщик cron задания (один раз)

---

## 🚀 Быстрая установка

### Шаг 1: Скопируйте файлы в ваше рабочее окружение

```bash
# На вашем сервере
cd /home/admintelegrambot/cloud-services/prods-z-n

# Скопируйте новые скрипты
# (файлы run-sync.sh и setup-cron.sh уже в репозитории)
git pull origin claude/project-logic-analysis-011CV5GjbVGGhUPFT3uuevqp

# Или скопируйте вручную если нужно
chmod +x run-sync.sh setup-cron.sh
```

### Шаг 2: Проверьте пути в скриптах

Откройте `run-sync.sh` и убедитесь что путь правильный:

```bash
nano run-sync.sh

# Должно быть:
PROJECT_DIR="/home/admintelegrambot/cloud-services/prods-z-n"
```

### Шаг 3: Тестовый запуск

```bash
# Запустите скрипт вручную для проверки
./run-sync.sh

# Проверьте логи
tail -50 /var/log/zabbix-netbox-sync.log
```

### Шаг 4: Установите cron

```bash
# Запустите установщик
./setup-cron.sh

# Проверьте что задание добавлено
crontab -l
```

---

## 📅 Расписание

**По умолчанию:** Каждые 2 дня в 2:00 ночи

```
0 2 */2 * * /path/to/run-sync.sh >> /var/log/zabbix-netbox-sync.log 2>&1
```

### Изменить расписание

Если хотите другое расписание, отредактируйте crontab:

```bash
crontab -e
```

**Примеры:**

```bash
# Каждый день в 3:00
0 3 * * * /path/to/run-sync.sh >> /var/log/zabbix-netbox-sync.log 2>&1

# Каждые 12 часов
0 */12 * * * /path/to/run-sync.sh >> /var/log/zabbix-netbox-sync.log 2>&1

# Каждый понедельник в 2:00
0 2 * * 1 /path/to/run-sync.sh >> /var/log/zabbix-netbox-sync.log 2>&1

# Первого числа каждого месяца
0 2 1 * * /path/to/run-sync.sh >> /var/log/zabbix-netbox-sync.log 2>&1
```

---

## 📊 Мониторинг

### Просмотр логов

```bash
# Последние 50 строк
tail -50 /var/log/zabbix-netbox-sync.log

# Живой просмотр (следить в реальном времени)
tail -f /var/log/zabbix-netbox-sync.log

# Поиск ошибок
grep "ERROR\|ОШИБКА\|❌" /var/log/zabbix-netbox-sync.log

# Поиск успешных синхронизаций
grep "✅ Синхронизация завершена успешно" /var/log/zabbix-netbox-sync.log
```

### Проверка статуса

```bash
# Когда было последнее выполнение?
ls -lh /var/log/zabbix-netbox-sync.log

# Статистика последней синхронизации
tail -100 logs/sync_*.log | grep "📈 Результаты"

# Проверка cron задания
crontab -l | grep run-sync
```

---

## 🔧 Управление

### Остановить автоматическую синхронизацию

```bash
# Временно отключить (закомментировать)
crontab -e
# Добавьте # в начале строки с run-sync.sh

# Или удалите задание полностью
crontab -e
# Удалите строку с run-sync.sh
```

### Запустить вручную

```bash
cd /home/admintelegrambot/cloud-services/prods-z-n
./run-sync.sh

# Или напрямую через Docker
docker compose run --rm sync-app
```

### Изменить настройки

Все настройки в `.env` файле:

```bash
nano .env

# Важные параметры:
DRY_RUN=false                        # Режим работы
DECOMMISSION_AFTER_DAYS=7            # Дней до decommissioning
DELETE_AFTER_DECOMMISSION_DAYS=30    # Дней до удаления
ENABLE_PHYSICAL_DELETION=false       # Физическое удаление
```

---

## 🐛 Решение проблем

### Cron не запускается

```bash
# Проверьте что cron сервис запущен
sudo systemctl status cron

# Если не запущен
sudo systemctl start cron
sudo systemctl enable cron
```

### Скрипт не выполняется

```bash
# Проверьте права
ls -lh run-sync.sh
# Должно быть: -rwxr-xr-x

# Если нет:
chmod +x run-sync.sh

# Проверьте путь в crontab
crontab -l
# Путь должен быть абсолютный: /home/admintelegrambot/cloud-services/prods-z-n/run-sync.sh
```

### Логи не пишутся

```bash
# Создайте лог файл вручную
sudo touch /var/log/zabbix-netbox-sync.log
sudo chown $USER:$USER /var/log/zabbix-netbox-sync.log
chmod 664 /var/log/zabbix-netbox-sync.log
```

### Docker compose не работает в cron

```bash
# Убедитесь что docker доступен для вашего пользователя
groups $USER | grep docker

# Если нет, добавьте:
sudo usermod -aG docker $USER
# Затем перелогиньтесь
```

---

## 📧 Уведомления

У вас уже настроены Telegram уведомления в `.env`:

```bash
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=ваш_токен
TELEGRAM_CHAT_ID=ваш_chat_id
```

Вы будете получать уведомления о:
- ✅ Успешных синхронизациях
- ❌ Ошибках
- 🔄 Переименованиях устройств
- 🗑️ Decommissioning
- ⚠️ Конфликтах стоек

---

## 🔄 Альтернатива: APScheduler

Если все же хотите использовать APScheduler вместо cron:

### Плюсы APScheduler:
- ✅ Управление из Python кода
- ✅ Более гибкие триггеры
- ✅ Легче интегрировать с веб-интерфейсом

### Минусы APScheduler:
- ❌ Нужен постоянно работающий процесс
- ❌ Больше потребление ресурсов
- ❌ Сложнее для редких задач

### Быстрая установка APScheduler:

```bash
# 1. Установите библиотеку
pip install apscheduler

# 2. Создайте scheduler.py
cat > scheduler.py << 'EOF'
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_sync():
    logger.info("🚀 Запуск синхронизации...")
    result = subprocess.run(
        ["docker", "compose", "run", "--rm", "sync-app"],
        cwd="/home/admintelegrambot/cloud-services/prods-z-n",
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        logger.info("✅ Синхронизация завершена успешно")
    else:
        logger.error(f"❌ Ошибка синхронизации: {result.stderr}")

scheduler = BlockingScheduler()
scheduler.add_job(
    run_sync,
    trigger=IntervalTrigger(days=2),
    id='zabbix_netbox_sync',
    name='Zabbix → NetBox Sync'
)

if __name__ == "__main__":
    logger.info("📅 Планировщик запущен. Синхронизация каждые 2 дня.")
    scheduler.start()
EOF

# 3. Запустите как systemd сервис
sudo nano /etc/systemd/system/zabbix-netbox-sync.service

# Содержимое:
[Unit]
Description=Zabbix-NetBox Sync Scheduler
After=docker.service

[Service]
Type=simple
User=admintelegrambot
WorkingDirectory=/home/admintelegrambot/cloud-services/prods-z-n
ExecStart=/usr/bin/python3 scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target

# 4. Активируйте сервис
sudo systemctl daemon-reload
sudo systemctl enable zabbix-netbox-sync.service
sudo systemctl start zabbix-netbox-sync.service
sudo systemctl status zabbix-netbox-sync.service
```

---

## 📝 Рекомендации

**Для вашего случая (синхронизация каждые 2 дня):**

✅ **Используйте cron** - проще, надежнее, меньше ресурсов

❌ **APScheduler избыточен** - для редких задач cron оптимальнее

---

## ✅ Чеклист установки

- [ ] Файлы `run-sync.sh` и `setup-cron.sh` скопированы в рабочую директорию
- [ ] Права на выполнение установлены (`chmod +x`)
- [ ] Пути в скриптах проверены и корректны
- [ ] Тестовый запуск `./run-sync.sh` выполнен успешно
- [ ] Cron задание установлено (`./setup-cron.sh`)
- [ ] Cron задание проверено (`crontab -l`)
- [ ] Лог файл `/var/log/zabbix-netbox-sync.log` создан
- [ ] Настройки `.env` проверены (особенно `ENABLE_PHYSICAL_DELETION`)
- [ ] Telegram уведомления работают

---

**Готово! Синхронизация будет запускаться автоматически каждые 2 дня в 2:00 ночи.**

Следующий запуск через 2 дня. Мониторьте логи первую неделю!
