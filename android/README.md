# Sleep Detector for Android

Runs the whole pipeline on the phone: Fitbit Air (BLE "Share heart rate") -> adaptive sleep detector
(Kotlin port of `../sleep_algo.py`) -> LG webOS power-off over Wi-Fi. No Mac needed.

## Build & run
1. Install Android Studio, then **File > Open** this `android/` folder and let Gradle sync.
2. Enable Developer options + USB debugging on the phone, plug it in, press **Run**.

## First use
1. On the Fitbit Air: turn on **Share heart rate** (always visible).
2. In the app: set the TV IP, turn the TV on, tap **Pair TV** and press *Allow* on the TV.
   (Or paste the `client-key` from the Mac's `lgtv_key.json`.)
3. Tap **Start monitoring**. Allow Bluetooth + notifications. It keeps running with the screen off.
4. Android battery settings: set the app to **Unrestricted** so it isn't killed overnight.

`SleepDetector.kt` and `sleep_algo.py` implement the same algorithm; change both together.
