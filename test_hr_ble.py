import asyncio
import warnings
warnings.filterwarnings("ignore")
from bleak import BleakClient

HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
DEVICE_UUID = "67D44C91-9EDA-9C47-6B70-3CF89A78C4EF"

received_points = []

def hr_callback(sender, data):
    flags = data[0]
    if flags & 0x01:
        bpm = int.from_bytes(data[1:3], byteorder='little')
    else:
        bpm = data[1]
    received_points.append(bpm)
    print(f"--> [PULSE] {bpm} BPM (raw: {list(data)})")

async def main():
    print(f"Connecting to Google Fitbit Air...")
    async with BleakClient(DEVICE_UUID, timeout=15.0) as client:
        print(f"Connected: {client.is_connected}")
        print("Subscribing to Heart Rate notifications...")
        await client.start_notify(HR_CHAR_UUID, hr_callback)
        print("Listening for 15 seconds (make sure the band is touching skin/wrist)...")
        for i in range(15):
            await asyncio.sleep(1.0)
            if received_points:
                print(f"[{i}s] Current latest: {received_points[-1]} BPM")
            else:
                print(f"[{i}s] Waiting for pulse from optical sensor...")
        await client.stop_notify(HR_CHAR_UUID)
        print(f"Done. Total pulses received: {len(received_points)}")

if __name__ == "__main__":
    asyncio.run(main())
