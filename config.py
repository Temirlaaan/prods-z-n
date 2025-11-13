#!/usr/bin/env python3
"""
Конфигурация для синхронизации Zabbix → NetBox
"""
import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# === ОСНОВНЫЕ НАСТРОЙКИ ===
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '50'))
HOST_LIMIT = int(os.getenv('HOST_LIMIT')) if os.getenv('HOST_LIMIT') else None
TIMEOUT = int(os.getenv('TIMEOUT', '10'))

# === ZABBIX ===
ZABBIX_URL = os.getenv('ZABBIX_URL', 'http://zabbix.local')
ZABBIX_USER = os.getenv('ZABBIX_USER')
ZABBIX_PASSWORD = os.getenv('ZABBIX_PASSWORD')

# === NETBOX ===
NETBOX_URL = os.getenv('NETBOX_URL', 'http://netbox.local')
NETBOX_TOKEN = os.getenv('NETBOX_TOKEN')

# === REDIS ===
REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true').lower() == 'true'
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_DB = int(os.getenv('REDIS_DB', '0'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_KEY_PREFIX = os.getenv('REDIS_KEY_PREFIX', 'zabbix_host:')
REDIS_TTL = int(os.getenv('REDIS_TTL', '86400'))  # 24 часа

# === TELEGRAM ===
TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'true').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_PARSE_MODE = os.getenv('TELEGRAM_PARSE_MODE', 'HTML')  # HTML или Markdown
TELEGRAM_DISABLE_NOTIFICATION = os.getenv('TELEGRAM_DISABLE_NOTIFICATION', 'false').lower() == 'true'

# === ЛОГИРОВАНИЕ ===
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DIR = os.getenv('LOG_DIR', 'logs')

# === МАППИНГИ ===

# IP подсети → Site
SITE_MAPPING = {
    '10.11': 'DC Kabanbay-Batyr28',
    '10.127': 'DC Almaty',
    '10.13': 'DC Karaganda',
    '10.14': 'DC Atyrau',
    '10.10': 'DC Konaeva10',
    '192.168': 'DC Konaeva10'  # Добавлено для решения ошибки
}

# Site → Location
LOCATION_MAPPING = {
    'DC Kabanbay-Batyr28': 'city Astana street Kabanbay batyr 28',
    'DC Almaty': 'city Almaty street Karasay Batyr 55',
    'DC Karaganda': 'city Karaganda street 132-й учетный квартал участок 168',
    'DC Atyrau': 'city Atyrau street XXX',
    'DC Konaeva10': 'city Astana street Konaeva 10'
}

# Vendor + Model → U-Height
U_HEIGHT_MAPPING = {
    'Dell Inc. PowerEdge R640': 1,
    'Dell Inc. PowerEdge R740': 2,
    'Dell PowerEdge R640': 1,
    'Dell PowerEdge R740': 2,
    'HPE ProLiant DL360 Gen10': 1,
    'HPE ProLiant DL380 Gen10': 2,
    'Huawei CH121 V3': 1,
    'Huawei RH1288 V3': 1,
    'Huawei RH2288H V3': 2,
    'Huawei RH5885H V3': 4,
    'Huawei Technologies Co., Ltd. RH5885H V3': 4,
    'Huawei Technologies Co., Ltd. To be filled by O.E.M.': 4,
    'Lenovo J900XBXR': 1,
    'Lenovo ThinkAgile VX7531 Node': 2,
    'Lenovo ThinkSystem SR645': 1,
    'Lenovo ThinkSystem SR650': 2,
    'VMware Virtual Platform': 0,  # Виртуальная машина
    
    # Добавляем маппинги для Unknown моделей
    'Dell Unknown': 2,
    'HPE Unknown': 2,
    'Huawei Unknown': 2,
    'Lenovo Unknown': 2,
    'Unknown Unknown': 2,
    'Generic Server': 2
}

# Default Site если не определен по IP
DEFAULT_SITE = 'DC Konaeva10'

# === CUSTOM FIELDS в NetBox ===
# ВАЖНО: Эти поля должны быть созданы в NetBox UI
CUSTOM_FIELDS = [
    'cpu_model',        # Модель процессора
    'memory_size',      # Размер памяти
    'os_name',          # Имя ОС
    'os_version',       # Версия ОС
    'vsphere_cluster',  # vSphere кластер
    'rack_location',    # Локация в стойке (текст)
    'zabbix_hostid',    # ID хоста в Zabbix
    'last_sync',        # Последняя синхронизация
    'serial_number',    # Серийный номер
    'asset_tag',        # Инвентарный номер
    'rack_name',        # Имя стойки из Zabbix
    'rack_unit',        # Позиция U в стойке
    'decommissioned_date',  # НОВОЕ: Дата decommissioning
]

# === МАППИНГ ПОЛЕЙ ZABBIX → NETBOX ===
# Как поля из Zabbix inventory мапятся в NetBox
ZABBIX_TO_NETBOX_MAPPING = {
    # Основные данные
    'vendor': 'manufacturer',
    'model': 'device_type',
    'serialno_a': 'serial_number',     # Серийный номер
    'asset_tag': 'asset_tag',          # Инвентарный номер
    
    # Расположение
    'location': 'rack_location',       # Текстовое описание локации
    'software_app_b': 'rack_name',       # Имя стойки (НЕ location_lat!)
    'location_lon': 'rack_unit',       # Используем lon для позиции U
    
    # Характеристики
    'hardware': 'cpu_model',
    'software_app_a': 'memory_size',
    'os': 'os_name',
    'os_short': 'os_version',
    'alias': 'vsphere_cluster',
}

# === ФИЛЬТРЫ ДЛЯ ZABBIX ===
# Шаблоны для исключения
EXCLUDED_TEMPLATES = [
    'Juniper by SNMP',
    'Template Net SNMP',
    'Template Module Generic SNMP'
]

# Группы для исключения
EXCLUDED_GROUPS = [
    'Network',
    'DataStore',
    'Virtual machines'
]

# Шаблоны для включения (только эти)
INCLUDED_TEMPLATES = [
    'VMware Hypervisor'
]

# === НАСТРОЙКИ УДАЛЕНИЯ ===
# Через сколько дней неактивности помечать устройство как decommissioned
DECOMMISSION_AFTER_DAYS = int(os.getenv('DECOMMISSION_AFTER_DAYS', '30'))

# Удалять ли устройства физически из NetBox
DELETE_DECOMMISSIONED = os.getenv('DELETE_DECOMMISSIONED', 'false').lower() == 'true'

# Через сколько дней в статусе decommissioning удалять физически
DELETE_AFTER_DECOMMISSION_DAYS = int(os.getenv('DELETE_AFTER_DECOMMISSION_DAYS', '90'))

# Включить физическое удаление (ОСТОРОЖНО!)
ENABLE_PHYSICAL_DELETION = os.getenv('ENABLE_PHYSICAL_DELETION', 'false').lower() == 'true'

# === НАСТРОЙКИ ЗАЩИТЫ ДАННЫХ ===
# Поля которые НЕ должны перезаписываться из Zabbix
PROTECTED_FIELDS_STR = os.getenv('PROTECTED_FIELDS', '')
PROTECTED_FIELDS = set(filter(None, PROTECTED_FIELDS_STR.split(',')))

# Custom fields которые НЕ перезаписываются
PROTECTED_CUSTOM_FIELDS_STR = os.getenv('PROTECTED_CUSTOM_FIELDS', '')
PROTECTED_CUSTOM_FIELDS = set(filter(None, PROTECTED_CUSTOM_FIELDS_STR.split(',')))

# === НАСТРОЙКИ ОЧИСТКИ ===
# Что делать с orphaned IP адресами
ORPHANED_IP_ACTION = os.getenv('ORPHANED_IP_ACTION', 'deprecated')  # deprecated, delete, keep

# Проверять конфликты позиций в стойках
CHECK_RACK_CONFLICTS = os.getenv('CHECK_RACK_CONFLICTS', 'true').lower() == 'true'

# === ВАЛИДАЦИЯ ===
def validate_config():
    """Проверка обязательных параметров конфигурации"""
    errors = []
    
    if not ZABBIX_USER:
        errors.append("ZABBIX_USER не установлен")
    if not ZABBIX_PASSWORD:
        errors.append("ZABBIX_PASSWORD не установлен")
    if not NETBOX_TOKEN:
        errors.append("NETBOX_TOKEN не установлен")
    
    if TELEGRAM_ENABLED and not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN не установлен, но TELEGRAM_ENABLED=true")
    
    if TELEGRAM_ENABLED and not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID не установлен, но TELEGRAM_ENABLED=true")
    
    if REDIS_ENABLED and REDIS_PASSWORD and not REDIS_PASSWORD:
        errors.append("REDIS_PASSWORD может потребоваться")
    
    return errors
