#!/usr/bin/env python3
"""
Скрипт инициализации NetBox для синхронизации с Zabbix

Создает все необходимые сущности:
- Sites (дата-центры)
- Manufacturers (производители)
- Device Roles (роли устройств)
- Device Types (типы устройств)
- Device Bay Templates (для chassis)
- Custom Fields
- Platforms
- Chassis Devices

Скрипт идемпотентен - безопасен для повторного запуска.
"""
import sys
import os
import argparse

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pynetbox
import urllib3
from dotenv import load_dotenv

# Отключаем SSL предупреждения
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Загрузка переменных окружения
load_dotenv()

# === КОНФИГУРАЦИЯ ===
NETBOX_URL = os.getenv('NETBOX_URL', 'https://web-netbox.t-cloud.kz/')
NETBOX_TOKEN = os.getenv('NETBOX_TOKEN')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'

# === ДАННЫЕ ДЛЯ СОЗДАНИЯ ===

SITES = [
    {
        'name': 'DC Kabanbay-Batyr28',
        'slug': 'dc-kabanbay-batyr28',
        'status': 'active',
        'physical_address': 'г. Астана, ул. Кабанбай батыра 28',
        'description': 'Дата-центр Кабанбай Батыра 28, Астана (подсеть 10.11.x.x)'
    },
    {
        'name': 'DC Almaty',
        'slug': 'dc-almaty',
        'status': 'active',
        'physical_address': 'г. Алматы, ул. Карасай Батыра 55',
        'description': 'Дата-центр Алматы (подсеть 10.127.x.x)'
    },
    {
        'name': 'DC Karaganda',
        'slug': 'dc-karaganda',
        'status': 'active',
        'physical_address': 'г. Караганда, 132-й учетный квартал, участок 168',
        'description': 'Дата-центр Караганда (подсеть 10.13.x.x)'
    },
    {
        'name': 'DC Atyrau',
        'slug': 'dc-atyrau',
        'status': 'active',
        'physical_address': 'г. Атырау',
        'description': 'Дата-центр Атырау (подсеть 10.14.x.x)'
    },
    {
        'name': 'DC Konaeva10',
        'slug': 'dc-konaeva10',
        'status': 'active',
        'physical_address': 'г. Астана, ул. Конаева 10',
        'description': 'Дата-центр Конаева 10, Астана - DEFAULT (подсети 10.10.x.x, 192.168.x.x)'
    }
]

MANUFACTURERS = [
    {'name': 'Dell', 'slug': 'dell', 'description': 'Dell Technologies'},
    {'name': 'HPE', 'slug': 'hpe', 'description': 'Hewlett Packard Enterprise'},
    {'name': 'Huawei', 'slug': 'huawei', 'description': 'Huawei Technologies'},
    {'name': 'Lenovo', 'slug': 'lenovo', 'description': 'Lenovo Group'},
    {'name': 'Cisco', 'slug': 'cisco', 'description': 'Cisco Systems'},
    {'name': 'VMware', 'slug': 'vmware', 'description': 'VMware Inc'},
    {'name': 'Generic', 'slug': 'generic', 'description': 'Generic/Unknown manufacturer'}
]

DEVICE_ROLES = [
    {
        'name': 'Server',
        'slug': 'server',
        'color': '0000ff',  # синий
        'vm_role': False,
        'description': 'Физический сервер (rack-mounted)'
    },
    {
        'name': 'Blade Server',
        'slug': 'blade-server',
        'color': '00ff00',  # зелёный
        'vm_role': False,
        'description': 'Blade сервер (устанавливается в chassis)'
    },
    {
        'name': 'Chassis',
        'slug': 'chassis',
        'color': 'ff9800',  # оранжевый
        'vm_role': False,
        'description': 'Шасси для blade серверов'
    }
]

DEVICE_TYPES = [
    # === RACK SERVERS ===
    # Dell
    {'manufacturer': 'Dell', 'model': 'PowerEdge R640', 'slug': 'dell-poweredge-r640', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'Dell', 'model': 'PowerEdge R740', 'slug': 'dell-poweredge-r740', 'u_height': 2, 'is_full_depth': True},

    # HPE
    {'manufacturer': 'HPE', 'model': 'ProLiant DL360 Gen10', 'slug': 'hpe-proliant-dl360-gen10', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'HPE', 'model': 'ProLiant DL380 Gen10', 'slug': 'hpe-proliant-dl380-gen10', 'u_height': 2, 'is_full_depth': True},

    # Huawei (rack)
    {'manufacturer': 'Huawei', 'model': 'RH1288 V3', 'slug': 'huawei-rh1288-v3', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'RH2288H V3', 'slug': 'huawei-rh2288h-v3', 'u_height': 2, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'RH5885H V3', 'slug': 'huawei-rh5885h-v3', 'u_height': 4, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'To be filled by O.E.M.', 'slug': 'huawei-unknown', 'u_height': 2, 'is_full_depth': True},

    # Lenovo
    {'manufacturer': 'Lenovo', 'model': 'ThinkSystem SR645', 'slug': 'lenovo-thinksystem-sr645', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'Lenovo', 'model': 'ThinkSystem SR650', 'slug': 'lenovo-thinksystem-sr650', 'u_height': 2, 'is_full_depth': True},
    {'manufacturer': 'Lenovo', 'model': 'ThinkAgile VX7531 Node', 'slug': 'lenovo-thinkagile-vx7531', 'u_height': 2, 'is_full_depth': True},
    {'manufacturer': 'Lenovo', 'model': 'J900XBXR', 'slug': 'lenovo-j900xbxr', 'u_height': 1, 'is_full_depth': True},

    # Generic/Fallback
    {'manufacturer': 'Generic', 'model': 'Generic Server', 'slug': 'generic-server', 'u_height': 2, 'is_full_depth': True},
    {'manufacturer': 'Generic', 'model': 'Unknown', 'slug': 'generic-unknown', 'u_height': 2, 'is_full_depth': True},

    # VMware (virtual - 0U)
    {'manufacturer': 'VMware', 'model': 'Virtual Platform', 'slug': 'vmware-virtual-platform', 'u_height': 0, 'is_full_depth': False},

    # === BLADE SERVERS (u_height=0, subdevice_role=child) ===
    {
        'manufacturer': 'Cisco',
        'model': 'UCSB-B200-M4',
        'slug': 'cisco-ucsb-b200-m4',
        'u_height': 0,
        'is_full_depth': False,
        'subdevice_role': 'child',
        'description': 'Cisco UCS B200 M4 Blade Server'
    },
    {
        'manufacturer': 'Huawei',
        'model': 'CH121 V3',
        'slug': 'huawei-ch121-v3',
        'u_height': 0,
        'is_full_depth': False,
        'subdevice_role': 'child',
        'description': 'Huawei CH121 V3 Compute Node (Blade)'
    },

    # === CHASSIS (subdevice_role=parent) ===
    {
        'manufacturer': 'Cisco',
        'model': 'UCS 5108 Blade Server Chassis',
        'slug': 'cisco-ucs-5108',
        'u_height': 6,
        'is_full_depth': True,
        'subdevice_role': 'parent',
        'description': 'Cisco UCS 5108 Chassis - вмещает до 8 blade серверов'
    },
    {
        'manufacturer': 'Huawei',
        'model': 'E9000 Converged Infrastructure Blade Chassis',
        'slug': 'huawei-e9000',
        'u_height': 12,
        'is_full_depth': True,
        'subdevice_role': 'parent',
        'description': 'Huawei E9000 Chassis - вмещает до 16 blade серверов'
    }
]

# Device Bay Templates для Chassis
DEVICE_BAY_TEMPLATES = {
    'cisco-ucs-5108': [
        {'name': f'Blade Bay {i}', 'description': f'Slot for blade server {i}'}
        for i in range(1, 9)  # 8 слотов
    ],
    'huawei-e9000': [
        {'name': f'Slot {i}', 'description': f'Slot for compute node {i}'}
        for i in range(1, 17)  # 16 слотов
    ]
}

CUSTOM_FIELDS = [
    {'name': 'cpu_model', 'label': 'CPU Model', 'type': 'text', 'description': 'Модель процессора из Zabbix'},
    {'name': 'memory_size', 'label': 'Memory Size (GB)', 'type': 'text', 'description': 'Размер оперативной памяти'},
    {'name': 'os_name', 'label': 'OS Name', 'type': 'text', 'description': 'Операционная система'},
    {'name': 'os_version', 'label': 'OS Version', 'type': 'text', 'description': 'Версия ОС'},
    {'name': 'vsphere_cluster', 'label': 'vSphere Cluster', 'type': 'text', 'description': 'Кластер vSphere'},
    {'name': 'rack_location', 'label': 'Rack Location', 'type': 'text', 'description': 'Текстовое описание локации'},
    {'name': 'zabbix_hostid', 'label': 'Zabbix Host ID', 'type': 'text', 'description': 'ID хоста в Zabbix (ключ синхронизации)'},
    {'name': 'last_sync', 'label': 'Last Sync', 'type': 'date', 'description': 'Дата последней синхронизации'},
    {'name': 'serial_number', 'label': 'Serial Number', 'type': 'text', 'description': 'Серийный номер из Zabbix'},
    {'name': 'asset_tag', 'label': 'Asset Tag', 'type': 'text', 'description': 'Инвентарный номер'},
    {'name': 'rack_name', 'label': 'Rack Name (Zabbix)', 'type': 'text', 'description': 'Имя стойки из Zabbix'},
    {'name': 'rack_unit', 'label': 'Rack Unit (Zabbix)', 'type': 'text', 'description': 'Позиция U из Zabbix'},
    {'name': 'decommissioned_date', 'label': 'Decommissioned Date', 'type': 'date', 'description': 'Дата decommissioning'}
]

PLATFORMS = [
    {'name': 'VMware ESXi', 'slug': 'vmware-esxi', 'manufacturer': 'VMware', 'description': 'VMware ESXi Hypervisor'}
]

# Chassis устройства для создания в DEFAULT_SITE
CHASSIS_DEVICES = [
    {
        'name': 'Cisco-UCS-Chassis-01',
        'device_type_model': 'UCS 5108 Blade Server Chassis',
        'role': 'Chassis',
        'site': 'DC Konaeva10',
        'status': 'active',
        'comments': 'Auto-created chassis for Cisco blade servers. Move to correct rack manually.'
    },
    {
        'name': 'Huawei-E9000-Chassis-01',
        'device_type_model': 'E9000 Converged Infrastructure Blade Chassis',
        'role': 'Chassis',
        'site': 'DC Konaeva10',
        'status': 'active',
        'comments': 'Auto-created chassis for Huawei blade servers. Move to correct rack manually.'
    }
]


class FakeObject:
    """Фиктивный объект для dry-run режима"""
    _id_counter = 9000

    def __init__(self, name, **kwargs):
        FakeObject._id_counter += 1
        self.id = FakeObject._id_counter
        self.name = name
        for key, value in kwargs.items():
            setattr(self, key, value)


class NetBoxInitializer:
    """Класс для инициализации NetBox"""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.nb = None
        self.stats = {
            'sites': {'created': 0, 'skipped': 0, 'errors': 0},
            'manufacturers': {'created': 0, 'skipped': 0, 'errors': 0},
            'device_roles': {'created': 0, 'skipped': 0, 'errors': 0},
            'device_types': {'created': 0, 'skipped': 0, 'errors': 0},
            'bay_templates': {'created': 0, 'skipped': 0, 'errors': 0},
            'custom_fields': {'created': 0, 'skipped': 0, 'errors': 0},
            'platforms': {'created': 0, 'skipped': 0, 'errors': 0},
            'chassis': {'created': 0, 'skipped': 0, 'errors': 0}
        }
        self.manufacturers_cache = {}
        self.device_types_cache = {}
        self.sites_cache = {}
        self.roles_cache = {}

    def connect(self):
        """Подключение к NetBox"""
        if not NETBOX_TOKEN:
            print("NETBOX_TOKEN не установлен в .env")
            return False

        try:
            self.nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
            self.nb.http_session.verify = VERIFY_SSL
            # Тестовый запрос
            self.nb.dcim.sites.count()
            print(f"  Подключено к NetBox: {NETBOX_URL}")
            return True
        except Exception as e:
            print(f"  Ошибка подключения к NetBox: {e}")
            return False

    def create_sites(self):
        """Создание Sites"""
        print("\n[1/8] SITES")

        for site_data in SITES:
            try:
                existing = self.nb.dcim.sites.get(name=site_data['name'])

                if existing:
                    print(f"  [SKIP] {site_data['name']} - уже существует")
                    self.stats['sites']['skipped'] += 1
                    self.sites_cache[site_data['name']] = existing
                else:
                    if not self.dry_run:
                        new_site = self.nb.dcim.sites.create(**site_data)
                        self.sites_cache[site_data['name']] = new_site
                        print(f"  [OK] {site_data['name']} - создан")
                    else:
                        # В dry-run создаем фиктивный объект для зависимостей
                        self.sites_cache[site_data['name']] = FakeObject(site_data['name'], slug=site_data['slug'])
                        print(f"  [DRY] {site_data['name']} - будет создан")
                    self.stats['sites']['created'] += 1

            except Exception as e:
                print(f"  [ERR] {site_data['name']}: {e}")
                self.stats['sites']['errors'] += 1

    def create_manufacturers(self):
        """Создание Manufacturers"""
        print("\n[2/8] MANUFACTURERS")

        for mfr_data in MANUFACTURERS:
            try:
                existing = self.nb.dcim.manufacturers.get(name=mfr_data['name'])

                if existing:
                    print(f"  [SKIP] {mfr_data['name']} - уже существует")
                    self.stats['manufacturers']['skipped'] += 1
                    self.manufacturers_cache[mfr_data['name']] = existing
                else:
                    if not self.dry_run:
                        new_mfr = self.nb.dcim.manufacturers.create(**mfr_data)
                        self.manufacturers_cache[mfr_data['name']] = new_mfr
                        print(f"  [OK] {mfr_data['name']} - создан")
                    else:
                        # В dry-run создаем фиктивный объект для зависимостей
                        self.manufacturers_cache[mfr_data['name']] = FakeObject(mfr_data['name'], slug=mfr_data['slug'])
                        print(f"  [DRY] {mfr_data['name']} - будет создан")
                    self.stats['manufacturers']['created'] += 1

            except Exception as e:
                print(f"  [ERR] {mfr_data['name']}: {e}")
                self.stats['manufacturers']['errors'] += 1

    def create_device_roles(self):
        """Создание Device Roles"""
        print("\n[3/8] DEVICE ROLES")

        for role_data in DEVICE_ROLES:
            try:
                existing = self.nb.dcim.device_roles.get(name=role_data['name'])

                if existing:
                    print(f"  [SKIP] {role_data['name']} - уже существует")
                    self.stats['device_roles']['skipped'] += 1
                    self.roles_cache[role_data['name']] = existing
                else:
                    if not self.dry_run:
                        new_role = self.nb.dcim.device_roles.create(**role_data)
                        self.roles_cache[role_data['name']] = new_role
                        print(f"  [OK] {role_data['name']} - создан")
                    else:
                        # В dry-run создаем фиктивный объект для зависимостей
                        self.roles_cache[role_data['name']] = FakeObject(role_data['name'], slug=role_data['slug'])
                        print(f"  [DRY] {role_data['name']} - будет создан")
                    self.stats['device_roles']['created'] += 1

            except Exception as e:
                print(f"  [ERR] {role_data['name']}: {e}")
                self.stats['device_roles']['errors'] += 1

    def create_device_types(self):
        """Создание Device Types"""
        print("\n[4/8] DEVICE TYPES")

        for dt_data in DEVICE_TYPES:
            mfr_name = dt_data.get('manufacturer')
            try:
                mfr_name = dt_data.pop('manufacturer')

                # Получаем manufacturer из кэша (включая фиктивные объекты в dry-run)
                manufacturer = self.manufacturers_cache.get(mfr_name)
                if not manufacturer:
                    manufacturer = self.nb.dcim.manufacturers.get(name=mfr_name)
                    if manufacturer:
                        self.manufacturers_cache[mfr_name] = manufacturer

                if not manufacturer:
                    print(f"  [ERR] {dt_data['model']}: Производитель {mfr_name} не найден")
                    self.stats['device_types']['errors'] += 1
                    dt_data['manufacturer'] = mfr_name  # Восстанавливаем
                    continue

                # Определяем тип устройства для вывода
                device_info = f"{mfr_name} {dt_data['model']} ({dt_data['u_height']}U"
                if dt_data.get('subdevice_role') == 'parent':
                    device_info += ", parent"
                elif dt_data.get('subdevice_role') == 'child':
                    device_info += ", child"
                device_info += ")"

                # В dry-run режиме не проверяем существование если manufacturer фиктивный
                if self.dry_run and isinstance(manufacturer, FakeObject):
                    self.device_types_cache[dt_data['slug']] = FakeObject(
                        dt_data['model'],
                        slug=dt_data['slug'],
                        u_height=dt_data['u_height']
                    )
                    print(f"  [DRY] {device_info} - будет создан")
                    self.stats['device_types']['created'] += 1
                else:
                    # Проверяем существование в реальном NetBox
                    existing = self.nb.dcim.device_types.get(
                        model=dt_data['model'],
                        manufacturer_id=manufacturer.id
                    )

                    if existing:
                        print(f"  [SKIP] {mfr_name} {dt_data['model']} - уже существует")
                        self.stats['device_types']['skipped'] += 1
                        self.device_types_cache[dt_data['slug']] = existing
                    else:
                        dt_data['manufacturer'] = manufacturer.id

                        if not self.dry_run:
                            new_dt = self.nb.dcim.device_types.create(**dt_data)
                            self.device_types_cache[dt_data['slug']] = new_dt
                            print(f"  [OK] {device_info} - создан")
                        else:
                            self.device_types_cache[dt_data['slug']] = FakeObject(
                                dt_data['model'],
                                slug=dt_data['slug'],
                                u_height=dt_data['u_height']
                            )
                            print(f"  [DRY] {device_info} - будет создан")
                        self.stats['device_types']['created'] += 1

                dt_data['manufacturer'] = mfr_name  # Восстанавливаем для следующих итераций

            except Exception as e:
                print(f"  [ERR] {dt_data.get('model', 'Unknown')}: {e}")
                self.stats['device_types']['errors'] += 1
                if mfr_name:
                    dt_data['manufacturer'] = mfr_name  # Восстанавливаем

    def create_device_bay_templates(self):
        """Создание Device Bay Templates для Chassis"""
        print("\n[5/8] DEVICE BAY TEMPLATES")

        for chassis_slug, bays in DEVICE_BAY_TEMPLATES.items():
            try:
                # Получаем device type из кэша (включая фиктивные объекты в dry-run)
                device_type = self.device_types_cache.get(chassis_slug)
                if not device_type:
                    device_type = self.nb.dcim.device_types.get(slug=chassis_slug)

                if not device_type:
                    print(f"  [ERR] Device type {chassis_slug} не найден")
                    self.stats['bay_templates']['errors'] += 1
                    continue

                # В dry-run режиме с фиктивным device_type просто показываем что будет создано
                if self.dry_run and isinstance(device_type, FakeObject):
                    print(f"  [DRY] {chassis_slug}: будет создано {len(bays)} bay slots")
                    self.stats['bay_templates']['created'] += len(bays)
                    continue

                # Проверяем существующие bay templates
                existing_bays = list(self.nb.dcim.device_bay_templates.filter(
                    device_type_id=device_type.id
                ))
                existing_names = {bay.name for bay in existing_bays}

                created_count = 0
                for bay_data in bays:
                    if bay_data['name'] in existing_names:
                        continue

                    bay_data['device_type'] = device_type.id

                    if not self.dry_run:
                        self.nb.dcim.device_bay_templates.create(**bay_data)
                    created_count += 1

                if created_count > 0:
                    if not self.dry_run:
                        print(f"  [OK] {chassis_slug}: создано {created_count} bay slots")
                    else:
                        print(f"  [DRY] {chassis_slug}: будет создано {created_count} bay slots")
                    self.stats['bay_templates']['created'] += created_count
                else:
                    print(f"  [SKIP] {chassis_slug}: все bay slots уже существуют")
                    self.stats['bay_templates']['skipped'] += len(bays)

            except Exception as e:
                print(f"  [ERR] {chassis_slug}: {e}")
                self.stats['bay_templates']['errors'] += 1

    def create_custom_fields(self):
        """Создание Custom Fields"""
        print("\n[6/8] CUSTOM FIELDS")

        # Маппинг типов
        type_mapping = {
            'text': 'text',
            'date': 'date',
            'integer': 'integer',
            'boolean': 'boolean'
        }

        for cf_data in CUSTOM_FIELDS:
            try:
                existing = self.nb.extras.custom_fields.get(name=cf_data['name'])

                if existing:
                    print(f"  [SKIP] {cf_data['name']} - уже существует")
                    self.stats['custom_fields']['skipped'] += 1
                else:
                    create_data = {
                        'name': cf_data['name'],
                        'label': cf_data['label'],
                        'type': type_mapping.get(cf_data['type'], 'text'),
                        'description': cf_data.get('description', ''),
                        'object_types': ['dcim.device'],  # Применяется к устройствам
                        'required': False,
                        'filter_logic': cf_data.get('filter_logic', 'loose'),
                        'weight': 100
                    }

                    if not self.dry_run:
                        self.nb.extras.custom_fields.create(**create_data)
                        print(f"  [OK] {cf_data['name']} ({cf_data['type']}) - создан")
                    else:
                        print(f"  [DRY] {cf_data['name']} ({cf_data['type']}) - будет создан")
                    self.stats['custom_fields']['created'] += 1

            except Exception as e:
                print(f"  [ERR] {cf_data['name']}: {e}")
                self.stats['custom_fields']['errors'] += 1

    def create_platforms(self):
        """Создание Platforms"""
        print("\n[7/8] PLATFORMS")

        for platform_data in PLATFORMS:
            try:
                existing = self.nb.dcim.platforms.get(name=platform_data['name'])

                if existing:
                    print(f"  [SKIP] {platform_data['name']} - уже существует")
                    self.stats['platforms']['skipped'] += 1
                else:
                    # Получаем manufacturer
                    mfr_name = platform_data.pop('manufacturer')
                    manufacturer = self.manufacturers_cache.get(mfr_name)
                    if not manufacturer:
                        manufacturer = self.nb.dcim.manufacturers.get(name=mfr_name)

                    if manufacturer:
                        platform_data['manufacturer'] = manufacturer.id

                    if not self.dry_run:
                        self.nb.dcim.platforms.create(**platform_data)
                        print(f"  [OK] {platform_data['name']} - создан")
                    else:
                        print(f"  [DRY] {platform_data['name']} - будет создан")
                    self.stats['platforms']['created'] += 1

                    platform_data['manufacturer'] = mfr_name  # Восстанавливаем

            except Exception as e:
                print(f"  [ERR] {platform_data.get('name', 'Unknown')}: {e}")
                self.stats['platforms']['errors'] += 1

    def create_chassis_devices(self):
        """Создание Chassis устройств"""
        print("\n[8/8] CHASSIS DEVICES")

        for chassis_data in CHASSIS_DEVICES:
            try:
                existing = self.nb.dcim.devices.get(name=chassis_data['name'])

                if existing:
                    print(f"  [SKIP] {chassis_data['name']} - уже существует")
                    self.stats['chassis']['skipped'] += 1
                else:
                    # Получаем site из кэша или NetBox
                    site = self.sites_cache.get(chassis_data['site'])
                    if not site:
                        site = self.nb.dcim.sites.get(name=chassis_data['site'])
                    if not site:
                        print(f"  [ERR] {chassis_data['name']}: Site {chassis_data['site']} не найден")
                        self.stats['chassis']['errors'] += 1
                        continue

                    # Получаем device role из кэша или NetBox
                    role = self.roles_cache.get(chassis_data['role'])
                    if not role:
                        role = self.nb.dcim.device_roles.get(name=chassis_data['role'])
                    if not role:
                        print(f"  [ERR] {chassis_data['name']}: Role {chassis_data['role']} не найден")
                        self.stats['chassis']['errors'] += 1
                        continue

                    # Получаем device type по модели
                    device_type = None
                    # Сначала ищем в кэше по модели
                    for dt in self.device_types_cache.values():
                        if hasattr(dt, 'model') and dt.model == chassis_data['device_type_model']:
                            device_type = dt
                            break
                        elif hasattr(dt, 'name') and dt.name == chassis_data['device_type_model']:
                            device_type = dt
                            break
                    if not device_type:
                        device_type = self.nb.dcim.device_types.get(model=chassis_data['device_type_model'])
                    if not device_type:
                        print(f"  [ERR] {chassis_data['name']}: Device type {chassis_data['device_type_model']} не найден")
                        self.stats['chassis']['errors'] += 1
                        continue

                    # В dry-run режиме с фиктивными объектами просто показываем что будет создано
                    if self.dry_run and (isinstance(site, FakeObject) or isinstance(role, FakeObject) or isinstance(device_type, FakeObject)):
                        print(f"  [DRY] {chassis_data['name']} будет создан в {chassis_data['site']}")
                        self.stats['chassis']['created'] += 1
                        continue

                    create_data = {
                        'name': chassis_data['name'],
                        'device_type': device_type.id,
                        'role': role.id,
                        'site': site.id,
                        'status': chassis_data['status'],
                        'comments': chassis_data.get('comments', '')
                    }

                    if not self.dry_run:
                        self.nb.dcim.devices.create(**create_data)
                        print(f"  [OK] {chassis_data['name']} создан в {chassis_data['site']}")
                    else:
                        print(f"  [DRY] {chassis_data['name']} будет создан в {chassis_data['site']}")
                    self.stats['chassis']['created'] += 1

            except Exception as e:
                print(f"  [ERR] {chassis_data.get('name', 'Unknown')}: {e}")
                self.stats['chassis']['errors'] += 1

    def print_summary(self):
        """Вывод итоговой статистики"""
        print("\n" + "=" * 70)
        print("  ИТОГО")
        print("=" * 70)

        total_created = 0
        total_skipped = 0
        total_errors = 0

        categories = [
            ('Sites', 'sites'),
            ('Manufacturers', 'manufacturers'),
            ('Device Roles', 'device_roles'),
            ('Device Types', 'device_types'),
            ('Bay Templates', 'bay_templates'),
            ('Custom Fields', 'custom_fields'),
            ('Platforms', 'platforms'),
            ('Chassis', 'chassis')
        ]

        for name, key in categories:
            s = self.stats[key]
            print(f"  {name:15}: {s['created']} создано, {s['skipped']} пропущено, {s['errors']} ошибок")
            total_created += s['created']
            total_skipped += s['skipped']
            total_errors += s['errors']

        print("-" * 70)
        print(f"  {'ВСЕГО':15}: {total_created} создано, {total_skipped} пропущено, {total_errors} ошибок")
        print("=" * 70)

        if self.dry_run:
            print("\n  [DRY RUN] Изменения НЕ были сохранены!")
        else:
            print("\n  ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА")

        print("\nСледующие шаги:")
        print("1. Проверь созданные объекты в NetBox UI")
        print("2. Переместите chassis в правильные стойки вручную")
        print("3. Запусти синхронизацию: python main.py --dry-run --limit 10")

    def run(self):
        """Запуск полной инициализации"""
        print("=" * 70)
        if self.dry_run:
            print("  ИНИЦИАЛИЗАЦИЯ NETBOX ДЛЯ ZABBIX SYNC [DRY RUN]")
        else:
            print("  ИНИЦИАЛИЗАЦИЯ NETBOX ДЛЯ ZABBIX SYNC")
        print("=" * 70)

        if not self.connect():
            return False

        # Выполняем в правильном порядке
        self.create_sites()
        self.create_manufacturers()
        self.create_device_roles()
        self.create_device_types()
        self.create_device_bay_templates()
        self.create_custom_fields()
        self.create_platforms()
        self.create_chassis_devices()

        self.print_summary()

        return self.stats


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Инициализация NetBox для синхронизации с Zabbix'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Тестовый запуск без изменений'
    )

    args = parser.parse_args()

    initializer = NetBoxInitializer(dry_run=args.dry_run)
    initializer.run()


if __name__ == "__main__":
    main()
