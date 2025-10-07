#!/usr/bin/env python3
"""
Диагностический скрипт для проверки и восстановления синхронизации
"""
import pynetbox
import redis
from pyzabbix import ZabbixAPI
import config
from datetime import datetime
import sys

def check_connections():
    """Проверка подключений к сервисам"""
    print("=" * 60)
    print("ПРОВЕРКА ПОДКЛЮЧЕНИЙ")
    print("=" * 60)
    
    # Zabbix
    try:
        zabbix = ZabbixAPI(config.ZABBIX_URL, timeout=config.TIMEOUT)
        zabbix.session.verify = config.VERIFY_SSL
        zabbix.login(config.ZABBIX_USER, config.ZABBIX_PASSWORD)
        version = zabbix.api_version()
        print(f"✅ Zabbix: Подключен (версия {version})")
        
        # Считаем хосты
        hosts = zabbix.host.get(countOutput=True)
        print(f"   Всего хостов в Zabbix: {hosts}")
        
        # VMware хосты
        vmware_hosts = zabbix.host.get(
            output=['hostid', 'name'],
            selectParentTemplates=['name'],
            filter={'status': '0'}
        )
        vmware_count = sum(1 for h in vmware_hosts 
                          if any('VMware' in t.get('name', '') 
                                for t in h.get('parentTemplates', [])))
        print(f"   VMware хостов: {vmware_count}")
        
    except Exception as e:
        print(f"❌ Zabbix: {e}")
        return False
    
    # NetBox
    try:
        netbox = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)
        netbox.http_session.verify = config.VERIFY_SSL
        
        # Считаем устройства
        all_devices = netbox.dcim.devices.count()
        print(f"✅ NetBox: Подключен")
        print(f"   Всего устройств: {all_devices}")
        
        # Активные устройства
        active = netbox.dcim.devices.count(status='active')
        print(f"   Активных: {active}")
        
        # Decommissioned
        decomm = netbox.dcim.devices.count(status='decommissioned')
        print(f"   Decommissioned: {decomm}")
        
        # С zabbix_hostid
        with_zabbix = netbox.dcim.devices.filter(cf_zabbix_hostid__n=False)
        zabbix_count = len(list(with_zabbix))
        print(f"   С Zabbix ID: {zabbix_count}")
        
    except Exception as e:
        print(f"❌ NetBox: {e}")
        return False
    
    # Redis
    try:
        r = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None
        )
        r.ping()
        
        # Считаем ключи
        keys = list(r.scan_iter(f"{config.REDIS_KEY_PREFIX}*"))
        print(f"✅ Redis: Подключен")
        print(f"   Кэшированных хостов: {len(keys)}")
        
    except Exception as e:
        print(f"⚠️  Redis: {e}")
    
    return True

def check_custom_fields():
    """Проверка Custom Fields в NetBox"""
    print("\n" + "=" * 60)
    print("ПРОВЕРКА CUSTOM FIELDS")
    print("=" * 60)
    
    try:
        netbox = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)
        netbox.http_session.verify = config.VERIFY_SSL
        
        required_fields = config.CUSTOM_FIELDS
        existing_fields = []
        
        for cf in netbox.extras.custom_fields.all():
            if cf.name in required_fields:
                existing_fields.append(cf.name)
                print(f"✅ {cf.name}")
        
        missing = set(required_fields) - set(existing_fields)
        if missing:
            print(f"\n❌ Отсутствующие поля:")
            for field in missing:
                print(f"   - {field}")
            print("\n💡 Запустите: python create_custom_fields.py")
            return False
        else:
            print("\n✅ Все Custom Fields на месте")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def check_racks_and_locations():
    """Проверка проблем с Rack и Location"""
    print("\n" + "=" * 60)
    print("ПРОВЕРКА RACK И LOCATION")
    print("=" * 60)
    
    try:
        netbox = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)
        netbox.http_session.verify = config.VERIFY_SSL
        
        # Проверяем Sites
        for site_name in config.SITE_MAPPING.values():
            site = netbox.dcim.sites.get(name=site_name)
            if site:
                print(f"✅ Site: {site_name}")
                
                # Проверяем Location
                location_name = config.LOCATION_MAPPING.get(site_name)
                if location_name:
                    location = netbox.dcim.locations.get(name=location_name)
                    if location:
                        print(f"   ✅ Location: {location_name}")
                    else:
                        print(f"   ⚠️ Location не найдена: {location_name}")
                
                # Проверяем Racks
                racks = netbox.dcim.racks.filter(site_id=site.id)
                rack_count = len(list(racks))
                if rack_count > 0:
                    print(f"   📦 Racks в site: {rack_count}")
                    
                    # Проверяем проблемные rack
                    for rack in racks:
                        if rack.location:
                            # Проверяем что location принадлежит тому же site
                            if rack.location.site.id != site.id:
                                print(f"   ❌ Rack {rack.name}: location в другом site!")
            else:
                print(f"❌ Site не найден: {site_name}")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    
    return True

def find_missing_devices():
    """Поиск пропавших устройств"""
    print("\n" + "=" * 60)
    print("ПОИСК ПРОПАВШИХ УСТРОЙСТВ")
    print("=" * 60)
    
    try:
        # Получаем хосты из Zabbix
        zabbix = ZabbixAPI(config.ZABBIX_URL, timeout=config.TIMEOUT)
        zabbix.session.verify = config.VERIFY_SSL
        zabbix.login(config.ZABBIX_USER, config.ZABBIX_PASSWORD)
        
        vmware_hosts = zabbix.host.get(
            output=['hostid', 'name'],
            selectParentTemplates=['name'],
            filter={'status': '0'}
        )
        
        # Фильтруем VMware
        zabbix_hosts = {}
        for host in vmware_hosts:
            templates = [t.get('name', '') for t in host.get('parentTemplates', [])]
            if any('VMware' in t for t in templates):
                zabbix_hosts[host['hostid']] = host['name']
        
        print(f"Найдено {len(zabbix_hosts)} VMware хостов в Zabbix")
        
        # Получаем устройства из NetBox
        netbox = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)
        netbox.http_session.verify = config.VERIFY_SSL
        
        netbox_devices = {}
        for device in netbox.dcim.devices.filter(cf_zabbix_hostid__n=False):
            zabbix_id = device.custom_fields.get('zabbix_hostid')
            if zabbix_id:
                netbox_devices[str(zabbix_id)] = {
                    'name': device.name,
                    'status': device.status.value if device.status else 'unknown'
                }
        
        print(f"Найдено {len(netbox_devices)} устройств с Zabbix ID в NetBox")
        
        # Сравниваем
        missing_in_netbox = set(zabbix_hosts.keys()) - set(netbox_devices.keys())
        missing_in_zabbix = set(netbox_devices.keys()) - set(zabbix_hosts.keys())
        
        if missing_in_netbox:
            print(f"\n⚠️ Отсутствуют в NetBox ({len(missing_in_netbox)}):")
            for host_id in list(missing_in_netbox)[:10]:
                print(f"   - {zabbix_hosts[host_id]} (ID: {host_id})")
            if len(missing_in_netbox) > 10:
                print(f"   ... и еще {len(missing_in_netbox) - 10}")
        
        if missing_in_zabbix:
            print(f"\n⚠️ Отсутствуют в Zabbix ({len(missing_in_zabbix)}):")
            for host_id in list(missing_in_zabbix)[:10]:
                device = netbox_devices[host_id]
                print(f"   - {device['name']} (ID: {host_id}, Status: {device['status']})")
            if len(missing_in_zabbix) > 10:
                print(f"   ... и еще {len(missing_in_zabbix) - 10}")
        
        if not missing_in_netbox and not missing_in_zabbix:
            print("\n✅ Все устройства синхронизированы")
        
        return len(missing_in_netbox), len(missing_in_zabbix)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return 0, 0

def clear_redis_cache():
    """Очистка Redis кэша"""
    print("\n" + "=" * 60)
    print("ОЧИСТКА REDIS КЭША")
    print("=" * 60)
    
    try:
        r = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None
        )
        
        keys = list(r.scan_iter(f"{config.REDIS_KEY_PREFIX}*"))
        if keys:
            response = input(f"Удалить {len(keys)} ключей из Redis? (y/n): ")
            if response.lower() == 'y':
                for key in keys:
                    r.delete(key)
                print(f"✅ Удалено {len(keys)} ключей")
            else:
                print("❌ Отменено")
        else:
            print("ℹ️ Кэш уже пуст")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    """Главная функция диагностики"""
    print("\n🔍 ДИАГНОСТИКА СИНХРОНИЗАЦИИ ZABBIX → NETBOX")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Проверки
    if not check_connections():
        print("\n❌ Проблемы с подключением. Проверьте настройки в .env")
        sys.exit(1)
    
    check_custom_fields()
    check_racks_and_locations()
    missing_nb, missing_zb = find_missing_devices()
    
    # Рекомендации
    print("\n" + "=" * 60)
    print("РЕКОМЕНДАЦИИ")
    print("=" * 60)
    
    if missing_nb > 0:
        print("📌 Для восстановления пропавших устройств:")
        print("   1. Очистите Redis кэш (опция ниже)")
        print("   2. Запустите: python main.py --no-redis --limit 10")
        print("   3. Если все ОК, запустите полную синхронизацию")
    
    # Меню действий
    print("\n" + "=" * 60)
    print("ДОСТУПНЫЕ ДЕЙСТВИЯ")
    print("=" * 60)
    print("1. Очистить Redis кэш")
    print("2. Показать последние ошибки из логов")
    print("3. Выход")
    
    choice = input("\nВыберите действие (1-3): ")
    
    if choice == '1':
        clear_redis_cache()
    elif choice == '2':
        import os
        import glob
        
        log_files = glob.glob(f"{config.LOG_DIR}/sync_*.log")
        if log_files:
            latest_log = max(log_files, key=os.path.getctime)
            print(f"\nПоследний лог: {latest_log}")
            
            with open(latest_log, 'r') as f:
                lines = f.readlines()
                errors = [line for line in lines if 'ERROR' in line]
                
            if errors:
                print("\nПоследние ошибки:")
                for error in errors[-10:]:
                    print(error.strip())
            else:
                print("✅ Ошибок не найдено")
    
    print("\n✨ Диагностика завершена")

if __name__ == "__main__":
    main()
