#!/usr/bin/env python3
"""
Основная логика синхронизации Zabbix → NetBox
"""
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pyzabbix import ZabbixAPI
import pynetbox
import redis
import requests
import config
from utils import (
    DataValidator, DataNormalizer, HashCalculator,
    IPHelper, UHeightHelper, NotificationHelper
)

logger = logging.getLogger(__name__)


class ServerSync:
    """Основной класс синхронизации"""
    
    def __init__(self):
        self.zabbix = None
        self.netbox = None
        self.redis_client = None
        self.telegram_bot = None  # Изменено
        self.stats = {
            'new_hosts': [],
            'changed_hosts': [],
            'error_hosts': [],
            'new_models': [],
            'skipped_hosts': []
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
                    password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None
                )
                self.redis_client.ping()
                logger.info("✓ Redis подключен")
            except Exception as e:
                logger.warning(f"⚠ Redis недоступен: {e} (работаем без кэша)")
                self.redis_client = None
        
        # Telegram (опционально)
        if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN:
            try:
                # Тестовое сообщение для проверки
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
            # Получаем все хосты
            hosts = self.zabbix.host.get(
                output=['hostid', 'host', 'name', 'status'],
                selectParentTemplates=['templateid', 'name'],
                selectInventory=[
                    'vendor', 'model', 'os', 'os_short',
                    'hardware', 'alias', 'software_app_a', 'location'
                ],
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
        """Проверка изменений через Redis"""
        if not self.redis_client:
            # Без Redis все хосты считаются новыми
            return hosts, []
        
        new_hosts = []
        changed_hosts = []
        
        for host in hosts:
            host_id = host['hostid']
            primary_ip = IPHelper.get_primary_ip(host)
            current_hash = HashCalculator.calculate_host_hash(host, primary_ip)
            
            redis_key = f"{config.REDIS_KEY_PREFIX}{host_id}"
            
            try:
                old_hash = self.redis_client.get(redis_key)
                
                if old_hash is None:
                    new_hosts.append(host)
                elif old_hash.decode('utf-8') != current_hash:
                    changed_hosts.append(host)
                
                # Обновляем хэш с TTL
                self.redis_client.setex(redis_key, config.REDIS_TTL, current_hash)
                
            except Exception as e:
                logger.warning(f"Ошибка работы с Redis для хоста {host_id}: {e}")
                # При ошибке считаем хост измененным
                changed_hosts.append(host)
        
        return new_hosts, changed_hosts
    
    def ensure_manufacturer(self, vendor_name: str) -> Optional[Any]:
        """Создание или получение производителя"""
        vendor_name = DataNormalizer.normalize_vendor(vendor_name)
        
        if not vendor_name or vendor_name == 'Unknown':
            return None
        
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
                    return None
            
            return manufacturer
        except Exception as e:
            logger.error(f"  Ошибка работы с производителем {vendor_name}: {e}")
            return None
    
    def ensure_device_type(self, model: str, manufacturer: Any) -> Optional[Any]:
        """Создание или получение типа устройства"""
        model = DataNormalizer.normalize_model(model)
        
        if not model or model == 'Unknown' or not manufacturer:
            return None
        
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
                    self.stats['new_models'].append(f"{manufacturer.name} {model}")
                    u_height = 0  # NetBox требует значение
                
                if not config.DRY_RUN:
                    device_type = self.netbox.dcim.device_types.create(
                        manufacturer=manufacturer.id,
                        model=model,
                        slug=slug,
                        u_height=u_height
                    )
                    logger.info(f"  Создан тип устройства: {model} ({u_height}U)")
                else:
                    logger.info(f"  [DRY RUN] Будет создан тип: {model} ({u_height}U)")
                    return None
            
            return device_type
        except Exception as e:
            logger.error(f"  Ошибка работы с типом устройства {model}: {e}")
            return None
    
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
        """Синхронизация IP адреса и интерфейса"""
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
            
            # Работаем с IP (без маски, как вы просили)
            ip_address = self.netbox.ipam.ip_addresses.get(address=f"{ip}/32")
            
            if ip_address:
                if not ip_address.assigned_object or ip_address.assigned_object_id != interface.id:
                    if not config.DRY_RUN:
                        ip_address.assigned_object_type = 'dcim.interface'
                        ip_address.assigned_object_id = interface.id
                        ip_address.save()
                        logger.info(f"    IP {ip} привязан к интерфейсу")
            else:
                if not config.DRY_RUN:
                    ip_address = self.netbox.ipam.ip_addresses.create(
                        address=ip,
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
    
    def sync_device(self, host_data: Dict) -> bool:
        """Синхронизация одного устройства в NetBox"""
        host_id = host_data['hostid']
        host_name = host_data.get('name', 'Unknown')
        
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
            
            # IP и Site
            primary_ip = IPHelper.get_primary_ip(host_data)
            site_name = IPHelper.get_site_from_ip(primary_ip)
            
            site = self.netbox.dcim.sites.get(name=site_name)
            if not site:
                logger.error(f"  Site {site_name} не найден в NetBox")
                self.stats['error_hosts'].append(host_name)
                return False
            
            # Локация
            location_name = config.LOCATION_MAPPING.get(site_name)
            location = self.ensure_location(location_name, site) if location_name else None
            
            # Производитель и модель
            manufacturer = self.ensure_manufacturer(inventory.get('vendor'))
            device_type = self.ensure_device_type(inventory.get('model'), manufacturer)
            
            if not device_type:
                logger.error(f"  Не удалось определить тип устройства")
                self.stats['error_hosts'].append(host_name)
                return False
            
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
                'vsphere_cluster': inventory.get('alias', ''),  # Используем vsphere_cluster
                'rack_location': inventory.get('location', ''),
                'zabbix_hostid': host_id,
                'last_sync': datetime.now().isoformat()
            }
            
            # Убираем пустые значения
            custom_fields = {k: v for k, v in custom_fields.items() if v}
            
            # Проверяем существование устройства
            device = self.netbox.dcim.devices.get(name=host_name)
            
            # Данные устройства
            device_data = {
                'name': host_name,
                'device_type': device_type.id,
                'role': device_role.id,
                'site': site.id,
                'status': 'active' if host_data.get('status') == '0' else 'offline',
                'platform': platform.id if platform else None,
                'location': location.id if location else None,
                'custom_fields': custom_fields
            }
            
            # Убираем None
            device_data = {k: v for k, v in device_data.items() if v is not None}
            
            if device:
                # Обновление
                if not config.DRY_RUN:
                    device.update(device_data)
                    logger.info(f"  ✓ Устройство обновлено")
                    self.stats['changed_hosts'].append(host_name)
                else:
                    logger.info(f"  [DRY RUN] Устройство будет обновлено")
            else:
                # Создание
                if not config.DRY_RUN:
                    device = self.netbox.dcim.devices.create(**device_data)
                    logger.info(f"  ✓ Устройство создано")
                    self.stats['new_hosts'].append(host_name)
                else:
                    logger.info(f"  [DRY RUN] Устройство будет создано")
                    return True
            
            # IP адрес
            if primary_ip and device:
                interface, ip_address = self.sync_ip_address(primary_ip, device)
            
            return True
            
        except Exception as e:
            logger.error(f"  ✗ Ошибка синхронизации {host_name}: {e}")
            self.stats['error_hosts'].append(host_name)
            
            # Rollback при ошибке
            if not config.DRY_RUN:
                self.rollback_device_creation(device, interface, ip_address)
            
            return False
    
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
        
        # Результаты
        success_count = len(self.stats['new_hosts']) + len(self.stats['changed_hosts'])
        error_count = len(self.stats['error_hosts'])
        
        logger.info("\n" + "=" * 60)
        logger.info("📈 Результаты синхронизации:")
        logger.info(f"  ✓ Успешно: {success_count}")
        logger.info(f"  ✗ Ошибок: {error_count}")
        logger.info(f"  ⏭ Пропущено: {len(self.stats['skipped_hosts'])}")
        
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
    
    def send_document(self, file_path: str, caption: str = None) -> bool:
        """Отправка файла в Telegram (например, лог файл)"""
        try:
            with open(file_path, 'rb') as file:
                params = {
                    'chat_id': self.chat_id,
                    'caption': caption
                }
                files = {
                    'document': file
                }
                
                response = requests.post(
                    f"{self.base_url}/sendDocument",
                    data=params,
                    files=files,
                    timeout=30
                )
                
                return response.status_code == 200
                
        except Exception as e:
            logger.error(f"Ошибка отправки файла в Telegram: {e}")
            return False