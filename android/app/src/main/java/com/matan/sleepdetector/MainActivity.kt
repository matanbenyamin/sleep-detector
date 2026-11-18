package com.matan.sleepdetector

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val dens by lazy { resources.displayMetrics.density }
    private fun dp(v: Int) = (v * dens).toInt()

    // palette
    private val bg = Color.parseColor("#0B0D12")
    private val card = Color.parseColor("#141821")
    private val field = Color.parseColor("#1B2130")
    private val text1 = Color.parseColor("#F2F4F8")
    private val muted = Color.parseColor("#8A93A6")
    private val accent = Color.parseColor("#7C5CFF")
    private val red = Color.parseColor("#FF5C7A")
    private val green = Color.parseColor("#3DDC97")

    private lateinit var stateTitle: TextView
    private lateinit var stateSub: TextView
    private lateinit var bpm: TextView
    private lateinit var conn: TextView
    private lateinit var connDot: View
    private lateinit var prob: ProbBar
    private lateinit var probLabel: TextView
    private lateinit var chart: ChartView
    private lateinit var tvTitle: TextView
    private lateinit var tvSub: TextView
    private lateinit var toggle: TextView
    private lateinit var settingsBody: LinearLayout
    private lateinit var ipEdit: EditText
    private lateinit var delayEdit: EditText
    private lateinit var restEdit: EditText
    private lateinit var keyEdit: EditText
    private val rangeChips = ArrayList<TextView>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SleepMonitor.init(this)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_PAN)
        setContentView(buildUi())
    }

    override fun onResume() { super.onResume(); ui.post(tick) }
    override fun onPause() { ui.removeCallbacks(tick); super.onPause() }

    private val tick = object : Runnable {
        override fun run() { refresh(); ui.postDelayed(this, 1000) }
    }

    // ------------------------------------------------------------ helpers
    private fun rounded(color: Int, radiusDp: Int, strokeColor: Int? = null) = GradientDrawable().apply {
        cornerRadius = dp(radiusDp).toFloat(); setColor(color)
        if (strokeColor != null) setStroke(dp(1), strokeColor)
    }

    private fun tv(size: Float, color: Int = text1, font: String = "sans-serif", bold: Boolean = false) = TextView(this).apply {
        textSize = size; setTextColor(color)
        typeface = Typeface.create(font, if (bold) Typeface.BOLD else Typeface.NORMAL)
        includeFontPadding = false
    }

    private fun cardBox(pad: Int = 18): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(card, 24)
        setPadding(dp(pad), dp(pad), dp(pad), dp(pad))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(14) }
    }

    private fun pillButton(label: String, filled: Boolean, onClick: () -> Unit) = TextView(this).apply {
        text = label; gravity = Gravity.CENTER; textSize = 15f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setTextColor(if (filled) Color.WHITE else text1)
        background = if (filled) rounded(accent, 28) else rounded(Color.TRANSPARENT, 28, Color.parseColor("#2A3244"))
        setPadding(dp(18), dp(14), dp(18), dp(14))
        setOnClickListener { onClick() }
    }

    private fun editField(hint: String, value: String, number: Boolean = false, decimal: Boolean = false) = EditText(this).apply {
        setText(value); setHint(hint); setTextColor(text1); setHintTextColor(muted); textSize = 15f
        isSingleLine = true; background = rounded(field, 14); setPadding(dp(14), dp(12), dp(14), dp(12))
        if (number) inputType = InputType.TYPE_CLASS_NUMBER
        if (decimal) inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
    }

    private fun label(text: String) = tv(12f, muted).apply {
        this.text = text.uppercase(); letterSpacing = 0.08f; setPadding(0, dp(14), 0, dp(6))
    }

    // ----------------------------------------------------------------- UI
    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(28))
        }

        // top bar
        val bar = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        bar.addView(tv(20f, text1, "sans-serif-medium").apply { text = "Sleep Detector" },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        connDot = View(this).apply { background = rounded(muted, 8) }
        bar.addView(connDot, LinearLayout.LayoutParams(dp(8), dp(8)).apply { rightMargin = dp(8) })
        conn = tv(12f, muted).apply { text = "Not running"; maxLines = 1; maxWidth = dp(220); ellipsize = android.text.TextUtils.TruncateAt.END }
        bar.addView(conn)
        root.addView(bar)

        // hero
        val hero = cardBox(22).apply { background = rounded(card, 28) }
        val heroTop = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val left = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        stateTitle = tv(34f, muted, "sans-serif-medium").apply { text = "Idle" }
        stateSub = tv(13f, muted).apply { text = "Start monitoring to begin"; setPadding(0, dp(6), 0, 0) }
        left.addView(stateTitle); left.addView(stateSub)
        heroTop.addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val right = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.END }
        bpm = tv(46f, red, "sans-serif-light").apply { text = "--" }
        right.addView(bpm)
        right.addView(tv(11f, muted).apply { text = "BPM"; letterSpacing = 0.12f; gravity = Gravity.END })
        heroTop.addView(right)
        hero.addView(heroTop)

        prob = ProbBar()
        hero.addView(prob, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(10)).apply { topMargin = dp(22) })
        probLabel = tv(12f, muted).apply { setPadding(0, dp(8), 0, 0) }
        hero.addView(probLabel)
        root.addView(hero)

        // chart card
        val cc = cardBox(16)
        val ch = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        ch.addView(tv(15f, text1, "sans-serif-medium").apply { text = "Heart rate" },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        for ((m, name) in listOf(15 to "15m", 30 to "30m", 60 to "1h", 180 to "3h")) {
            val chip = tv(12f, muted, "sans-serif-medium").apply {
                text = name; gravity = Gravity.CENTER; setPadding(dp(11), dp(6), dp(11), dp(6))
                setOnClickListener { selectRange(m) }
                tag = m
            }
            rangeChips += chip
            ch.addView(chip, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { leftMargin = dp(4) })
        }
        cc.addView(ch)
        chart = ChartView(this)
        cc.addView(chart, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(300)).apply { topMargin = dp(10) })
        root.addView(cc)
        selectRange(30)

        // TV card
        val tc = cardBox(18)
        val tr = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val tcol = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        tvTitle = tv(15f, text1, "sans-serif-medium").apply { text = "LG TV auto-off" }
        tvSub = tv(12.5f, muted).apply { text = ""; setPadding(0, dp(4), 0, 0) }
        tcol.addView(tvTitle); tcol.addView(tvSub)
        tr.addView(tcol, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val sw = Switch(this).apply {
            isChecked = SleepMonitor.tvEnabled
            thumbTintList = ColorStateList.valueOf(Color.WHITE)
            trackTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(accent, Color.parseColor("#3A4256")))
            setOnCheckedChangeListener { _, on -> SleepMonitor.tvEnabled = on }
        }
        tr.addView(sw)
        tc.addView(tr)
        root.addView(tc)

        // start / stop
        toggle = pillButton("Start monitoring", true) { toggleService() }.apply { textSize = 16f; setPadding(dp(18), dp(17), dp(18), dp(17)) }
        root.addView(toggle, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(18) })

        // settings (collapsible)
        val sc = cardBox(18)
        val head = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        head.addView(tv(15f, text1, "sans-serif-medium").apply { text = "Settings" }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val chev = tv(18f, muted).apply { text = "▾" }
        head.addView(chev)
        sc.addView(head)
        settingsBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        settingsBody.addView(label("TV IP address"))
        ipEdit = editField("192.168.1.215", SleepMonitor.tvIp); settingsBody.addView(ipEdit)
        settingsBody.addView(label("Seconds asleep before power-off"))
        delayEdit = editField("180", SleepMonitor.tvDelaySec.toString(), number = true); settingsBody.addView(delayEdit)
        settingsBody.addView(label("Your resting heart rate (auto-learned)"))
        restEdit = editField("e.g. 50", if (SleepMonitor.restHr > 0) "%.0f".format(SleepMonitor.restHr) else "", decimal = true); settingsBody.addView(restEdit)
        settingsBody.addView(label("LG client key"))
        keyEdit = editField("filled in after pairing", SleepMonitor.lgKey); settingsBody.addView(keyEdit)
        val row = LinearLayout(this).apply { setPadding(0, dp(16), 0, 0) }
        val lp = { LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(8) } }
        row.addView(pillButton("Save", true) { saveSettings(true) }, lp())
        row.addView(pillButton("Pair TV", false) { pairTv() }, lp())
        row.addView(pillButton("Test off", false) { testOff() }, lp())
        settingsBody.addView(row)
        sc.addView(settingsBody)
        head.setOnClickListener {
            val open = settingsBody.visibility != View.VISIBLE
            settingsBody.visibility = if (open) View.VISIBLE else View.GONE
            chev.text = if (open) "▴" else "▾"
        }
        root.addView(sc)

        root.addView(tv(11f, muted).apply {
            text = "Samples are saved on this phone (hr_logs/*.csv). Using the phone counts as awake."
            setPadding(dp(4), dp(16), dp(4), 0)
        })
        return ScrollView(this).apply { setBackgroundColor(bg); isVerticalScrollBarEnabled = false; addView(root) }
    }

    private fun selectRange(minutes: Int) {
        chart.viewMinutes = minutes
        for (c in rangeChips) {
            val on = (c.tag as Int) == minutes
            c.setTextColor(if (on) text1 else muted)
            c.background = if (on) rounded(Color.parseColor("#262D40"), 14) else null
        }
        chart.invalidate()
    }

    // sleep-probability bar
    inner class ProbBar : View(this@MainActivity) {
        var value = 0f
        var color = muted
        private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = Color.parseColor("#222838") }
        private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
        private val mark = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = Color.parseColor("#0B0D12"); strokeWidth = dp(2).toFloat() }
        override fun onDraw(c: Canvas) {
            val r = height / 2f
            c.drawRoundRect(RectF(0f, 0f, width.toFloat(), height.toFloat()), r, r, track)
            fill.color = color
            c.drawRoundRect(RectF(0f, 0f, maxOf(height.toFloat(), width * value), height.toFloat()), r, r, fill)
            val cfg = SleepConfig()
            for (t in listOf(cfg.drowsyOn, cfg.asleepOn)) c.drawLine((width * t).toFloat(), 0f, (width * t).toFloat(), height.toFloat(), mark)
        }
    }

    // ------------------------------------------------------------ settings
    private fun saveSettings(toast: Boolean = false) {
        SleepMonitor.tvIp = ipEdit.text.toString()
        SleepMonitor.tvDelaySec = delayEdit.text.toString().toIntOrNull() ?: 180
        restEdit.text.toString().toDoubleOrNull()?.let { SleepMonitor.restHr = it }
        SleepMonitor.lgKey = keyEdit.text.toString()
        if (toast) Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
    }

    private fun pairTv() {
        saveSettings()
        Toast.makeText(this, "Turn the TV on and press Allow on the TV screen", Toast.LENGTH_LONG).show()
        Thread {
            val r = SleepMonitor.tvClient().pair()
            ui.post {
                keyEdit.setText(SleepMonitor.lgKey)
                Toast.makeText(this, if (r.ok) "TV paired" else "Pairing failed: ${r.message}", Toast.LENGTH_LONG).show()
            }
        }.start()
    }

    private fun testOff() {
        saveSettings()
        AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
            .setTitle("Turn the TV off now?")
            .setMessage("This sends a real power-off command to ${SleepMonitor.tvIp}.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Turn off") { _, _ ->
                Thread {
                    val r = SleepMonitor.tvClient().powerOff()
                    ui.post { Toast.makeText(this, if (r.ok) "Sent" else "Failed: ${r.message}", Toast.LENGTH_LONG).show() }
                }.start()
            }.show()
    }

    // ------------------------------------------------------------ service
    private fun toggleService() {
        if (SleepMonitor.running) {
            startService(Intent(this, SleepService::class.java).setAction(SleepService.ACTION_STOP))
            return
        }
        saveSettings()
        val needed = ArrayList<String>()
        if (Build.VERSION.SDK_INT >= 31) {
            needed += Manifest.permission.BLUETOOTH_SCAN
            needed += Manifest.permission.BLUETOOTH_CONNECT
        } else needed += Manifest.permission.ACCESS_FINE_LOCATION
        if (Build.VERSION.SDK_INT >= 33) needed += Manifest.permission.POST_NOTIFICATIONS
        val missing = needed.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1) else startMonitoring()
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, results: IntArray) {
        val bleOk = perms.indices.none { perms[it] != Manifest.permission.POST_NOTIFICATIONS && results[it] != PackageManager.PERMISSION_GRANTED }
        if (bleOk) startMonitoring() else Toast.makeText(this, "Bluetooth permission is required", Toast.LENGTH_LONG).show()
    }

    private fun startMonitoring() {
        startForegroundService(Intent(this, SleepService::class.java))
    }

    // ------------------------------------------------------------ refresh
    private fun refresh() {
        val running = SleepMonitor.running
        toggle.text = if (running) "Stop monitoring" else "Start monitoring"
        toggle.background = if (running) rounded(Color.TRANSPARENT, 28, red) else rounded(accent, 28)
        toggle.setTextColor(if (running) red else Color.WHITE)
        conn.text = SleepMonitor.bleStatus.substringBefore(':').take(40)
        val live = running && SleepMonitor.bleStatus.startsWith("Streaming")
        (connDot.background as GradientDrawable).setColor(if (live) green else if (running) ChartView.AMBER else muted)
        tvSub.text = SleepMonitor.tvStatus.ifEmpty { "Arms once monitoring starts" }
        chart.invalidate()

        val snap = SleepMonitor.latest()
        val last = SleepMonitor.historySince(System.currentTimeMillis() - 15_000).lastOrNull()
        bpm.text = last?.get(1)?.toString() ?: "--"
        val d = SleepMonitor.detector
        if (!running) {
            title("Idle", muted, "Start monitoring to begin"); prob.value = 0f; prob.color = muted; prob.invalidate()
            probLabel.text = ""; return
        }
        val cal = d.calibration
        if (snap == null || cal != null) {
            title("Learning", ChartView.AMBER,
                if (cal != null) "Learning your resting level (${cal.first}/${cal.second} min)" else "Collecting first minutes of data")
            prob.value = 0f; prob.color = ChartView.AMBER; prob.invalidate()
            probLabel.text = "TV control is paused while calibrating"
            return
        }
        val name = snap.state.name.lowercase().replaceFirstChar { it.uppercase() }
        val asleepFor = d.asleepSinceMs?.takeIf { d.isAsleep }?.let { " - asleep for ${(d.lastSampleMs - it) / 60000} min" } ?: ""
        title(name, ChartView.stateColor(snap.state),
            "Resting level ${snap.baseline.toInt()} BPM" + if (snap.reason.isNotEmpty()) "  -  ${snap.reason}" else "")
        prob.value = snap.score.toFloat(); prob.color = ChartView.stateColor(snap.state); prob.invalidate()
        probLabel.text = "Sleep probability ${(snap.score * 100).toInt()}%$asleepFor"
    }

    private fun title(t: String, color: Int, sub: String) {
        stateTitle.text = t; stateTitle.setTextColor(color); stateSub.text = sub
    }
}
