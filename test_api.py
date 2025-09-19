import pynetbox
import os
from dotenv import load_dotenv

load_dotenv()

NETBOX_URL = os.getenv('NETBOX_URL')
NETBOX_TOKEN = os.getenv('NETBOX_TOKEN')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'

netbox = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
netbox.http_session.verify = VERIFY_SSL

try:
    # Замени ID на реальные из твоего NetBox (найди в UI: device_type, role, site)
    device = netbox.dcim.devices.create(
        name="test-device",
        device_type=1,  # ID типа устройства (например, PowerEdge R640)
        role=1,         # ID роли (например, Server)
        site=1,         # ID сайта (например, DC Karaganda)
        status="active",
        custom_fields={
            "zabbix_hostid": "12345",  # Тестовое значение
            "last_sync": "2025-09-19T05:00:00"  # ISO-формат для datetime
        }
    )
    print("Тестовое устройство создано успешно!")
except Exception as e:
    print(f"Ошибка: {e}")
