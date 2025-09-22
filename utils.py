#!/usr/bin/env python3
"""
Утилиты и вспомогательные функции
"""
import re
import hashlib
import json
import logging
from typing import Dict, Optional, Any, Tuple, List
from datetime import datetime
import config

logger = logging.getLogger(__name__)

class DataValidator:
    """Валидация данных из Zabbix"""
    
    @staticmethod
    def validate_host_data(host_data: Dict) -> Tuple[bool, str]:
        """
        Проверка минимальных требований для синхронизации
        Returns: (valid: bool, error_message: str)
        """
        # Обязательные поля
        if not host_data.get('hostid'):
            return False, "Отсутствует hostid"
        
        if not host_data.get('name'):
            return False, "Отсутствует имя хоста"
        
        # Проверка наличия inventory
        inventory = host_data.get('inventory', {})
        if not inventory:
            return False, "Отсутствует inventory"
        
        # Предупреждения (не критично)
        warnings = []
        if not inventory.get('vendor'):
            warnings.append("vendor не указан")
        if not inventory.get('model'):
            warnings.append("model не указан")
        
        if warnings:
            logger.warning(f"Хост {host_data['name']}: {', '.join(warnings)}")
        
        return True, ""
    
    @staticmethod
    def validate_ip(ip: str) -> bool:
        """Проверка валидности IP адреса"""
        if not ip:
            return False
        
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, ip):
            return False
        
        octets = ip.split('.')
        for octet in octets:
            if int(octet) > 255:
                return False
        
        # Исключаем специальные адреса
        if ip in ['0.0.0.0', '127.0.0.1', '255.255.255.255']:
            return False
        
        return True


class DataNormalizer:
    """Нормализация данных для NetBox"""
    
    @staticmethod
    def normalize_memory(memory: str) -> Optional[int]:
        """
        Конвертация памяти в GB
        '1.99 TB' -> 2038
        '512 GB' -> 512
        Returns: int (GB) or None
        """
        if not memory or memory == 'N/A':
            return None
        
        try:
            match = re.match(r'(\d+\.?\d*)\s*(TB|GB|MB)', memory, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2).upper()
                
                if unit == 'TB':
                    return int(value * 1024)
                elif unit == 'GB':
                    return int(value)
                elif unit == 'MB':
                    return int(value / 1024)
            
            return None
        except Exception as e:
            logger.debug(f"Ошибка нормализации памяти '{memory}': {e}")
            return None
    
    @staticmethod
    def normalize_vendor(vendor: str) -> str:
        """Нормализация имени производителя"""
        if not vendor or vendor == 'N/A':
            return 'Unknown'
        
        # Маппинг известных вариантов
        vendor_mapping = {
            'Dell Inc.': 'Dell',
            'DELL': 'Dell',
            'Hewlett Packard Enterprise': 'HPE',
            'HP': 'HPE',
            'Huawei Technologies Co., Ltd.': 'Huawei',
            'LENOVO': 'Lenovo',
            'VMware, Inc.': 'VMware',
        }
        
        vendor = vendor.strip()
        return vendor_mapping.get(vendor, vendor)
    
    @staticmethod
    def normalize_model(model: str) -> str:
        """Нормализация модели устройства"""
        if not model or model == 'N/A':
            return 'Unknown'
        
        # Убираем лишние символы
        model = model.strip()
        model = re.sub(r'\s+', ' ', model)  # Множественные пробелы
        
        # Убираем "To be filled by O.E.M." и подобное
        if 'to be filled' in model.lower():
            return 'Unknown'
        
        return model
    
    @staticmethod
    def create_slug(name: str) -> str:
        """Создание slug для NetBox"""
        if not name:
            return 'unknown'
        
        # Приводим к нижнему регистру
        slug = name.lower()
        
        # Заменяем пробелы и специальные символы
        slug = re.sub(r'[^a-z0-9-]', '-', slug)
        
        # Убираем множественные дефисы
        slug = re.sub(r'-+', '-', slug)
        
        # Убираем дефисы в начале и конце
        slug = slug.strip('-')
        
        # Ограничиваем длину (NetBox limit)
        if len(slug) > 50:
            slug = slug[:50].rstrip('-')
        
        return slug or 'unknown'


class HashCalculator:
    """Расчет хэшей для отслеживания изменений"""
    
    @staticmethod
    def calculate_host_hash(host_data: Dict, primary_ip: str = None) -> str:
        """Создание хэша для отслеживания изменений"""
        inventory = host_data.get('inventory', {})
        
        # Собираем значимые поля, включая новые
        hash_data = {
            'name': host_data.get('name', ''),
            'vendor': DataNormalizer.normalize_vendor(inventory.get('vendor', '')),
            'model': DataNormalizer.normalize_model(inventory.get('model', '')),
            'os': inventory.get('os', ''),
            'os_version': inventory.get('os_short', ''),
            'cpu': inventory.get('hardware', ''),
            'memory': inventory.get('software_app_a', ''),
            'cluster': inventory.get('alias', ''),
            'location': inventory.get('location', ''),
            'ip': primary_ip or '',
            'status': host_data.get('status', ''),
            # Новые поля для отслеживания
            'serial': inventory.get('serialno_a', ''),
            'asset_tag': inventory.get('asset_tag', ''),
            'rack_name': inventory.get('location_lat', ''),
            'rack_unit': inventory.get('location_lon', '')
        }
        
        # Создаем стабильный хэш
        json_str = json.dumps(hash_data, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(json_str.encode()).hexdigest()


class IPHelper:
    """Работа с IP адресами"""
    
    @staticmethod
    def get_primary_ip(host_data: Dict) -> Optional[str]:
        """Получение основного IP адреса хоста"""
        interfaces = host_data.get('interfaces', [])
        
        # Сначала ищем main interface
        for iface in interfaces:
            if iface.get('main') == '1' and iface.get('ip'):
                ip = iface['ip']
                if DataValidator.validate_ip(ip):
                    return ip
        
        # Fallback на первый валидный IP
        for iface in interfaces:
            ip = iface.get('ip')
            if ip and DataValidator.validate_ip(ip):
                return ip
        
        return None
    
    @staticmethod
    def get_site_from_ip(ip: str) -> Optional[str]:
        """Определение Site по IP адресу"""
        if not DataValidator.validate_ip(ip):
            return config.DEFAULT_SITE
        
        octets = ip.split('.')
        subnet = f"{octets[0]}.{octets[1]}"
        
        site = config.SITE_MAPPING.get(subnet)
        if not site:
            logger.warning(f"Неизвестная подсеть {subnet} для IP {ip}, используем {config.DEFAULT_SITE}")
            return config.DEFAULT_SITE
        
        return site


class UHeightHelper:
    """Определение высоты устройства в U"""
    
    @staticmethod
    def get_u_height(vendor: str, model: str) -> Optional[int]:
        """Получение высоты устройства из маппинга"""
        vendor = DataNormalizer.normalize_vendor(vendor)
        model = DataNormalizer.normalize_model(model)
        
        # Составляем ключ
        key = f"{vendor} {model}"
        
        # Ищем в маппинге
        u_height = config.U_HEIGHT_MAPPING.get(key)
        
        if u_height is None:
            # Пробуем только по модели
            for map_key, height in config.U_HEIGHT_MAPPING.items():
                if model in map_key:
                    return height
            
            # Для Generic/Unknown моделей
            if 'Generic' in key or 'Unknown' in key:
                return 2  # Стандартный 2U
            
            logger.warning(f"U-height не найден для '{key}'")
            return None
        
        return u_height


class ChangeTracker:
    """Отслеживание изменений между синхронизациями"""
    
    @staticmethod
    def compare_hosts(old_host: Dict, new_host: Dict) -> List[str]:
        """Сравнение двух версий хоста и возврат списка изменений"""
        changes = []
        
        # Сравниваем основные поля
        if old_host.get('name') != new_host.get('name'):
            changes.append(f"Имя: {old_host.get('name')} → {new_host.get('name')}")
        
        if old_host.get('status') != new_host.get('status'):
            old_status = 'active' if old_host.get('status') == '0' else 'offline'
            new_status = 'active' if new_host.get('status') == '0' else 'offline'
            changes.append(f"Статус: {old_status} → {new_status}")
        
        # Сравниваем inventory
        old_inv = old_host.get('inventory', {})
        new_inv = new_host.get('inventory', {})
        
        # Проверяем ключевые поля inventory
        inventory_fields = {
            'vendor': 'Производитель',
            'model': 'Модель',
            'serialno_a': 'Серийный номер',
            'asset_tag': 'Инвентарный номер',
            'hardware': 'CPU',
            'software_app_a': 'Память',
            'os': 'ОС',
            'os_short': 'Версия ОС',
            'alias': 'Кластер',
            'location': 'Локация',
            'location_lat': 'Стойка',
            'location_lon': 'Позиция U'
        }
        
        for field, name in inventory_fields.items():
            old_val = old_inv.get(field, '')
            new_val = new_inv.get(field, '')
            if str(old_val) != str(new_val) and (old_val or new_val):
                # Специальная обработка для памяти
                if field == 'software_app_a':
                    old_gb = DataNormalizer.normalize_memory(old_val)
                    new_gb = DataNormalizer.normalize_memory(new_val)
                    if old_gb != new_gb:
                        changes.append(f"{name}: {old_gb}GB → {new_gb}GB")
                else:
                    changes.append(f"{name}: {old_val or 'пусто'} → {new_val or 'пусто'}")
        
        # Проверяем IP адреса
        old_ip = IPHelper.get_primary_ip(old_host)
        new_ip = IPHelper.get_primary_ip(new_host)
        if old_ip != new_ip:
            changes.append(f"IP: {old_ip} → {new_ip}")
        
        return changes


class NotificationHelper:
    """Форматирование уведомлений"""
    
    @staticmethod
    def format_sync_summary(new_hosts: list, changed_hosts: list, 
                           success_count: int, error_count: int,
                           new_models: list = None, 
                           decommissioned: list = None,
                           detailed_changes: dict = None,
                           error_details: dict = None,
                           format_type: str = 'HTML') -> str:
        """Форматирование детального отчета синхронизации для Telegram"""
        if format_type == 'HTML':
            lines = [
                "📊 <b>Синхронизация Zabbix → NetBox завершена</b>",
                "",
                f"✅ Успешно: <b>{success_count}</b>",
                f"❌ Ошибок: <b>{error_count}</b>",
                ""
            ]
            
            # Новые устройства
            if new_hosts:
                lines.append(f"🆕 <b>Новые устройства ({len(new_hosts)}):</b>")
                for host in new_hosts[:5]:  # Первые 5
                    lines.append(f"  • <code>{host}</code>")
                if len(new_hosts) > 5:
                    lines.append(f"  <i>... и еще {len(new_hosts) - 5}</i>")
                lines.append("")
            
            # Измененные устройства с деталями
            if changed_hosts:
                lines.append(f"🔄 <b>Измененные устройства ({len(changed_hosts)}):</b>")
                for host in changed_hosts[:3]:  # Первые 3 с деталями
                    lines.append(f"  • <code>{host}</code>")
                    if detailed_changes and host in detailed_changes:
                        changes = detailed_changes[host][:2]  # Первые 2 изменения
                        for change in changes:
                            lines.append(f"    → {change}")
                        if len(detailed_changes[host]) > 2:
                            lines.append(f"    → <i>... и еще {len(detailed_changes[host]) - 2} изменений</i>")
                if len(changed_hosts) > 3:
                    lines.append(f"  <i>... и еще {len(changed_hosts) - 3} устройств</i>")
                lines.append("")
            
            # Decommissioned устройства
            if decommissioned:
                lines.append(f"🗑 <b>Decommissioned ({len(decommissioned)}):</b>")
                for host in decommissioned[:3]:
                    lines.append(f"  • <code>{host}</code>")
                if len(decommissioned) > 3:
                    lines.append(f"  <i>... и еще {len(decommissioned) - 3}</i>")
                lines.append("")
            
            # Ошибки с деталями
            if error_details:
                lines.append(f"❌ <b>Детали ошибок:</b>")
                for host, error in list(error_details.items())[:3]:
                    lines.append(f"  • <code>{host}</code>")
                    # Обрезаем длинные ошибки
                    error_msg = error if len(error) < 100 else error[:97] + "..."
                    lines.append(f"    → {error_msg}")
                if len(error_details) > 3:
                    lines.append(f"  <i>... и еще {len(error_details) - 3} ошибок</i>")
                lines.append("")
            
            # Новые модели
            if new_models:
                lines.append(f"⚠️ <b>Новые модели без U-height ({len(new_models)}):</b>")
                for model in new_models[:3]:
                    lines.append(f"  • <code>{model}</code>")
                if len(new_models) > 3:
                    lines.append(f"  <i>... и еще {len(new_models) - 3}</i>")
                lines.append("<i>Добавьте в U_HEIGHT_MAPPING</i>")
            
            lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
        else:  # Markdown
            lines = [
                "📊 *Синхронизация Zabbix → NetBox завершена*",
                "",
                f"✅ Успешно: *{success_count}*",
                f"❌ Ошибок: *{error_count}*",
                ""
            ]
            
            if new_hosts:
                lines.append(f"🆕 *Новые устройства ({len(new_hosts)}):*")
                for host in new_hosts[:5]:
                    lines.append(f"  • `{host}`")
                if len(new_hosts) > 5:
                    lines.append(f"  _... и еще {len(new_hosts) - 5}_")
                lines.append("")
            
            if changed_hosts:
                lines.append(f"🔄 *Измененные устройства ({len(changed_hosts)}):*")
                for host in changed_hosts[:3]:
                    lines.append(f"  • `{host}`")
                    if detailed_changes and host in detailed_changes:
                        changes = detailed_changes[host][:2]
                        for change in changes:
                            lines.append(f"    → {change}")
                        if len(detailed_changes[host]) > 2:
                            lines.append(f"    → _... и еще {len(detailed_changes[host]) - 2} изменений_")
                if len(changed_hosts) > 3:
                    lines.append(f"  _... и еще {len(changed_hosts) - 3} устройств_")
                lines.append("")
            
            if decommissioned:
                lines.append(f"🗑 *Decommissioned ({len(decommissioned)}):*")
                for host in decommissioned[:3]:
                    lines.append(f"  • `{host}`")
                if len(decommissioned) > 3:
                    lines.append(f"  _... и еще {len(decommissioned) - 3}_")
                lines.append("")
            
            if error_details:
                lines.append(f"❌ *Детали ошибок:*")
                for host, error in list(error_details.items())[:3]:
                    lines.append(f"  • `{host}`")
                    error_msg = error if len(error) < 100 else error[:97] + "..."
                    lines.append(f"    → {error_msg}")
                if len(error_details) > 3:
                    lines.append(f"  _... и еще {len(error_details) - 3} ошибок_")
                lines.append("")
            
            if new_models:
                lines.append(f"⚠️ *Новые модели без U-height ({len(new_models)}):*")
                for model in new_models[:3]:
                    lines.append(f"  • `{model}`")
                if len(new_models) > 3:
                    lines.append(f"  _... и еще {len(new_models) - 3}_")
                lines.append("_Добавьте в U\\_HEIGHT\\_MAPPING_")
            
            lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_error_notification(error: str, context: dict = None, format_type: str = 'HTML') -> str:
        """Форматирование уведомления об ошибке для Telegram"""
        if format_type == 'HTML':
            lines = [
                "🚨 <b>Ошибка синхронизации</b>",
                "",
                f"❌ <code>{error}</code>",
            ]
            
            if context:
                lines.append("\n<b>Контекст:</b>")
                for key, value in context.items():
                    lines.append(f"  • {key}: <code>{value}</code>")
            
            lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        else:  # Markdown
            lines = [
                "🚨 *Ошибка синхронизации*",
                "",
                f"❌ `{error}`",
            ]
            
            if context:
                lines.append("\n*Контекст:*")
                for key, value in context.items():
                    lines.append(f"  • {key}: `{value}`")
            
            lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)