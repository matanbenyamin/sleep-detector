import asyncio
import warnings
warnings.filterwarnings("ignore")
from bleak import BleakScanner

async def scan():
    print("Initializing scanner...")
    # Give CoreBluetooth delegate a moment to initialize
    try:
        async with BleakScanner() as scanner:
            print("Scanner started. Listening for advertisements for 5 seconds...")
            await asyncio.sleep(5.0)
            devices = scanner.discovered_devices_and_advertisement_data
            print(f"Discovered {len(devices)} devices:")
            for d, adv in devices.values():
                name = d.name or adv.local_name or "Unknown"
                print(f"  {name} | RSSI: {adv.rssi} | UUID: {d.address} | Services: {adv.service_uuids}")
    except Exception as e:
        print(f"Scan error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(scan())
