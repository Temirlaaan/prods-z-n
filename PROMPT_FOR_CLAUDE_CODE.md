# Промпт для Claude Code: Инициализация NetBox для Zabbix Sync

## Задача

Создай Python скрипт `init_netbox.py` который полностью подготовит чистый NetBox для синхронизации с Zabbix. Скрипт должен создать все необходимые сущности и быть идемпотентным (безопасен для повторного запуска).

## Конфигурация подключения

```python
NETBOX_URL = "https://web-netbox.t-cloud.kz/"
NETBOX_TOKEN = "token"  # Заменить на реальный токен
VERIFY_SSL = False
```

## Что нужно создать

### 1. Sites (Дата-центры)

```python
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
```

### 2. Manufacturers (Производители)

```python
MANUFACTURERS = [
    {'name': 'Dell', 'slug': 'dell', 'description': 'Dell Technologies'},
    {'name': 'HPE', 'slug': 'hpe', 'description': 'Hewlett Packard Enterprise'},
    {'name': 'Huawei', 'slug': 'huawei', 'description': 'Huawei Technologies'},
    {'name': 'Lenovo', 'slug': 'lenovo', 'description': 'Lenovo Group'},
    {'name': 'Cisco', 'slug': 'cisco', 'description': 'Cisco Systems'},
    {'name': 'VMware', 'slug': 'vmware', 'description': 'VMware Inc'},
    {'name': 'Generic', 'slug': 'generic', 'description': 'Generic/Unknown manufacturer'}
]
```

### 3. Device Roles (Роли устройств)

```python
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
```

### 4. Device Types (Типы устройств)

```python
DEVICE_TYPES = [
    # === RACK SERVERS ===
    # Dell
    {'manufacturer': 'Dell', 'model': 'PowerEdge R640', 'slug': 'dell-poweredge-r640', 'u_height': 1, 'is_full_depth': True},
    
    # HPE
    {'manufacturer': 'HPE', 'model': 'ProLiant DL360 Gen10', 'slug': 'hpe-proliant-dl360-gen10', 'u_height': 1, 'is_full_depth': True},
    
    # Huawei (rack)
    {'manufacturer': 'Huawei', 'model': 'RH1288 V3', 'slug': 'huawei-rh1288-v3', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'RH2288H V3', 'slug': 'huawei-rh2288h-v3', 'u_height': 2, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'RH5885H V3', 'slug': 'huawei-rh5885h-v3', 'u_height': 4, 'is_full_depth': True},
    {'manufacturer': 'Huawei', 'model': 'To be filled by O.E.M.', 'slug': 'huawei-unknown', 'u_height': 2, 'is_full_depth': True},
    
    # Lenovo
    {'manufacturer': 'Lenovo', 'model': 'ThinkSystem SR645', 'slug': 'lenovo-thinksystem-sr645', 'u_height': 1, 'is_full_depth': True},
    {'manufacturer': 'Lenovo', 'model': 'ThinkAgile VX7531 Node', 'slug': 'lenovo-thinkagile-vx7531', 'u_height': 2, 'is_full_depth': True},
    
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
```

### 5. Device Bay Templates для Chassis

После создания device types, нужно создать device bay templates для chassis:

```python
# Для Cisco UCS 5108 - 8 слотов
CISCO_CHASSIS_BAYS = [
    {'name': f'Blade Bay {i}', 'description': f'Slot for blade server {i}'} 
    for i in range(1, 9)
]

# Для Huawei E9000 - 16 слотов  
HUAWEI_CHASSIS_BAYS = [
    {'name': f'Slot {i}', 'description': f'Slot for compute node {i}'} 
    for i in range(1, 17)
]
```

### 6. Custom Fields

```python
CUSTOM_FIELDS = [
    {'name': 'cpu_model', 'label': 'CPU Model', 'type': 'text', 'description': 'Модель процессора из Zabbix'},
    {'name': 'memory_size', 'label': 'Memory Size (GB)', 'type': 'text', 'description': 'Размер оперативной памяти'},
    {'name': 'os_name', 'label': 'OS Name', 'type': 'text', 'description': 'Операционная система'},
    {'name': 'os_version', 'label': 'OS Version', 'type': 'text', 'description': 'Версия ОС'},
    {'name': 'vsphere_cluster', 'label': 'vSphere Cluster', 'type': 'text', 'description': 'Кластер vSphere'},
    {'name': 'rack_location', 'label': 'Rack Location', 'type': 'text', 'description': 'Текстовое описание локации'},
    {'name': 'zabbix_hostid', 'label': 'Zabbix Host ID', 'type': 'text', 'description': 'ID хоста в Zabbix (ключ синхронизации)', 'filter_logic': 'loose'},
    {'name': 'last_sync', 'label': 'Last Sync', 'type': 'date', 'description': 'Дата последней синхронизации'},
    {'name': 'serial_number', 'label': 'Serial Number', 'type': 'text', 'description': 'Серийный номер из Zabbix'},
    {'name': 'asset_tag', 'label': 'Asset Tag', 'type': 'text', 'description': 'Инвентарный номер'},
    {'name': 'rack_name', 'label': 'Rack Name (Zabbix)', 'type': 'text', 'description': 'Имя стойки из Zabbix'},
    {'name': 'rack_unit', 'label': 'Rack Unit (Zabbix)', 'type': 'text', 'description': 'Позиция U из Zabbix'},
    {'name': 'decommissioned_date', 'label': 'Decommissioned Date', 'type': 'date', 'description': 'Дата decommissioning'}
]
```

### 7. Platforms

```python
PLATFORMS = [
    {'name': 'VMware ESXi', 'slug': 'vmware-esxi', 'manufacturer': 'VMware', 'description': 'VMware ESXi Hypervisor'}
]
```

### 8. Создание Chassis устройств в DEFAULT_SITE

После создания всех типов, создай по одному chassis каждого типа в DC Konaeva10:

```python
CHASSIS_DEVICES = [
    {
        'name': 'Cisco-UCS-Chassis-01',
        'device_type': 'UCS 5108 Blade Server Chassis',  # ищем по model
        'role': 'Chassis',
        'site': 'DC Konaeva10',
        'status': 'active',
        'comments': 'Auto-created chassis for Cisco blade servers. Move to correct rack manually.'
    },
    {
        'name': 'Huawei-E9000-Chassis-01', 
        'device_type': 'E9000 Converged Infrastructure Blade Chassis',
        'role': 'Chassis',
        'site': 'DC Konaeva10',
        'status': 'active',
        'comments': 'Auto-created chassis for Huawei blade servers. Move to correct rack manually.'
    }
]
```

## Требования к скрипту

1. **Идемпотентность** - безопасен для повторного запуска (проверяет существование перед созданием)
2. **Логирование** - выводит что создано, что пропущено, ошибки
3. **Порядок создания**:
   - Sites
   - Manufacturers
   - Device Roles
   - Device Types
   - Device Bay Templates (для chassis)
   - Custom Fields
   - Platforms
   - Chassis Devices
4. **Обработка ошибок** - продолжает работу при ошибке создания одного элемента
5. **Итоговый отчёт** - в конце показать статистику

## Зависимости

```python
import pynetbox
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

## Пример вывода

```
======================================================================
  🚀 ИНИЦИАЛИЗАЦИЯ NETBOX ДЛЯ ZABBIX SYNC
======================================================================

[1/8] SITES
  ✅ DC Kabanbay-Batyr28 - создан
  ✅ DC Almaty - создан
  ⏭  DC Konaeva10 - уже существует

[2/8] MANUFACTURERS
  ✅ Dell - создан
  ...

[3/8] DEVICE ROLES
  ...

[4/8] DEVICE TYPES
  ✅ Dell PowerEdge R640 (1U) - создан
  ✅ Cisco UCS 5108 Blade Server Chassis (6U, parent) - создан
  ✅ Cisco UCSB-B200-M4 (blade, child) - создан
  ...

[5/8] DEVICE BAY TEMPLATES
  ✅ Cisco UCS 5108: создано 8 bay slots
  ✅ Huawei E9000: создано 16 bay slots

[6/8] CUSTOM FIELDS  
  ...

[7/8] PLATFORMS
  ...

[8/8] CHASSIS DEVICES
  ✅ Cisco-UCS-Chassis-01 создан в DC Konaeva10
  ✅ Huawei-E9000-Chassis-01 создан в DC Konaeva10

======================================================================
  📊 ИТОГО
======================================================================
  Sites:           5 создано, 0 пропущено
  Manufacturers:   7 создано, 0 пропущено  
  Device Roles:    3 создано, 0 пропущено
  Device Types:   14 создано, 0 пропущено
  Bay Templates:  24 создано, 0 пропущено
  Custom Fields:  13 создано, 0 пропущено
  Platforms:       1 создано, 0 пропущено
  Chassis:         2 создано, 0 пропущено

======================================================================
  ✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА
======================================================================

Следующие шаги:
1. Проверь созданные объекты в NetBox UI
2. Переместите chassis в правильные стойки вручную
3. Запусти синхронизацию: python main.py --dry-run --limit 10
```

## Дополнительно: обновить config.py

После создания init_netbox.py, обнови U_HEIGHT_MAPPING в config.py проекта синхронизации:

```python
U_HEIGHT_MAPPING = {
    # Dell
    'Dell PowerEdge R640': 1,
    
    # HPE  
    'HPE ProLiant DL360 Gen10': 1,
    
    # Huawei (rack servers)
    'Huawei RH1288 V3': 1,
    'Huawei RH2288H V3': 2,
    'Huawei RH5885H V3': 4,
    'Huawei To be filled by O.E.M.': 2,
    
    # Huawei (blade - 0U, goes into chassis)
    'Huawei CH121 V3': 0,
    
    # Lenovo
    'Lenovo ThinkSystem SR645': 1,
    'Lenovo ThinkAgile VX7531 Node': 2,
    
    # Cisco (blade - 0U, goes into chassis)
    'Cisco Systems Inc UCSB-B200-M4': 0,
    'Cisco UCSB-B200-M4': 0,
    
    # VMware (virtual)
    'VMware Virtual Platform': 0,
    
    # Fallback
    'Dell Unknown': 2,
    'HPE Unknown': 2,
    'Huawei Unknown': 2,
    'Lenovo Unknown': 2,
    'Cisco Unknown': 2,
    'Unknown Unknown': 2,
    'Generic Server': 2,
}
```

---

Создай полный рабочий скрипт init_netbox.py по этим требованиям.
