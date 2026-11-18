package com.matan.sleepdetector

import android.content.Context
import android.content.SharedPreferences
import java.io.File
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale

/** Process-wide state shared by the foreground service (writer) and the UI (reader). */
object SleepMonitor {
    private lateinit var prefs: SharedPreferences
    private lateinit var logDir: File
    private var initialised = false

    lateinit var detector: SleepDetector
        private set

    // history for the chart: (ms, bpm)
    private val history = ArrayDeque<LongArray>()
    private const val MAX_HISTORY = 6 * 3600

    @Volatile var bleStatus = "Not running"
    @Volatile var running = false
    @Volatile var tvStatus = ""
    private var tvTriggeredAtMs = 0L
    private var tvDone = false

    var tvIp: String
        get() = prefs.getString("tv_ip", "192.168.1.215")!!
        set(v) = prefs.edit().putString("tv_ip", v.trim()).apply()
    var tvDelaySec: Int
        get() = prefs.getInt("tv_delay", 180)
        set(v) = prefs.edit().putInt("tv_delay", v).apply()
    var tvEnabled: Boolean
        get() = prefs.getBoolean("tv_enabled", true)
        set(v) = prefs.edit().putBoolean("tv_enabled", v).apply()
    var lgKey: String
        get() = prefs.getString("lg_key", "")!!
        set(v) = prefs.edit().putString("lg_key", v.trim()).apply()

    @Synchronized
    fun init(ctx: Context) {
        if (initialised) return
        prefs = ctx.applicationContext.getSharedPreferences("sleep", Context.MODE_PRIVATE)
        logDir = File(ctx.applicationContext.filesDir, "hr_logs").apply { mkdirs() }
        detector = SleepDetector(
            dropRef = prefs.getFloat("drop_ref", 0.09f).toDouble(),
            nSleeps = prefs.getInt("n_sleeps", 0),
            restPrior = prefs.getFloat("rest_hr", 50f).toDouble().takeIf { it > 0 },
        ).also { d ->
            d.onPrior = { prefs.edit().putFloat("rest_hr", it.toFloat()).apply() }
            d.onLearn = { drop, n -> prefs.edit().putFloat("drop_ref", drop.toFloat()).putInt("n_sleeps", n).apply() }
        }
        initialised = true
    }

    /** Personal resting HR (BPM): auto-learned over time; you can seed it. 0 = unknown. */
    var restHr: Double
        get() = detector.restPrior ?: 0.0
        set(v) { prefs.edit().putFloat("rest_hr", v.toFloat()).apply(); detector.setRestPrior(if (v > 0) v else null) }

    fun tvClient() = LgTv(tvIp, lgKey.ifEmpty { null }) { lgKey = it }

    @Synchronized
    fun onSample(tMs: Long, bpm: Double, phoneInUse: Boolean = false) {
        if (phoneInUse) detector.lastActivityMs = tMs
        history.addLast(longArrayOf(tMs, bpm.toLong()))
        while (history.size > MAX_HISTORY) history.removeFirst()
        logSample(tMs, bpm)
        detector.add(tMs, bpm)
        checkTv(tMs)
    }

    private fun logSample(tMs: Long, bpm: Double) {
        try {
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date(tMs))
            val f = File(logDir, "hr_$day.csv")
            val isNew = !f.exists()
            f.appendText((if (isNew) "timestamp,bpm\n" else "") +
                SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date(tMs)) + ",${bpm.toInt()}\n")
        } catch (_: Exception) {}
    }

    private fun checkTv(nowMs: Long) {
        val d = detector
        if (!tvEnabled) { tvStatus = "TV auto-off disabled"; return }
        if (d.state == SleepState.AWAKE) tvDone = false
        val since = d.asleepSinceMs
        if (d.isAsleep && since != null) {
            val sustained = (nowMs - since) / 1000
            if (tvDone) { tvStatus = "TV powered off"; return }
            if (sustained >= tvDelaySec) {
                // retry at most every 30 s if the TV did not answer
                if (nowMs - tvTriggeredAtMs > 30_000) {
                    tvTriggeredAtMs = nowMs
                    tvStatus = "TV powering off..."
                    Thread {
                        val r = tvClient().powerOff()
                        tvStatus = if (r.ok) "TV powered off" else "TV off failed: ${r.message}"
                        if (r.ok) tvDone = true
                    }.start()
                }
            } else tvStatus = "TV shutting off in ${tvDelaySec - sustained}s"
        } else tvStatus = "TV auto-off armed (${tvDelaySec}s after sleep onset)"
    }

    @Synchronized
    fun historySince(sinceMs: Long): List<LongArray> = history.filter { it[0] >= sinceMs }

    @Synchronized
    fun snapshotsSince(sinceMs: Long): List<Snapshot> = detector.snapshots.filter { it.tMs >= sinceMs }

    @Synchronized
    fun latest(): Snapshot? = detector.snapshots.lastOrNull()

    fun logFiles(): List<File> = logDir.listFiles()?.sortedBy { it.name } ?: emptyList()
}
