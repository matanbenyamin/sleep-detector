BRIDGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sleep Detector — Phone Wi-Fi Bridge</title>
<style>
  body { background: #0e0e18; color: #fff; font-family: -apple-system, system-ui, sans-serif; text-align: center; padding: 25px 15px; margin: 0; }
  .card { background: #1a1a2e; border: 1px solid #333355; border-radius: 20px; padding: 30px 20px; max-width: 380px; margin: 30px auto; box-shadow: 0 8px 32px rgba(0,0,0,0.6); }
  h2 { margin: 0 0 10px 0; font-size: 22px; color: #ffffff; }
  .desc { color: #8888aa; font-size: 14px; margin-bottom: 25px; line-height: 1.4; }
  .bpm-box { background: #121222; border-radius: 16px; padding: 20px; margin-bottom: 25px; border: 1px solid #2a2a44; }
  .bpm { font-size: 64px; font-weight: 800; color: #00ffff; letter-spacing: -1px; }
  .bpm-label { font-size: 13px; color: #666688; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
  .status { color: #ff9900; font-size: 14px; min-height: 20px; font-weight: 500; }
  .status.active { color: #00ff88; }
  .btn { background: linear-gradient(135deg, #00ffff, #0088ff); color: #000; font-size: 17px; font-weight: 700; border: none; border-radius: 30px; padding: 16px 28px; cursor: pointer; width: 100%; box-shadow: 0 4px 15px rgba(0,255,255,0.3); margin-top: 20px; transition: transform 0.1s; }
  .btn:active { transform: scale(0.98); }
</style>
</head>
<body>
<div class="card">
  <h2>💤 Sleep Detector Bridge</h2>
  <div class="desc">Connects your Fitbit Air to your Mac over home Wi-Fi</div>
  <div class="bpm-box">
    <div class="bpm" id="bpm-val">--</div>
    <div class="bpm-label">Live Heart Rate (BPM)</div>
  </div>
  <div class="status" id="status-val">Ready to pair</div>
  <button class="btn" id="connect-btn" onclick="connectBle()">CONNECT FITBIT AIR</button>
</div>
<script>
async function connectBle() {
  const status = document.getElementById('status-val');
  const bpmDisp = document.getElementById('bpm-val');
  const btn = document.getElementById('connect-btn');
  try {
    status.innerText = "Searching for Fitbit Air...";
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ services: ['heart_rate'] }]
    });
    status.innerText = "Connecting to " + (device.name || "Fitbit Air") + "...";
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService('heart_rate');
    const char = await service.getCharacteristic('heart_rate_measurement');
    await char.startNotifications();
    
    status.className = "status active";
    status.innerText = "Streaming to Mac over Wi-Fi ✓";
    btn.style.display = 'none';

    char.addEventListener('characteristicvaluechanged', (e) => {
      const data = e.target.value;
      const flags = data.getUint8(0);
      let bpm = (flags & 0x01) ? data.getUint16(1, true) : data.getUint8(1);
      bpmDisp.innerText = bpm;
      fetch('/hr?bpm=' + bpm).catch(e => {});
    });

    device.addEventListener('gattserverdisconnected', () => {
      status.className = "status";
      status.innerText = "Disconnected. Tap reconnect.";
      btn.style.display = 'block';
      btn.innerText = "RECONNECT FITBIT";
    });
  } catch (err) {
    status.innerText = "Pairing cancelled or error: " + err.message;
  }
}
</script>
</body>
</html>
"""
