# Руководство по исправлению логических дыр

## 🔴 КРИТИЧЕСКОЕ: Исправление #1 - Device Lookup by zabbix_hostid

### Проблема
Переименование устройства в Zabbix создает дубликат в NetBox.

### Текущий код (sync.py:546)
```python
device = self.netbox.dcim.devices.get(name=host_name)
```

### Исправленный код
```python
def get_or_create_device(self, host_data: Dict) -> Tuple[Any, bool]:
    """
    Получение или создание устройства с учетом hostid
    Returns: (device, is_new)
    """
    host_id = host_data['hostid']
    host_name = host_data.get('name', 'Unknown')

    # 1. Сначала ищем по zabbix_hostid (первичный ключ)
    devices = self.netbox.dcim.devices.filter(cf_zabbix_hostid=host_id)

    if devices:
        device = devices[0]
        # Проверяем переименование
        if device.name != host_name:
            logger.warning(f"Обнаружено переименование: {device.name} → {host_name}")
            if not config.DRY_RUN:
                device.name = host_name
                device.save()
                logger.info(f"  ✓ Устройство переименовано в {host_name}")
        return device, False

    # 2. Fallback на поиск по имени (для старых устройств без hostid)
    device = self.netbox.dcim.devices.get(name=host_name)
    if device:
        # Добавляем hostid если его нет
        if not device.custom_fields.get('zabbix_hostid'):
            logger.info(f"Добавляем zabbix_hostid для существующего устройства {host_name}")
            if not config.DRY_RUN:
                device.custom_fields['zabbix_hostid'] = host_id
                device.save()
        return device, False

    # 3. Устройство не найдено - будет создано новое
    return None, True
```

### Изменения в sync_device()
```python
def sync_device(self, host_data: Dict) -> bool:
    # ... существующий код ...

    # ЗАМЕНИТЬ строку 546
    # device = self.netbox.dcim.devices.get(name=host_name)

    # НА:
    device, is_new = self.get_or_create_device(host_data)

    # ... остальной код ...

    if device and not is_new:
        # Обновление существующего устройства
        # ... код обновления ...
    elif not device:
        # Создание нового устройства
        # ... код создания ...
```

---

## 🔴 КРИТИЧЕСКОЕ: Исправление #2 - Physical Device Deletion

### Добавить в config.py
```python
# Через сколько дней в статусе decommissioning удалять физически
DELETE_AFTER_DECOMMISSION_DAYS = int(os.getenv('DELETE_AFTER_DECOMMISSION_DAYS', '90'))

# Включить физическое удаление
ENABLE_PHYSICAL_DELETION = os.getenv('ENABLE_PHYSICAL_DELETION', 'false').lower() == 'true'
```

### Добавить в .env
```bash
# Удаление устройств
DELETE_AFTER_DECOMMISSION_DAYS=90  # Удалять после 90 дней в decommissioning
ENABLE_PHYSICAL_DELETION=false      # Пока выключено для безопасности
```

### Исправленный метод check_decommissioned_devices()
```python
def check_decommissioned_devices(self):
    """Проверка и пометка неактивных устройств как decommissioning + удаление"""
    if not self.redis_client:
        return

    try:
        # Получаем все активные хосты из Zabbix
        active_host_ids = set()
        for host in self.get_vmware_hosts():
            active_host_ids.add(host['hostid'])

        # 1. Проверяем активные устройства для decommissioning
        netbox_devices = self.netbox.dcim.devices.filter(
            cf_zabbix_hostid__n=False,
            status='active'
        )

        for device in netbox_devices:
            zabbix_hostid = device.custom_fields.get('zabbix_hostid')
            if zabbix_hostid and zabbix_hostid not in active_host_ids:
                self._mark_as_decommissioning(device, zabbix_hostid)

        # 2. НОВОЕ: Проверяем устройства в decommissioning для удаления
        if config.ENABLE_PHYSICAL_DELETION:
            decommissioning_devices = self.netbox.dcim.devices.filter(
                status='decommissioning'
            )

            for device in decommissioning_devices:
                self._check_for_deletion(device)

        # Обновляем last_seen для активных хостов
        for host_id in active_host_ids:
            last_seen_key = f"{config.REDIS_KEY_PREFIX}lastseen:{host_id}"
            self.redis_client.set(last_seen_key, datetime.now().isoformat())

    except Exception as e:
        logger.error(f"Ошибка при проверке decommissioned устройств: {e}")

def _mark_as_decommissioning(self, device: Any, zabbix_hostid: str):
    """Пометить устройство как decommissioning"""
    last_seen_key = f"{config.REDIS_KEY_PREFIX}lastseen:{zabbix_hostid}"
    last_seen = self.redis_client.get(last_seen_key)

    if last_seen:
        last_seen_date = datetime.fromisoformat(last_seen)
        days_inactive = (datetime.now() - last_seen_date).days

        if days_inactive > config.DECOMMISSION_AFTER_DAYS:
            if not config.DRY_RUN:
                device.status = 'decommissioning'
                # Добавляем дату decommissioning в custom field
                device.custom_fields['decommissioned_date'] = datetime.now().isoformat()
                device.save()
                logger.info(f"Устройство {device.name} помечено как decommissioning (неактивно {days_inactive} дней)")
            else:
                logger.info(f"[DRY RUN] Устройство {device.name} будет помечено как decommissioning")

            self.stats['decommissioned_hosts'].append(device.name)
    else:
        # Первый раз не видим - записываем дату
        self.redis_client.set(last_seen_key, datetime.now().isoformat())

def _check_for_deletion(self, device: Any):
    """Проверить и удалить устройство если прошло достаточно времени"""
    decommissioned_date_str = device.custom_fields.get('decommissioned_date')

    if not decommissioned_date_str:
        # Если даты нет, устанавливаем сейчас
        if not config.DRY_RUN:
            device.custom_fields['decommissioned_date'] = datetime.now().isoformat()
            device.save()
        return

    try:
        decommissioned_date = datetime.fromisoformat(decommissioned_date_str)
        days_in_decommissioning = (datetime.now() - decommissioned_date).days

        if days_in_decommissioning > config.DELETE_AFTER_DECOMMISSION_DAYS:
            if not config.DRY_RUN:
                device_name = device.name
                device.delete()
                logger.warning(f"🗑️ Устройство {device_name} УДАЛЕНО физически (decommissioning {days_in_decommissioning} дней)")
                self.stats['deleted_hosts'].append(device_name)
            else:
                logger.warning(f"[DRY RUN] Устройство {device.name} будет УДАЛЕНО")
        else:
            logger.debug(f"Устройство {device.name} в decommissioning {days_in_decommissioning}/{config.DELETE_AFTER_DECOMMISSION_DAYS} дней")

    except Exception as e:
        logger.error(f"Ошибка при проверке удаления {device.name}: {e}")
```

### Добавить в stats (sync.py:31)
```python
self.stats = {
    'new_hosts': [],
    'changed_hosts': [],
    'error_hosts': [],
    'decommissioned_hosts': [],
    'deleted_hosts': [],  # НОВОЕ
    'new_models': [],
    'skipped_hosts': [],
    'detailed_changes': {},
    'error_details': {}
}
```

### Добавить custom field в NetBox
```
Имя: decommissioned_date
Тип: Date
Описание: Дата когда устройство было помечено как decommissioning
```

---

## 🔴 КРИТИЧЕСКОЕ: Исправление #3 - Orphaned IP Cleanup

### Исправленный метод sync_ip_address()
```python
def sync_ip_address(self, ip: str, device: Any) -> Tuple[Optional[Any], Optional[Any]]:
    """Синхронизация IP адреса и интерфейса с очисткой старых IP"""
    if not ip or not DataValidator.validate_ip(ip):
        return None, None

    interface = None
    ip_address = None

    try:
        # Создаем/получаем интерфейс
        interface_name = "mgmt0"
        interface = self.netbox.dcim.interfaces.get(
            device_id=device.id,
            name=interface_name
        )

        if not interface:
            if not config.DRY_RUN:
                interface = self.netbox.dcim.interfaces.create(
                    device=device.id,
                    name=interface_name,
                    type="1000base-t",
                    enabled=True,
                    description="Management interface"
                )
                logger.info(f"    Создан интерфейс {interface_name}")
            else:
                logger.info(f"    [DRY RUN] Будет создан интерфейс {interface_name}")
                return None, None

        # НОВОЕ: Проверяем старый primary IP
        ip_with_mask = f"{ip}/32"
        old_primary_ip = device.primary_ip4

        if old_primary_ip and old_primary_ip.address != ip_with_mask:
            logger.info(f"    Обнаружено изменение IP: {old_primary_ip.address} → {ip_with_mask}")
            if not config.DRY_RUN:
                # Освобождаем старый IP
                old_ip_obj = self.netbox.ipam.ip_addresses.get(address=old_primary_ip.address)
                if old_ip_obj:
                    old_ip_obj.assigned_object_type = None
                    old_ip_obj.assigned_object_id = None
                    old_ip_obj.status = 'deprecated'  # Помечаем как deprecated вместо удаления
                    old_ip_obj.description = f"Deprecated: was used by {device.name}"
                    old_ip_obj.save()
                    logger.info(f"    Старый IP {old_primary_ip.address} освобожден и помечен deprecated")

        # Работаем с новым IP
        ip_address = self.netbox.ipam.ip_addresses.get(address=ip_with_mask)

        if ip_address:
            # Проверяем что IP назначен правильному интерфейсу
            if not ip_address.assigned_object or ip_address.assigned_object_id != interface.id:
                if not config.DRY_RUN:
                    ip_address.assigned_object_type = 'dcim.interface'
                    ip_address.assigned_object_id = interface.id
                    ip_address.status = 'active'  # Восстанавливаем active если был deprecated
                    ip_address.save()
                    logger.info(f"    IP {ip} привязан к интерфейсу")
        else:
            if not config.DRY_RUN:
                ip_address = self.netbox.ipam.ip_addresses.create(
                    address=ip_with_mask,
                    status='active',
                    assigned_object_type='dcim.interface',
                    assigned_object_id=interface.id,
                    description=f"Primary IP for {device.name}"
                )
                logger.info(f"    IP {ip} создан")
            else:
                logger.info(f"    [DRY RUN] Будет создан IP {ip}")

        # Устанавливаем как primary
        if ip_address and (not device.primary_ip4 or device.primary_ip4.id != ip_address.id):
            if not config.DRY_RUN:
                device.primary_ip4 = ip_address.id
                device.save()
                logger.info(f"    IP {ip} установлен как primary")

        return interface, ip_address

    except Exception as e:
        logger.error(f"    Ошибка при работе с IP {ip}: {e}")
        raise
```

### Добавить утилиту для очистки orphaned IP
```python
def cleanup_orphaned_ips(self):
    """Очистка IP адресов без assigned_object"""
    try:
        # Находим все IP без assigned_object и не в prefixes
        orphaned_ips = self.netbox.ipam.ip_addresses.filter(
            assigned_object_id__isnull=True,
            status='active'  # Только active, deprecated оставляем для истории
        )

        count = 0
        for ip in orphaned_ips:
            logger.info(f"Найден orphaned IP: {ip.address}")
            if not config.DRY_RUN:
                # Помечаем как deprecated вместо удаления
                ip.status = 'deprecated'
                ip.description = f"Orphaned IP cleaned up at {datetime.now().isoformat()}"
                ip.save()
                count += 1

        logger.info(f"Очищено orphaned IP адресов: {count}")
        return count

    except Exception as e:
        logger.error(f"Ошибка очистки orphaned IP: {e}")
        return 0
```

---

## 🟡 ВЫСОКИЙ: Исправление #4 - Protected Fields

### Добавить в config.py
```python
# Поля которые НЕ должны перезаписываться из Zabbix
PROTECTED_FIELDS = os.getenv('PROTECTED_FIELDS', '').split(',')
# Пример: PROTECTED_FIELDS=asset_tag,comments,description

# Custom fields которые НЕ перезаписываются
PROTECTED_CUSTOM_FIELDS = os.getenv('PROTECTED_CUSTOM_FIELDS', '').split(',')
# Пример: PROTECTED_CUSTOM_FIELDS=manual_notes,warranty_date
```

### Изменить логику обновления в sync_device()
```python
def sync_device(self, host_data: Dict) -> bool:
    # ... существующий код ...

    if device:
        # Обновление существующего устройства
        changes_made = []

        # Фильтруем protected fields
        protected_fields = set(config.PROTECTED_FIELDS)
        protected_custom_fields = set(config.PROTECTED_CUSTOM_FIELDS)

        for field, new_value in device_data.items():
            # Пропускаем protected fields
            if field in protected_fields:
                logger.debug(f"Поле {field} защищено от перезаписи")
                continue

            if field == 'custom_fields':
                for cf_name, cf_value in new_value.items():
                    # Пропускаем protected custom fields
                    if cf_name in protected_custom_fields:
                        logger.debug(f"Custom field {cf_name} защищено от перезаписи")
                        continue

                    old_cf_value = device.custom_fields.get(cf_name)
                    if str(old_cf_value) != str(cf_value):
                        changes_made.append(f"{cf_name}: {old_cf_value} → {cf_value}")
            else:
                old_value = getattr(device, field, None)
                # ... остальная логика сравнения ...
```

---

## 🟡 ВЫСОКИЙ: Исправление #5 - Rack Position Conflicts

### Добавить метод проверки конфликтов
```python
def check_rack_position_conflict(self, rack: Any, position: int, device_id: int = None) -> Optional[Any]:
    """
    Проверка конфликта позиции в стойке
    Returns: Устройство которое уже занимает позицию или None
    """
    if not rack or not position:
        return None

    try:
        # Ищем устройства на этой позиции
        conflicts = self.netbox.dcim.devices.filter(
            rack_id=rack.id,
            position=position
        )

        for conflict in conflicts:
            # Пропускаем текущее устройство (при обновлении)
            if device_id and conflict.id == device_id:
                continue

            return conflict

        return None

    except Exception as e:
        logger.error(f"Ошибка проверки конфликта стойки: {e}")
        return None
```

### Использовать в sync_device()
```python
def sync_device(self, host_data: Dict) -> bool:
    # ... существующий код ...

    if rack and rack_position:
        # Проверяем конфликт
        conflict_device = self.check_rack_position_conflict(
            rack,
            rack_position,
            device.id if device else None
        )

        if conflict_device:
            logger.error(f"  ⚠️ КОНФЛИКТ: Позиция U{rack_position} в {rack.name} занята устройством {conflict_device.name}")
            self.stats['rack_conflicts'].append({
                'device': host_name,
                'rack': rack.name,
                'position': rack_position,
                'conflict_with': conflict_device.name
            })
            # НЕ назначаем позицию при конфликте
            rack = None
            rack_position = None
        else:
            logger.debug(f"  Позиция U{rack_position} в {rack.name} свободна")

    # ... продолжение кода ...
```

### Добавить в stats
```python
self.stats = {
    # ... существующие ...
    'rack_conflicts': [],  # НОВОЕ
}
```

---

## 🟡 ВЫСОКИЙ: Исправление #6 - Site Fallback

### Простое исправление в sync_device()
```python
def sync_device(self, host_data: Dict) -> bool:
    # ... существующий код ...

    # ЗАМЕНИТЬ (sync.py:469-474):
    # site = self.netbox.dcim.sites.get(name=site_name)
    # if not site:
    #     logger.error(f"  Site {site_name} не найден в NetBox")
    #     return False

    # НА:
    site = self.netbox.dcim.sites.get(name=site_name)
    if not site:
        logger.warning(f"  Site {site_name} не найден, использую {config.DEFAULT_SITE}")
        site = self.netbox.dcim.sites.get(name=config.DEFAULT_SITE)

        if not site:
            logger.error(f"  DEFAULT_SITE {config.DEFAULT_SITE} также не найден в NetBox!")
            self.stats['error_hosts'].append(host_name)
            self.stats['error_details'][host_name] = f"Site {site_name} и DEFAULT_SITE не найдены"
            return False

    # ... продолжение кода ...
```

---

## 🟢 СРЕДНИЙ: Исправление #13 - Status Recovery

### Изменить логику обновления статуса
```python
def sync_device(self, host_data: Dict) -> bool:
    # ... существующий код ...

    # Всегда обновляем статус, даже если был decommissioning
    new_status = 'active' if host_data.get('status') == '0' else 'offline'

    device_data = {
        # ... остальные поля ...
        'status': new_status,
    }

    if device:
        # Специальная обработка для recovery из decommissioning
        if device.status == 'decommissioning' and new_status == 'active':
            logger.warning(f"  🔄 Устройство {host_name} восстановлено из decommissioning → active")
            # Очищаем дату decommissioning
            if 'decommissioned_date' in device.custom_fields:
                device.custom_fields['decommissioned_date'] = None
            self.stats['recovered_hosts'].append(host_name)

        # Обновляем устройство
        # ... остальная логика обновления ...
```

### Добавить в stats
```python
self.stats = {
    # ... существующие ...
    'recovered_hosts': [],  # НОВОЕ: Устройства восстановленные из decommissioning
}
```

---

## 📝 ДОПОЛНИТЕЛЬНЫЕ УТИЛИТЫ

### Утилита для проверки consistency
```python
def check_consistency(self):
    """Проверка консистентности данных NetBox"""
    issues = {
        'orphaned_ips': [],
        'duplicate_serials': [],
        'missing_custom_fields': [],
        'rack_conflicts': []
    }

    logger.info("Проверка консистентности данных...")

    # 1. Orphaned IP
    orphaned = self.netbox.ipam.ip_addresses.filter(
        assigned_object_id__isnull=True,
        status='active'
    )
    issues['orphaned_ips'] = [ip.address for ip in orphaned]

    # 2. Дубликаты серийных номеров
    devices = self.netbox.dcim.devices.all()
    serial_map = {}
    for device in devices:
        if device.serial:
            if device.serial in serial_map:
                issues['duplicate_serials'].append({
                    'serial': device.serial,
                    'devices': [serial_map[device.serial], device.name]
                })
            else:
                serial_map[device.serial] = device.name

    # 3. Отсутствующие custom fields
    for device in devices:
        for cf in config.CUSTOM_FIELDS:
            if cf not in device.custom_fields:
                issues['missing_custom_fields'].append({
                    'device': device.name,
                    'field': cf
                })
                break  # Достаточно одного отсутствующего поля

    # 4. Конфликты позиций в стойках
    racks = self.netbox.dcim.racks.all()
    for rack in racks:
        position_map = {}
        devices_in_rack = self.netbox.dcim.devices.filter(rack_id=rack.id)
        for device in devices_in_rack:
            if device.position:
                if device.position in position_map:
                    issues['rack_conflicts'].append({
                        'rack': rack.name,
                        'position': device.position,
                        'devices': [position_map[device.position], device.name]
                    })
                else:
                    position_map[device.position] = device.name

    # Вывод результатов
    logger.info("\n=== Результаты проверки консистентности ===")
    logger.info(f"Orphaned IP: {len(issues['orphaned_ips'])}")
    logger.info(f"Дубликаты серийных номеров: {len(issues['duplicate_serials'])}")
    logger.info(f"Отсутствующие custom fields: {len(issues['missing_custom_fields'])}")
    logger.info(f"Конфликты стоек: {len(issues['rack_conflicts'])}")

    return issues
```

### CLI команда для проверки
```python
# В main.py добавить
@click.option('--check-consistency', is_flag=True, help='Проверить консистентность данных NetBox')
def main(dry_run, limit, no_redis, no_telegram, validate_only,
         check_decommissioned, cleanup_orphaned_ips, check_consistency, verbose):

    if check_consistency:
        issues = sync.check_consistency()
        # Вывести детали issues
        return
```

---

## 🎯 ПОРЯДОК ПРИМЕНЕНИЯ ИСПРАВЛЕНИЙ

1. **День 1:**
   - Исправление #6 (Site fallback) - 30 мин
   - Исправление #13 (Status recovery) - 1 час

2. **День 2-3:**
   - Исправление #1 (Device lookup) - 4 часа
   - Тестирование переименований

3. **День 4-5:**
   - Исправление #3 (Orphaned IP) - 4 часа
   - Утилита cleanup_orphaned_ips
   - Тестирование изменений IP

4. **День 6-7:**
   - Исправление #2 (Deletion) - 6 часов
   - Тестирование удалений (ОСТОРОЖНО!)

5. **День 8-9:**
   - Исправление #5 (Rack conflicts) - 4 часа
   - Исправление #4 (Protected fields) - 4 часа

6. **День 10:**
   - Утилита check_consistency
   - Финальное тестирование

---

## ⚠️ ВАЖНЫЕ ПРЕДУПРЕЖДЕНИЯ

1. **Тестируйте в DRY_RUN режиме!**
```bash
DRY_RUN=true python main.py
```

2. **Делайте бэкапы NetBox перед применением!**
```bash
pg_dump netbox > netbox_backup_$(date +%Y%m%d).sql
```

3. **Применяйте постепенно:**
   - Сначала исправления #6, #13 (безопасные)
   - Потом #1, #3 (влияют на данные)
   - В конце #2 (удаление!)

4. **Добавьте custom fields в NetBox:**
```python
# Через UI или API:
- decommissioned_date (Date)
- protected (Boolean) - для защиты от перезаписи
```

5. **Мониторьте логи:**
```bash
tail -f logs/sync.log | grep -E "КОНФЛИКТ|УДАЛЕНО|ПЕРЕИМЕНОВАН"
```
