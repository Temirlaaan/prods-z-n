#!/usr/bin/env python3
"""
Главный файл для запуска синхронизации Zabbix → NetBox
"""
import sys
import os
import logging
import argparse
from datetime import datetime, timedelta
import urllib3
import config
from sync import ServerSync
from utils import NotificationHelper

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройка логирования
def setup_logging():
    """Настройка системы логирования"""
    import os
    os.makedirs(config.LOG_DIR, exist_ok=True)
    
    log_file = f"{config.LOG_DIR}/sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # Создаем форматтер
    formatter = logging.Formatter(config.LOG_FORMAT)
    
    # Файловый handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Консольный handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Настраиваем root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Уменьшаем уровень логирования для библиотек
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('pynetbox').setLevel(logging.WARNING)
    logging.getLogger('pyzabbix').setLevel(logging.WARNING)

    return logger, log_file


def cleanup_old_logs():
    """Удаление логов старше LOG_RETENTION_DAYS дней"""
    if not os.path.exists(config.LOG_DIR):
        return 0

    cutoff_date = datetime.now() - timedelta(days=config.LOG_RETENTION_DAYS)
    deleted_count = 0

    for filename in os.listdir(config.LOG_DIR):
        if not filename.endswith('.log'):
            continue

        filepath = os.path.join(config.LOG_DIR, filename)
        try:
            # Получаем время модификации файла
            file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            if file_mtime < cutoff_date:
                os.remove(filepath)
                deleted_count += 1
        except (OSError, ValueError):
            continue

    return deleted_count


def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description='Синхронизация серверов из Zabbix в NetBox'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Тестовый запуск без изменений'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        help='Ограничить количество хостов'
    )
    
    parser.add_argument(
        '--no-redis',
        action='store_true',
        help='Запуск без Redis (все хосты как новые)'
    )
    
    parser.add_argument(
        '--no-telegram',
        action='store_true',
        help='Отключить уведомления в Telegram'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Подробный вывод (DEBUG)'
    )
    
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Только проверить конфигурацию'
    )
    
    parser.add_argument(
        '--check-decommissioned',
        action='store_true',
        help='Проверить и пометить неактивные устройства'
    )
    
    return parser.parse_args()


def validate_configuration():
    """Проверка конфигурации"""
    errors = config.validate_config()
    
    if errors:
        print("❌ Ошибки конфигурации:")
        for error in errors:
            print(f"  • {error}")
        return False
    
    print("✅ Конфигурация валидна")
    return True


def main():
    """Основная функция"""
    # Парсим аргументы
    args = parse_arguments()
    
    # Применяем аргументы к конфигурации
    if args.dry_run:
        config.DRY_RUN = True
    if args.limit:
        config.HOST_LIMIT = args.limit
    if args.no_redis:
        config.REDIS_ENABLED = False
    if args.no_telegram:
        config.TELEGRAM_ENABLED = False
    if args.verbose:
        config.LOG_LEVEL = 'DEBUG'
    
    # Валидация конфигурации
    if args.validate_only:
        sys.exit(0 if validate_configuration() else 1)
    
    if not validate_configuration():
        sys.exit(1)

    # Настройка логирования
    logger, log_file = setup_logging()

    # Очистка старых логов
    deleted_logs = cleanup_old_logs()
    if deleted_logs > 0:
        logger.info(f"🗑 Удалено {deleted_logs} старых лог-файлов (старше {config.LOG_RETENTION_DAYS} дней)")

    logger.info("=" * 60)
    logger.info("ЗАПУСК СИНХРОНИЗАЦИИ ZABBIX → NETBOX")
    logger.info(f"Лог файл: {log_file}")
    if config.DRY_RUN:
        logger.info("🔸 MODE: DRY RUN (тестовый режим)")
    if config.HOST_LIMIT:
        logger.info(f"🔸 LIMIT: {config.HOST_LIMIT} хостов")
    logger.info("=" * 60)
    
    # Создаем объект синхронизации
    sync = ServerSync()
    
    try:
        # Подключаемся к сервисам
        if not sync.connect_services():
            logger.error("Не удалось подключиться к необходимым сервисам")
            sys.exit(1)
        
        # Запускаем синхронизацию
        stats = sync.run_sync()
        
        # Отправляем уведомление ТОЛЬКО если есть значимые изменения
        has_changes = (
            stats['new_hosts'] or
            stats['changed_hosts'] or
            stats['error_hosts'] or
            stats['decommissioned_hosts'] or
            stats['new_models']
        )

        if config.TELEGRAM_ENABLED and has_changes:
            message = NotificationHelper.format_sync_summary(
                stats['new_hosts'],
                stats['changed_hosts'],
                len(stats['new_hosts']) + len(stats['changed_hosts']),
                len(stats['error_hosts']),
                new_models=stats['new_models'],
                decommissioned=stats['decommissioned_hosts'],
                detailed_changes=stats.get('detailed_changes', {}),
                error_details=stats.get('error_details', {}),
                format_type=config.TELEGRAM_PARSE_MODE
            )
            sync.send_telegram_notification(message)
        elif config.TELEGRAM_ENABLED:
            logger.info("📭 Нет значимых изменений — уведомление не отправлено")
        
        # Определяем код выхода
        if stats['error_hosts']:
            sys.exit(2)  # Есть ошибки
        else:
            sys.exit(0)  # Успешно
    
    except KeyboardInterrupt:
        logger.info("\n⚠️ Прервано пользователем")
        sys.exit(130)
    
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        
        # Уведомление об ошибке
        if config.TELEGRAM_ENABLED and sync.telegram_bot:
            error_msg = NotificationHelper.format_error_notification(
                str(e),
                {'log_file': log_file},
                format_type=config.TELEGRAM_PARSE_MODE
            )
            sync.send_telegram_notification(error_msg)
        
        sys.exit(1)
    
    finally:
        # Отключаемся от сервисов
        sync.disconnect_services()
        logger.info("Завершение работы")


if __name__ == "__main__":
    main()