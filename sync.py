#!/usr/bin/env python3
"""
Основная логика синхронизации Zabbix → NetBox
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pyzabbix import ZabbixAPI
import pynetbox
import redis
import requests
import json
import config
from utils import (
    DataValidator, DataNormalizer, HashCalculator,
    IPHelper, UHeightHelper, NotificationHelper, ChangeTracker
)

logger = logging.getLogger(__name__)

class ServerSync:
    """Основной класс синхронизации"""
    
    def __init__(self):
        self.zabbix = None
        self.netbox = None
        self.redis_client = None
        self.telegram_bot = None
        self.change_tracker = ChangeTracker()  # Для отслеживания детальных изменений
        self.stats = {
            'new_hosts': [],
            'changed_hosts': [],
            'error_hosts': [],
            'decommissioned_hosts': [],
            'deleted_hosts': [],      # НОВОЕ: Физически удаленные
            'recovered_hosts': [],    # НОВОЕ: Восстановленные из decommissioning
            'renamed_hosts': [],      # НОВОЕ: Переименованные устройства
            'new_models': [],
            'skipped_hosts': [],
            'rack_conflicts': [],     # НОВОЕ: Конфликты позиций в стойках
            'detailed_changes': {},   # Детальные изменения по хостам
            'error_details': {}       # Детали ошибок
        }
    
    def connect_services(self) -> bool:
        """Подключение ко всем сервисам"""
        success = True
        
        # Zabbix (критично)
        try:
            self.zabbix = ZabbixAPI(config.ZABBIX_URL, timeout=config.TIMEOUT)
            self.zabbix.session.verify = config.VERIFY_SSL
            self.zabbix.login(config.ZABBIX_USER, config.ZABBIX_PASSWORD)
            logger.info(f"✓ Zabbix API подключен (v{self.zabbix.api_version()})")
        except Exception as e:
            logger.error(f"✗ Ошибка подключения к Zabbix: {e}")
            return False
        
        # NetBox (критично)
        try:
            self.netbox = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)
            self.netbox.http_session.verify = config.VERIFY_SSL
            # Тестовый запрос
            self.netbox.dcim.sites.all()
            logger.info("✓ NetBox API подключен")
        except Exception as e:
            logger.error(f"✗ Ошибка подключения к NetBox: {e}")
            return False
        
        # Redis (опционально)
        if config.REDIS_ENABLED:
            try:
                self.redis_client = redis.Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    db=config.REDIS_DB,
                    password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None,
                    decode_responses=True  # Для удобства работы со строками
                )
                self.redis_client.ping()
                logger.info("✓ Redis подключен")
            except Exception as e:
                logger.warning(f"⚠ Redis недоступен: {e} (работаем без кэша)")
                self.redis_client = None
        
        # Telegram (опционально)
        if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN:
            try:
                self.telegram_bot = TelegramBot(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
                test_response = self.telegram_bot.test_connection()
                if test_response:
                    logger.info("✓ Telegram Bot подключен")
                else:
                    logger.warning("⚠ Telegram Bot настроен, но проверка не прошла")
                    self.telegram_bot = None
            except Exception as e:
                logger.warning(f"⚠ Telegram недоступен: {e}")
                self.telegram_bot = None
        
        return True
    
    def disconnect_services(self):
        """Отключение от сервисов"""
        if self.zabbix:
            try:
                self.zabbix.user.logout()
            except:
                pass
        
        if self.redis_client:
            try:
                self.redis_client.close()
            except:
                pass
    
    def send_telegram_notification(self, message: str):
        """Отправка уведомления в Telegram"""
        if not self.telegram_bot:
            return
        
        try:
            self.telegram_bot.send_message(message)
            logger.debug("Telegram уведомление отправлено")
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
    
    def get_vmware_hosts(self) -> List[Dict]:
        """Получение списка VMware хостов из Zabbix"""
        try:
            # Получаем все хосты с расширенным inventory
            hosts = self.zabbix.host.get(
                output=['hostid', 'host', 'name', 'status'],
                selectParentTemplates=['templateid', 'name'],
                selectInventory='extend',  # Получаем ВСЕ поля inventory
                selectInterfaces=['ip', 'type', 'main'],
                selectGroups=['groupid', 'name']
            )
            
            # Фильтрация
            filtered_hosts = []
            for host in hosts:
                templates = [t.get('name', '') for t in host.get('parentTemplates', [])]
                groups = [g.get('name', '') for g in host.get('groups', [])]
                
                # Проверка включенных шаблонов
                has_included = any(
                    incl in template 
                    for template in templates 
                    for incl in config.INCLUDED_TEMPLATES
                )
                
                # Проверка исключенных
                has_excluded = any(
                    excl in template 
                    for template in templates 
                    for excl in config.EXCLUDED_TEMPLATES
                )
                
                has_excluded_group = any(
                    excl in group 
                    for group in groups 
                    for excl in config.EXCLUDED_GROUPS
                )
                
                if has_included and not has_excluded and not has_excluded_group:
                    filtered_hosts.append(host)
            
            # Применяем лимит если задан
            if config.HOST_LIMIT:
                filtered_hosts = filtered_hosts[:config.HOST_LIMIT]
                logger.info(f"Применен лимит: {config.HOST_LIMIT} хостов")
            
            logger.info(f"Найдено {len(filtered_hosts)} хостов для синхронизации")
            return filtered_hosts
            
        except Exception as e:
            logger.error(f"Ошибка получения хостов из Zabbix: {e}")
            return []
    
    def check_changes(self, hosts: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Проверка изменений через Redis с детальным отслеживанием"""
        if not self.redis_client:
            # Без Redis все хосты считаются новыми
            logger.debug("Redis отключен, все хосты считаются новыми")
            return hosts, []
        
        new_hosts = []
        changed_hosts = []
        
        for host in hosts:
            host_id = host['hostid']
            host_name = host.get('name', 'Unknown')
            primary_ip = IPHelper.get_primary_ip(host)
            current_hash = HashCalculator.calculate_host_hash(host, primary_ip)
            
            redis_key = f"{config.REDIS_KEY_PREFIX}{host_id}"
            redis_data_key = f"{config.REDIS_KEY_PREFIX}data:{host_id}"
            
            try:
                old_hash = self.redis_client.get(redis_key)
                old_data = self.redis_client.get(redis_data_key)
                
                if old_hash is None:
                    logger.debug(f"Хост {host_name} новый (нет ключа в Redis)")
                    new_hosts.append(host)
                elif old_hash != current_hash:
                    logger.debug(f"Хост {host_name} изменился (хэш отличается)")
                    changed_hosts.append(host)
                    
                    # Отслеживаем что именно изменилось
                    if old_data:
                        try:
                            old_host_data = json.loads(old_data)
                            changes = self.change_tracker.compare_hosts(old_host_data, host)
                            if changes:
                                self.stats['detailed_changes'][host_name] = changes
                                logger.debug(f"Изменения для {host_name}: {changes}")
                        except json.JSONDecodeError:
                            logger.warning(f"Не удалось декодировать старые данные для {host_name}")
                
            except Exception as e:
                logger.warning(f"Ошибка работы с Redis для хоста {host_id}: {e}")
                changed_hosts.append(host)  # Считаем измененным при ошибке Redis
        
        logger.info(f"Найдено новых: {len(new_hosts)}, измененных: {len(changed_hosts)}")
        return new_hosts, changed_hosts
    
    def check_decommissioned_devices(self):
        """Проверка и пометка неактивных устройств как decommissioning + удаление (FIX #2)"""
        if not self.redis_client:
            return

        try:
            # Получаем все активные хосты из Zabbix
            active_host_ids = set()
            for host in self.get_vmware_hosts():
                active_host_ids.add(host['hostid'])

            # FIX: Фильтруем только устройства с ролью Server
            # Получаем ID ролей, которыми управляет этот проект
            role_ids = []
            if config.MANAGED_DEVICE_ROLES:
                for role_name in config.MANAGED_DEVICE_ROLES:
                    role = self.netbox.dcim.device_roles.get(name=role_name)
                    if role:
                        role_ids.append(role.id)
                logger.info(f"Проверка decommission для ролей: {config.MANAGED_DEVICE_ROLES}")

            # 1. Проверяем активные устройства для decommissioning
            netbox_devices = self.netbox.dcim.devices.filter(
                cf_zabbix_hostid__n=False,  # Не null
                status='active'
            )

            # Фильтруем по ролям - проверяем только серверы
            if role_ids:
                netbox_devices = [d for d in netbox_devices if d.role and d.role.id in role_ids]

            for device in netbox_devices:
                zabbix_hostid = device.custom_fields.get('zabbix_hostid')
                if zabbix_hostid and zabbix_hostid not in active_host_ids:
                    self._mark_as_decommissioning(device, zabbix_hostid)

            # 2. FIX #2: Проверяем устройства в decommissioning для физического удаления
            if config.ENABLE_PHYSICAL_DELETION:
                decommissioning_devices = self.netbox.dcim.devices.filter(status='decommissioning')

                # Фильтруем по ролям - удаляем только серверы
                if role_ids:
                    decommissioning_devices = [d for d in decommissioning_devices if d.role and d.role.id in role_ids]

                for device in decommissioning_devices:
                    self._check_for_deletion(device)

            # Обновляем last_seen для активных хостов
            for host_id in active_host_ids:
                last_seen_key = f"{config.REDIS_KEY_PREFIX}lastseen:{host_id}"
                self.redis_client.set(last_seen_key, datetime.now().date().isoformat())

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
                    # Добавляем дату decommissioning
                    device.custom_fields['decommissioned_date'] = datetime.now().date().isoformat()
                    device.save()
                    logger.info(f"Устройство {device.name} помечено как decommissioning (неактивно {days_inactive} дней)")
                else:
                    logger.info(f"[DRY RUN] Устройство {device.name} будет помечено как decommissioning")

                self.stats['decommissioned_hosts'].append(device.name)
        else:
            # Первый раз не видим - записываем дату
            self.redis_client.set(last_seen_key, datetime.now().date().isoformat())

    def _check_for_deletion(self, device: Any):
        """Проверить и удалить устройство если прошло достаточно времени (FIX #2)"""
        decommissioned_date_str = device.custom_fields.get('decommissioned_date')

        if not decommissioned_date_str:
            # Если даты нет, устанавливаем сейчас
            if not config.DRY_RUN:
                device.custom_fields['decommissioned_date'] = datetime.now().date().isoformat()
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
                    logger.warning(f"[DRY RUN] Устройство {device.name} будет УДАЛЕНО физически")
            else:
                logger.debug(f"Устройство {device.name} в decommissioning {days_in_decommissioning}/{config.DELETE_AFTER_DECOMMISSION_DAYS} дней")

        except Exception as e:
            logger.error(f"Ошибка при проверке удаления {device.name}: {e}")
    
    def ensure_manufacturer(self, vendor_name: str) -> Optional[Any]:
        """Создание или получение производителя"""
        vendor_name = DataNormalizer.normalize_vendor(vendor_name)
        
        if not vendor_name or vendor_name == 'Unknown':
            # Для Unknown создаем Generic производителя
            vendor_name = 'Generic'
        
        try:
            manufacturer = self.netbox.dcim.manufacturers.get(name=vendor_name)
            
            if not manufacturer:
                slug = DataNormalizer.create_slug(vendor_name)
                
                if not config.DRY_RUN:
                    manufacturer = self.netbox.dcim.manufacturers.create(
                        name=vendor_name,
                        slug=slug
                    )
                    logger.info(f"  Создан производитель: {vendor_name}")
                else:
                    logger.info(f"  [DRY RUN] Будет создан производитель: {vendor_name}")
                    # В dry-run режиме возвращаем фиктивный объект
                    class FakeManufacturer:
                        def __init__(self):
                            self.name = vendor_name
                            self.id = 999
                    return FakeManufacturer()
            
            return manufacturer
        except Exception as e:
            logger.error(f"  Ошибка работы с производителем {vendor_name}: {e}")
            return None
    
    def ensure_device_type(self, model: str, manufacturer: Any, host_data: Dict = None) -> Optional[Any]:
        """Создание или получение типа устройства с улучшенной обработкой Unknown"""
        original_model = model
        model = DataNormalizer.normalize_model(model)
        
        if not manufacturer:
            return None
        
        # Обработка Unknown/To be filled моделей
        if model == 'Unknown' or 'to be filled' in model.lower():
            # Пытаемся определить модель из других полей
            if host_data:
                inventory = host_data.get('inventory', {})
                hardware = inventory.get('hardware', '')
                
                # Пытаемся извлечь модель из hardware
                if 'PowerEdge' in hardware:
                    match = re.search(r'PowerEdge\s+(\w+)', hardware)
                    if match:
                        model = f"PowerEdge {match.group(1)}"
                        logger.info(f"  Определена модель из hardware: {model}")
                elif 'ProLiant' in hardware:
                    match = re.search(r'ProLiant\s+(\w+)', hardware)
                    if match:
                        model = f"ProLiant {match.group(1)}"
                        logger.info(f"  Определена модель из hardware: {model}")
            
            # Если все еще Unknown, используем Generic модель
            if model == 'Unknown':
                model = 'Generic Server'
                logger.info(f"  Используется Generic модель для '{original_model}'")
        
        try:
            device_type = self.netbox.dcim.device_types.get(
                model=model,
                manufacturer_id=manufacturer.id
            )
            
            if not device_type:
                slug = DataNormalizer.create_slug(f"{manufacturer.name}-{model}")
                
                # Определяем U-height
                u_height = UHeightHelper.get_u_height(manufacturer.name, model)
                if u_height is None:
                    # Для Generic/Unknown используем стандартный 2U
                    if 'Generic' in model or 'Unknown' in model:
                        u_height = 2
                        logger.info(f"  Используется стандартный 2U для {model}")
                    else:
                        self.stats['new_models'].append(f"{manufacturer.name} {model}")
                        u_height = 2  # По умолчанию
                
                if not config.DRY_RUN:
                    device_type = self.netbox.dcim.device_types.create(
                        manufacturer=manufacturer.id,
                        model=model,
                        slug=slug,
                        u_height=u_height,
                        comments=f"Auto-created. Original model: {original_model}"
                    )
                    logger.info(f"  Создан тип устройства: {model} ({u_height}U)")
                else:
                    logger.info(f"  [DRY RUN] Будет создан тип: {model} ({u_height}U)")
                    # В dry-run режиме возвращаем фиктивный объект
                    class FakeDeviceType:
                        def __init__(self):
                            self.model = model
                            self.id = 999
                    return FakeDeviceType()
            
            return device_type
        except Exception as e:
            logger.error(f"  Ошибка работы с типом устройства {model}: {e}")
            return None
    
    def get_or_create_device(self, host_data: Dict) -> Tuple[Any, bool]:
        """
        Получение или создание устройства с учетом hostid (FIX #1)
        Returns: (device, is_new)
        """
        host_id = host_data['hostid']
        host_name = host_data.get('name', 'Unknown')

        # 1. Сначала ищем по zabbix_hostid (первичный ключ)
        try:
            devices = list(self.netbox.dcim.devices.filter(cf_zabbix_hostid=host_id))

            if devices:
                device = devices[0]
                # Проверяем переименование
                if device.name != host_name:
                    logger.warning(f"  🔄 Обнаружено переименование: {device.name} → {host_name}")
                    self.stats['renamed_hosts'].append(f"{device.name} → {host_name}")
                    if not config.DRY_RUN:
                        device.name = host_name
                        device.save()
                        logger.info(f"  ✓ Устройство переименовано в {host_name}")
                    else:
                        logger.info(f"  [DRY RUN] Устройство будет переименовано в {host_name}")
                return device, False

            # 2. Fallback на поиск по имени (для старых устройств без hostid)
            device = self.netbox.dcim.devices.get(name=host_name)
            if device:
                # Добавляем hostid если его нет
                if not device.custom_fields.get('zabbix_hostid'):
                    logger.info(f"  Добавляем zabbix_hostid для существующего устройства {host_name}")
                    if not config.DRY_RUN:
                        device.custom_fields['zabbix_hostid'] = host_id
                        device.save()
                return device, False

        except Exception as e:
            logger.warning(f"  Ошибка при поиске устройства: {e}")

        # 3. Устройство не найдено - будет создано новое
        return None, True

    def check_rack_position_conflict(self, rack: Any, position: int, device_id: int = None) -> Optional[Any]:
        """
        Проверка конфликта позиции в стойке (FIX #5)
        Returns: Устройство которое уже занимает позицию или None
        """
        if not rack or not position:
            return None

        try:
            # Ищем устройства на этой позиции
            conflicts = list(self.netbox.dcim.devices.filter(
                rack_id=rack.id,
                position=position
            ))

            for conflict in conflicts:
                # Пропускаем текущее устройство (при обновлении)
                if device_id and conflict.id == device_id:
                    continue
                return conflict

            return None

        except Exception as e:
            logger.error(f"  Ошибка проверки конфликта стойки: {e}")
            return None

    def ensure_rack(self, rack_name: str, site: Any, location: Any = None) -> Optional[Any]:
        """Создание или получение стойки с проверкой/обновлением локации"""
        if not rack_name or not site:
            return None
        
        try:
            # Ищем стойку по name и site (как раньше)
            rack = self.netbox.dcim.racks.get(
                name=rack_name,
                site_id=site.id
            )
            
            if rack:
                # Проверяем локацию, если задана
                if location:
                    current_location_id = rack.location.id if rack.location else None
                    if current_location_id != location.id:
                        if not config.DRY_RUN:
                            rack.location = location.id
                            rack.save()
                            logger.info(f"  Обновлена локация стойки {rack_name} на {location.name}")
                        else:
                            logger.info(f"  [DRY RUN] Будет обновлена локация стойки {rack_name}")
                        # Если разная локация, можно добавить предупреждение
                        if current_location_id:
                            logger.warning(f"  Внимание: Изменена локация стойки {rack_name} с {rack.location.name} на {location.name}")
            
            if not rack:
                rack_data = {
                    'name': rack_name,
                    'site': site.id,
                    'status': 'active',
                    'u_height': 42,  # Стандартная высота
                    'type': '4-post-cabinet',
                    'width': 19,  # 19 inch
                    'comments': 'Auto-created from Zabbix'
                }
                
                # Location добавляем только если она существует
                if location:
                    rack_data['location'] = location.id
                
                if not config.DRY_RUN:
                    rack = self.netbox.dcim.racks.create(**rack_data)
                    logger.info(f"  Создана стойка: {rack_name} в site {site.name}")
                else:
                    logger.info(f"  [DRY RUN] Будет создана стойка: {rack_name}")
                    return None  # В dry-run не возвращаем объект
        
            return rack
        except Exception as e:
            logger.error(f"  Ошибка работы со стойкой {rack_name}: {e}")
            return None
    
    def sync_device(self, host_data: Dict) -> bool:
        """Синхронизация одного устройства в NetBox с расширенной поддержкой"""
        host_id = host_data['hostid']
        host_name = host_data.get('name', 'Unknown')
        primary_ip = IPHelper.get_primary_ip(host_data)  # Получаем IP заранее для хэша
        
        # Валидация
        is_valid, error = DataValidator.validate_host_data(host_data)
        if not is_valid:
            logger.warning(f"Хост {host_name} пропущен: {error}")
            self.stats['skipped_hosts'].append(host_name)
            return False
        
        logger.info(f"\nОбработка: {host_name} (ID: {host_id})")
        
        device = None
        interface = None
        ip_address = None
        
        try:
            inventory = host_data.get('inventory', {})
            
            # Для отладки - смотрим что есть в inventory
            if config.LOG_LEVEL == 'DEBUG':
                logger.debug(f"  Inventory для {host_name}: {json.dumps(inventory, indent=2)}")
            
            # IP и Site
            if not primary_ip:
                logger.warning(f"  Нет валидного IP для {host_name}")
            
            # FIX #6: Site fallback
            site_name = IPHelper.get_site_from_ip(primary_ip)
            site = self.netbox.dcim.sites.get(name=site_name)
            if not site:
                logger.warning(f"  Site {site_name} не найден, использую {config.DEFAULT_SITE}")
                site = self.netbox.dcim.sites.get(name=config.DEFAULT_SITE)

                if not site:
                    logger.error(f"  DEFAULT_SITE {config.DEFAULT_SITE} также не найден в NetBox!")
                    self.stats['error_hosts'].append(host_name)
                    self.stats['error_details'][host_name] = f"Site {site_name} и DEFAULT_SITE не найдены"
                    return False
            
            # Локация
            location_name = config.LOCATION_MAPPING.get(site_name)
            location = self.ensure_location(location_name, site) if location_name else None
            
            # Производитель и модель
            manufacturer = self.ensure_manufacturer(inventory.get('vendor'))
            if not manufacturer:
                logger.error(f"  Не удалось определить производителя для {host_name}")
                self.stats['error_hosts'].append(host_name)
                self.stats['error_details'][host_name] = "Не удалось определить производителя"
                return False
            
            device_type = self.ensure_device_type(
                inventory.get('model'), 
                manufacturer, 
                host_data
            )
            if not device_type:
                logger.error(f"  Не удалось определить тип устройства для {host_name}")
                self.stats['error_hosts'].append(host_name)
                self.stats['error_details'][host_name] = "Не удалось определить тип устройства"
                return False
            
            # Rack (стойка) - ИЗМЕНЕНО
            rack = None
            rack_position = None
            rack_name = inventory.get('software_app_b', '')  # Используем software_app_b
            rack_unit = inventory.get('location_lon', '')

            if rack_name:
                rack = self.ensure_rack(rack_name, site, location)
                if rack and rack_unit:
                    try:
                        rack_position = int(rack_unit)

                        # FIX #5: Проверка конфликтов позиций в стойках
                        if config.CHECK_RACK_CONFLICTS:
                            conflict_device = self.check_rack_position_conflict(
                                rack, rack_position, None  # device_id будет проверен позже
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
                    except ValueError:
                        logger.warning(f"  Некорректная позиция U: {rack_unit}")
            
            # Платформа
            platform = self.ensure_platform()
            
            # Роль устройства
            device_role = self.netbox.dcim.device_roles.get(name='Server')
            if not device_role:
                if not config.DRY_RUN:
                    device_role = self.netbox.dcim.device_roles.create(
                        name='Server',
                        slug='server',
                        color='0000ff'
                    )
                    logger.info("  Создана роль: Server")
            
            # Custom fields
            memory_gb = DataNormalizer.normalize_memory(inventory.get('software_app_a'))
            custom_fields = {
                'cpu_model': inventory.get('hardware', ''),
                'memory_size': str(memory_gb) if memory_gb else '',
                'os_name': inventory.get('os', ''),
                'os_version': inventory.get('os_short', ''),
                'vsphere_cluster': inventory.get('alias', ''),
                'rack_location': inventory.get('location', ''),
                'zabbix_hostid': host_id,
                'serial_number': inventory.get('serialno_a', ''),
                'asset_tag': inventory.get('asset_tag', ''),
                'rack_name': rack_name,
                'rack_unit': rack_unit,
                'last_sync': datetime.now().date().isoformat()
            }
            custom_fields = {k: v for k, v in custom_fields.items() if v}

            # FIX #1: Проверяем существование устройства по hostid
            device, is_new = self.get_or_create_device(host_data)

            # FIX #13: Status recovery - всегда обновляем статус
            new_status = 'active' if host_data.get('status') == '0' else 'offline'

            # Данные устройства
            device_data = {
                'name': host_name,
                'device_type': device_type.id,
                'role': device_role.id if device_role else None,
                'site': site.id,
                'status': new_status,
                'location': location.id if location else None,
                'serial': inventory.get('serialno_a', ''),
                'asset_tag': inventory.get('asset_tag', ''),
                'custom_fields': custom_fields
            }
            
            if rack:
                device_data['rack'] = rack.id
                if rack_position:
                    device_data['position'] = rack_position
                    device_data['face'] = 'front'
            
            device_data = {k: v for k, v in device_data.items() if v not in [None, '']}
            
            if device and not is_new:
                # ОБНОВЛЕНИЕ существующего устройства
                changes_made = []

                # FIX #13: Status recovery из decommissioning
                if device.status == 'decommissioning' and new_status == 'active':
                    logger.warning(f"  🔄 Устройство {host_name} восстановлено из decommissioning → active")
                    # Очищаем дату decommissioning
                    if device.custom_fields.get('decommissioned_date'):
                        device.custom_fields['decommissioned_date'] = None
                    self.stats['recovered_hosts'].append(host_name)

                # FIX #4: Применяем фильтр защищенных полей
                protected_fields = config.PROTECTED_FIELDS
                protected_custom_fields = config.PROTECTED_CUSTOM_FIELDS

                # Проверяем изменения в полях включая rack
                for field, new_value in device_data.items():
                    # Пропускаем protected fields
                    if field in protected_fields:
                        logger.debug(f"  Поле {field} защищено от перезаписи")
                        continue

                    if field == 'custom_fields':
                        for cf_name, cf_value in new_value.items():
                            # Пропускаем protected custom fields
                            if cf_name in protected_custom_fields:
                                logger.debug(f"  Custom field {cf_name} защищено от перезаписи")
                                continue

                            old_cf_value = device.custom_fields.get(cf_name)
                            if str(old_cf_value) != str(cf_value):
                                changes_made.append(f"{cf_name}: {old_cf_value} → {cf_value}")
                    else:
                        old_value = getattr(device, field, None)
                        
                        # Специальная обработка для rack и position
                        if field == 'rack':
                            old_rack_id = device.rack.id if device.rack else None
                            if old_rack_id != new_value:
                                old_rack_name = device.rack.name if device.rack else 'не указана'
                                changes_made.append(f"rack: {old_rack_name} → {rack_name}")
                        elif field == 'position':
                            old_position = device.position
                            if old_position != new_value:
                                changes_made.append(f"position: U{old_position} → U{new_value}")
                        else:
                            if hasattr(old_value, 'id'):
                                old_value = old_value.id
                            if str(old_value) != str(new_value):
                                changes_made.append(f"{field}: {old_value} → {new_value}")
                
                # ВАЖНО: Также проверяем если стойка была удалена в Zabbix
                if not rack_name and device.rack:
                    changes_made.append(f"rack: {device.rack.name} → удалена")
                    device_data['rack'] = None
                    device_data['position'] = None
                    device_data['face'] = None
                
                if changes_made:
                    if not config.DRY_RUN:
                        device.update(device_data)
                        logger.info(f"  ✓ Устройство обновлено")
                        logger.info(f"    Изменения: {', '.join(changes_made[:3])}")
                        self.stats['changed_hosts'].append(host_name)
                        self.stats['detailed_changes'][host_name] = changes_made
                        
                        # Обновляем Redis после успешного обновления
                        if self.redis_client:
                            current_hash = HashCalculator.calculate_host_hash(host_data, primary_ip)
                            redis_key = f"{config.REDIS_KEY_PREFIX}{host_id}"
                            redis_data_key = f"{config.REDIS_KEY_PREFIX}data:{host_id}"
                            self.redis_client.setex(redis_key, config.REDIS_TTL, current_hash)
                            self.redis_client.setex(redis_data_key, config.REDIS_TTL, json.dumps(host_data))
                            logger.debug(f"Redis обновлен для {host_name}")
                    else:
                        logger.info(f"  [DRY RUN] Устройство будет обновлено")
                        logger.info(f"    Изменения: {', '.join(changes_made[:3])}")
                else:
                    logger.info(f"  ℹ Устройство не изменилось")
            else:
                # Создание нового устройства
                if not config.DRY_RUN:
                    device = self.netbox.dcim.devices.create(**device_data)
                    logger.info(f"  ✓ Устройство создано")
                    if rack:
                        logger.info(f"    Размещено в стойке {rack_name}, позиция U{rack_position}")
                    self.stats['new_hosts'].append(host_name)
                    
                    # Обновляем Redis после успешного создания
                    if self.redis_client:
                        current_hash = HashCalculator.calculate_host_hash(host_data, primary_ip)
                        redis_key = f"{config.REDIS_KEY_PREFIX}{host_id}"
                        redis_data_key = f"{config.REDIS_KEY_PREFIX}data:{host_id}"
                        self.redis_client.setex(redis_key, config.REDIS_TTL, current_hash)
                        self.redis_client.setex(redis_data_key, config.REDIS_TTL, json.dumps(host_data))
                        logger.debug(f"Redis обновлен для {host_name}")
                else:
                    logger.info(f"  [DRY RUN] Устройство будет создано")
                    if rack_name:
                        logger.info(f"    Будет размещено в стойке {rack_name}, позиция U{rack_unit}")
            
            # IP адрес
            if primary_ip and device:
                interface, ip_address = self.sync_ip_address(primary_ip, device)
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"  ✗ Ошибка синхронизации {host_name}: {error_msg}")
            self.stats['error_hosts'].append(host_name)
            self.stats['error_details'][host_name] = error_msg
            
            # Rollback при ошибке
            if not config.DRY_RUN:
                self.rollback_device_creation(device, interface, ip_address)
            
            return False
        
    def ensure_location(self, location_name: str, site: Any) -> Optional[Any]:
        """Создание или получение локации"""
        if not location_name:
            return None
        
        try:
            location = self.netbox.dcim.locations.get(name=location_name)
            
            if not location:
                slug = DataNormalizer.create_slug(location_name)
                
                if not config.DRY_RUN:
                    location = self.netbox.dcim.locations.create(
                        name=location_name,
                        slug=slug,
                        site=site.id
                    )
                    logger.info(f"  Создана локация: {location_name}")
                else:
                    logger.info(f"  [DRY RUN] Будет создана локация: {location_name}")
                    return None
            
            return location
        except Exception as e:
            logger.error(f"  Ошибка работы с локацией {location_name}: {e}")
            return None
    
    def ensure_platform(self) -> Optional[Any]:
        """Создание или получение платформы VMware ESXi"""
        try:
            platform = self.netbox.dcim.platforms.get(name='VMware ESXi')
            
            if not platform:
                manufacturer = self.ensure_manufacturer('VMware')
                
                if manufacturer and not config.DRY_RUN:
                    platform = self.netbox.dcim.platforms.create(
                        name='VMware ESXi',
                        slug='vmware-esxi',
                        manufacturer=manufacturer.id
                    )
                    logger.info(f"  Создана платформа: VMware ESXi")
                else:
                    logger.info(f"  [DRY RUN] Будет создана платформа: VMware ESXi")
                    return None
            
            return platform
        except Exception as e:
            logger.error(f"  Ошибка работы с платформой: {e}")
            return None
    
    def sync_ip_address(self, ip: str, device: Any) -> Tuple[Optional[Any], Optional[Any]]:
        """Синхронизация IP адреса и интерфейса с очисткой orphaned IP (FIX #3)"""
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

            # FIX #3: Проверяем старый primary IP
            ip_with_mask = f"{ip}/32"
            old_primary_ip = device.primary_ip4

            if old_primary_ip and old_primary_ip.address != ip_with_mask:
                logger.info(f"    🔄 Обнаружено изменение IP: {old_primary_ip.address} → {ip_with_mask}")
                if not config.DRY_RUN:
                    # Освобождаем старый IP
                    try:
                        old_ip_obj = self.netbox.ipam.ip_addresses.get(id=old_primary_ip.id)
                        if old_ip_obj:
                            # Действие зависит от конфигурации
                            if config.ORPHANED_IP_ACTION == 'delete':
                                old_ip_obj.delete()
                                logger.info(f"    Старый IP {old_primary_ip.address} удален")
                            elif config.ORPHANED_IP_ACTION == 'deprecated':
                                old_ip_obj.assigned_object_type = None
                                old_ip_obj.assigned_object_id = None
                                old_ip_obj.status = 'deprecated'
                                old_ip_obj.description = f"Deprecated: was used by {device.name}"
                                old_ip_obj.save()
                                logger.info(f"    Старый IP {old_primary_ip.address} помечен deprecated")
                            else:  # keep
                                logger.info(f"    Старый IP {old_primary_ip.address} оставлен как есть")
                    except Exception as e:
                        logger.warning(f"    Ошибка при освобождении старого IP: {e}")

            # Работаем с новым IP
            ip_address = self.netbox.ipam.ip_addresses.get(address=ip_with_mask)
            
            if ip_address:
                if not ip_address.assigned_object or ip_address.assigned_object_id != interface.id:
                    if not config.DRY_RUN:
                        ip_address.assigned_object_type = 'dcim.interface'
                        ip_address.assigned_object_id = interface.id
                        # Восстанавливаем status если был deprecated
                        if ip_address.status == 'deprecated':
                            ip_address.status = 'active'
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
    
    def rollback_device_creation(self, device=None, interface=None, ip_address=None):
        """Откат при ошибке создания устройства"""
        if config.DRY_RUN:
            return
        
        rollback_log = []
        
        # Удаляем в обратном порядке создания
        if ip_address:
            try:
                ip_address.delete()
                rollback_log.append(f"IP {ip_address.address}")
            except Exception as e:
                logger.debug(f"Rollback IP failed: {e}")
        
        if interface:
            try:
                interface.delete()
                rollback_log.append(f"Interface {interface.name}")
            except Exception as e:
                logger.debug(f"Rollback interface failed: {e}")
        
        if device:
            try:
                # Проверяем что устройство действительно новое
                existing = self.netbox.dcim.devices.filter(name=device.name)
                if len(list(existing)) == 1:  # Только наше устройство
                    device.delete()
                    rollback_log.append(f"Device {device.name}")
            except Exception as e:
                logger.debug(f"Rollback device failed: {e}")
        
        if rollback_log:
            logger.info(f"  Rollback выполнен: {', '.join(rollback_log)}")
    
    def run_sync(self) -> dict:
        """Запуск процесса синхронизации"""
        logger.info("=" * 60)
        logger.info("Запуск синхронизации Zabbix → NetBox")
        if config.DRY_RUN:
            logger.info("MODE: DRY RUN (изменения не будут сохранены)")
        logger.info("=" * 60)
        
        # Получаем хосты
        hosts = self.get_vmware_hosts()
        if not hosts:
            logger.warning("Нет хостов для синхронизации")
            return self.stats
        
        # Проверяем изменения
        new_hosts, changed_hosts = self.check_changes(hosts)
        
        logger.info(f"\n📊 Статистика изменений:")
        logger.info(f"  • Новых: {len(new_hosts)}")
        logger.info(f"  • Измененных: {len(changed_hosts)}")
        logger.info(f"  • Всего: {len(new_hosts) + len(changed_hosts)}")
        
        # Обрабатываем пакетами
        all_hosts = new_hosts + changed_hosts
        total = len(all_hosts)
        
        for i in range(0, total, config.BATCH_SIZE):
            batch = all_hosts[i:i + config.BATCH_SIZE]
            logger.info(f"\nОбработка пакета {i//config.BATCH_SIZE + 1} ({len(batch)} хостов)")
            
            for host in batch:
                self.sync_device(host)
        
        # Проверяем decommissioned устройства
        logger.info("\nПроверка неактивных устройств...")
        self.check_decommissioned_devices()
        
        # Результаты
        success_count = len(self.stats['new_hosts']) + len(self.stats['changed_hosts'])
        error_count = len(self.stats['error_hosts'])
        
        logger.info("\n" + "=" * 60)
        logger.info("📈 Результаты синхронизации:")
        logger.info(f"  ✓ Успешно: {success_count}")
        logger.info(f"  ✗ Ошибок: {error_count}")
        logger.info(f"  ⏭ Пропущено: {len(self.stats['skipped_hosts'])}")

        # Новые категории
        if self.stats['renamed_hosts']:
            logger.info(f"  🔄 Переименовано: {len(self.stats['renamed_hosts'])}")
            for rename in self.stats['renamed_hosts'][:3]:
                logger.info(f"      • {rename}")
            if len(self.stats['renamed_hosts']) > 3:
                logger.info(f"      ... и еще {len(self.stats['renamed_hosts']) - 3}")

        if self.stats['recovered_hosts']:
            logger.info(f"  ↩️ Восстановлено из decommissioning: {len(self.stats['recovered_hosts'])}")

        logger.info(f"  🗑 Decommissioned: {len(self.stats['decommissioned_hosts'])}")

        if self.stats['deleted_hosts']:
            logger.warning(f"  ❌ Физически удалено: {len(self.stats['deleted_hosts'])}")
            for deleted in self.stats['deleted_hosts'][:3]:
                logger.warning(f"      • {deleted}")

        if self.stats['rack_conflicts']:
            logger.warning(f"\n⚠️ Конфликты позиций в стойках: {len(self.stats['rack_conflicts'])}")
            for conflict in self.stats['rack_conflicts'][:3]:
                logger.warning(f"  • {conflict['device']}: U{conflict['position']} в {conflict['rack']} занята {conflict['conflict_with']}")

        if self.stats['new_models']:
            logger.warning(f"\n⚠️ Новые модели без U-height:")
            for model in self.stats['new_models']:
                logger.warning(f"  • {model}")

        logger.info("=" * 60)
        
        return self.stats

class TelegramBot:
    """Класс для работы с Telegram Bot API"""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def test_connection(self) -> bool:
        """Проверка подключения к боту"""
        try:
            response = requests.get(f"{self.base_url}/getMe", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def send_message(self, text: str, disable_notification: bool = None) -> bool:
        """Отправка сообщения в Telegram"""
        try:
            # Ограничение длины сообщения (Telegram limit: 4096)
            if len(text) > 4000:
                text = text[:3997] + "..."
            
            params = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': config.TELEGRAM_PARSE_MODE,
                'disable_notification': disable_notification or config.TELEGRAM_DISABLE_NOTIFICATION
            }
            
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=params,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.text}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
            return False
