package com.matan.sleepdetector

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ParcelUuid
import android.os.PowerManager
import java.util.UUID

/** Foreground service: keeps the BLE heart-rate stream alive with the screen off. */
@SuppressLint("MissingPermission")
class SleepService : Service() {

    companion object {
        const val ACTION_STOP = "stop"
        private const val CHANNEL = "sleep_monitor"
        private const val NOTIF_ID = 1
        private val HR_SERVICE = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
        private val HR_CHAR = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
        private val CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        private const val STALE_MS = 30_000L
    }

    private val handler = Handler(Looper.getMainLooper())
    private var gatt: BluetoothGatt? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var lastSampleAt = 0L
    private var scanning = false
    private var stopped = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        SleepMonitor.init(this)
        if (intent?.action == ACTION_STOP) {
            shutdown()
            return START_NOT_STICKY
        }
        startForegroundCompat()
        if (!SleepMonitor.running) {
            SleepMonitor.running = true
            stopped = false
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sleepdetector:ble").apply { acquire() }
            startScan()
            handler.postDelayed(watchdog, 5_000)
            handler.postDelayed(notifTick, 15_000)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        shutdown()
        super.onDestroy()
    }

    private fun shutdown() {
        stopped = true
        SleepMonitor.running = false
        SleepMonitor.bleStatus = "Stopped"
        handler.removeCallbacksAndMessages(null)
        stopScan()
        gatt?.close(); gatt = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // ------------------------------------------------------------------ BLE
    private val adapter get() = (getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter

    private fun startScan() {
        if (stopped) return
        val scanner = adapter?.bluetoothLeScanner
        if (scanner == null) {
            SleepMonitor.bleStatus = "Bluetooth is off"
            handler.postDelayed({ startScan() }, 5_000)
            return
        }
        SleepMonitor.bleStatus = "Scanning for Fitbit Air... (Share heart rate must be ON)"
        val filters = listOf(
            ScanFilter.Builder().setServiceUuid(ParcelUuid(HR_SERVICE)).build(),
            ScanFilter.Builder().setDeviceName("Google Fitbit Air").build(),
        )
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        scanning = true
        scanner.startScan(filters, settings, scanCallback)
        // give up and retry if nothing is found
        handler.postDelayed({
            if (scanning && gatt == null) { stopScan(); startScan() }
        }, 20_000)
    }

    private fun stopScan() {
        if (!scanning) return
        scanning = false
        try { adapter?.bluetoothLeScanner?.stopScan(scanCallback) } catch (_: Exception) {}
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            if (gatt != null) return
            stopScan()
            connect(result.device)
        }

        override fun onScanFailed(errorCode: Int) {
            SleepMonitor.bleStatus = "Scan failed ($errorCode), retrying..."
            scanning = false
            handler.postDelayed({ startScan() }, 5_000)
        }
    }

    private fun connect(device: BluetoothDevice) {
        SleepMonitor.bleStatus = "Connecting to ${device.name ?: "Fitbit Air"}..."
        lastSampleAt = System.currentTimeMillis()
        gatt = device.connectGatt(this, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
    }

    private fun reconnectSoon() {
        gatt?.close(); gatt = null
        if (!stopped) handler.postDelayed({ startScan() }, 3_000)
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                SleepMonitor.bleStatus = "Connected, discovering services..."
                g.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                SleepMonitor.bleStatus = "Disconnected, reconnecting..."
                handler.post { reconnectSoon() }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val ch = g.getService(HR_SERVICE)?.getCharacteristic(HR_CHAR)
            if (ch == null) {
                SleepMonitor.bleStatus = "Heart-rate service not found"
                handler.post { reconnectSoon() }
                return
            }
            g.setCharacteristicNotification(ch, true)
            val desc = ch.getDescriptor(CCCD)
            @Suppress("DEPRECATION")
            run {
                desc.value = android.bluetooth.BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                g.writeDescriptor(desc)
            }
            SleepMonitor.bleStatus = "Streaming live pulse"
        }

        @Deprecated("Deprecated in API 33; still invoked on all versions")
        override fun onCharacteristicChanged(g: BluetoothGatt, ch: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val data = ch.value ?: return
            if (data.size < 2) return
            val flags = data[0].toInt()
            val bpm = if (flags and 0x01 != 0 && data.size >= 3)
                (data[1].toInt() and 0xFF) or ((data[2].toInt() and 0xFF) shl 8)
            else data[1].toInt() and 0xFF
            if (bpm <= 0) return
            val now = System.currentTimeMillis()
            lastSampleAt = now
            SleepMonitor.bleStatus = "Streaming live pulse: $bpm BPM"
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            SleepMonitor.onSample(now, bpm.toDouble(), pm.isInteractive)
        }
    }

    /** If the link is up but silent for 30 s, drop it and rescan. */
    private val watchdog = object : Runnable {
        override fun run() {
            if (!stopped && gatt != null && System.currentTimeMillis() - lastSampleAt > STALE_MS) {
                SleepMonitor.bleStatus = "No data, reconnecting..."
                reconnectSoon()
            }
            handler.postDelayed(this, 5_000)
        }
    }

    // --------------------------------------------------------- notification
    private val notifTick = object : Runnable {
        override fun run() {
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, buildNotification())
            handler.postDelayed(this, 15_000)
        }
    }

    private fun buildNotification(): Notification {
        val snap = SleepMonitor.latest()
        val text = if (snap != null)
            "${snap.state.name.lowercase().replaceFirstChar { it.uppercase() }} - ${snap.hr.toInt()} BPM - ${SleepMonitor.tvStatus}"
        else SleepMonitor.bleStatus
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Sleep Detector running")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private fun startForegroundCompat() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "Sleep monitoring", NotificationManager.IMPORTANCE_LOW))
        val n = buildNotification()
        if (Build.VERSION.SDK_INT >= 29)
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        else startForeground(NOTIF_ID, n)
    }
}
