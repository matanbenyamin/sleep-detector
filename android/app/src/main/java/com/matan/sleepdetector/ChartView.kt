package com.matan.sleepdetector

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.view.View
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

/** Heart rate (gradient area) + resting level + state bands, with a sleep-score strip below. */
class ChartView(ctx: Context) : View(ctx) {
    companion object {
        val GRID = Color.parseColor("#1E2430")
        val MUTED = Color.parseColor("#7C8599")
        val HR = Color.parseColor("#FF5C7A")
        val BASE = Color.parseColor("#8A93A6")
        val PURPLE = Color.parseColor("#9B7BFF")
        val BLUE = Color.parseColor("#4C8DFF")
        val AMBER = Color.parseColor("#FFB224")
        fun stateColor(s: SleepState) = when (s) {
            SleepState.AWAKE -> AMBER; SleepState.DROWSY -> BLUE; SleepState.ASLEEP -> PURPLE
        }
    }

    var viewMinutes = 30
    private val d = ctx.resources.displayMetrics.density

    private fun stroke(color: Int, w: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = color; strokeWidth = w * d; style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
    }
    private fun fillP(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color; style = Paint.Style.FILL }

    private val pGrid = stroke(GRID, 1f)
    private val pText = fillP(MUTED).apply { textSize = 10.5f * d }
    private val pRaw = stroke(HR, 1f).apply { alpha = 70 }
    private val pHr = stroke(HR, 2.6f)
    private val pBase = stroke(BASE, 1.3f).apply { pathEffect = DashPathEffect(floatArrayOf(7 * d, 6 * d), 0f) }
    private val pScore = stroke(PURPLE, 2f)
    private val pArea = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val pScoreArea = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val pDot = fillP(HR)
    private val pDotRing = fillP(HR).apply { alpha = 60 }
    private val pBand = fillP(PURPLE)
    private val pThresh = stroke(MUTED, 0.8f).apply { pathEffect = DashPathEffect(floatArrayOf(4 * d, 6 * d), 0f); alpha = 110 }
    private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())

    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat()
        val left = 30 * d; val right = w - 4 * d
        val top = 4 * d; val axisH = 18 * d; val gap = 14 * d
        val scoreH = (h - top - axisH - gap) * 0.2f
        val hrBox = RectF(left, top, right, h - axisH - gap - scoreH)
        val scBox = RectF(left, hrBox.bottom + gap, right, h - axisH)

        val end = System.currentTimeMillis()
        val start = end - viewMinutes * 60_000L
        val hist = SleepMonitor.historySince(start)
        val snaps = SleepMonitor.snapshotsSince(start)
        if (hist.isEmpty()) {
            pText.textAlign = Paint.Align.CENTER
            c.drawText("Waiting for heart rate...", w / 2, hrBox.centerY(), pText)
            pText.textAlign = Paint.Align.LEFT
            return
        }
        val tEnd = end + viewMinutes * 60_000L / 14
        fun x(t: Long, box: RectF) = box.left + (t - start).toFloat() / (tEnd - start) * box.width()

        val smooth = smooth(hist.map { it[1].toDouble() })
        var lo = smooth.min(); var hi = smooth.max()
        snaps.lastOrNull()?.let { lo = min(lo, it.baseline - 2); hi = max(hi, it.baseline + 1) }
        lo = max(30.0, lo - 4); hi += 5
        fun y(v: Double) = (hrBox.bottom - (v - lo) / (hi - lo) * hrBox.height()).toFloat()

        // grid + labels
        val step = if (hi - lo > 50) 20 else if (hi - lo > 22) 10 else 5
        var g = (ceil(lo / step) * step).toInt()
        pText.textAlign = Paint.Align.RIGHT
        while (g < hi) {
            c.drawLine(hrBox.left, y(g.toDouble()), hrBox.right, y(g.toDouble()), pGrid)
            c.drawText("$g", left - 6 * d, y(g.toDouble()) + 3.5f * d, pText)
            g += step
        }
        pText.textAlign = Paint.Align.CENTER
        for (i in 0..3) {
            val tt = start + (tEnd - start) * i / 4
            c.drawText(timeFmt.format(Date(tt)), x(tt, scBox), h - 3 * d, pText)
        }
        pText.textAlign = Paint.Align.LEFT

        // state bands (rounded-feel: full height soft tint)
        var i = 0
        while (i < snaps.size) {
            val s = snaps[i].state
            var j = i
            while (j + 1 < snaps.size && snaps[j + 1].state == s) j++
            if (s != SleepState.AWAKE) {
                pBand.color = stateColor(s); pBand.alpha = if (s == SleepState.DROWSY) 34 else 52
                val x0 = x(snaps[i].tMs, hrBox)
                val x1 = if (j + 1 < snaps.size) x(snaps[j + 1].tMs, hrBox) else x(end, hrBox)
                c.drawRoundRect(x0, hrBox.top, x1, hrBox.bottom, 6 * d, 6 * d, pBand)
                c.drawRoundRect(x0, scBox.top, x1, scBox.bottom, 6 * d, 6 * d, pBand)
            }
            i = j + 1
        }

        // paths
        val raw = Path(); val sm = Path(); val area = Path()
        hist.forEachIndexed { k, p ->
            val px = x(p[0], hrBox)
            if (k == 0) { raw.moveTo(px, y(p[1].toDouble())); sm.moveTo(px, y(smooth[k])); area.moveTo(px, hrBox.bottom); area.lineTo(px, y(smooth[k])) }
            else { raw.lineTo(px, y(p[1].toDouble())); sm.lineTo(px, y(smooth[k])); area.lineTo(px, y(smooth[k])) }
        }
        area.lineTo(x(hist.last()[0], hrBox), hrBox.bottom); area.close()
        pArea.shader = LinearGradient(0f, hrBox.top, 0f, hrBox.bottom, Color.argb(90, 255, 92, 122), Color.argb(0, 255, 92, 122), Shader.TileMode.CLAMP)

        c.save(); c.clipRect(hrBox)
        c.drawPath(area, pArea)
        if (snaps.size > 1) {
            val bp = Path()
            snaps.forEachIndexed { k, s -> if (k == 0) bp.moveTo(x(s.tMs, hrBox), y(s.baseline)) else bp.lineTo(x(s.tMs, hrBox), y(s.baseline)) }
            c.drawPath(bp, pBase)
        }
        c.drawPath(raw, pRaw)
        c.drawPath(sm, pHr)
        c.restore()
        val lx = x(hist.last()[0], hrBox); val ly = y(smooth.last())
        c.drawCircle(lx, ly, 8 * d, pDotRing)
        c.drawCircle(lx, ly, 4 * d, pDot)

        // score strip
        val cfg = SleepConfig()
        for (th in listOf(cfg.drowsyOn, cfg.asleepOn)) {
            val yy = scBox.bottom - th.toFloat() * scBox.height()
            c.drawLine(scBox.left, yy, scBox.right, yy, pThresh)
        }
        if (snaps.size > 1) {
            val line = Path(); val fill = Path()
            snaps.forEachIndexed { k, s ->
                val px = x(s.tMs, scBox); val py = scBox.bottom - s.score.toFloat() * scBox.height()
                if (k == 0) { line.moveTo(px, py); fill.moveTo(px, scBox.bottom); fill.lineTo(px, py) }
                else { line.lineTo(px, py); fill.lineTo(px, py) }
            }
            fill.lineTo(x(snaps.last().tMs, scBox), scBox.bottom); fill.close()
            pScoreArea.shader = LinearGradient(0f, scBox.top, 0f, scBox.bottom, Color.argb(80, 155, 123, 255), Color.argb(0, 155, 123, 255), Shader.TileMode.CLAMP)
            c.drawPath(fill, pScoreArea); c.drawPath(line, pScore)
        }
        c.drawText("sleep score", scBox.left + 6 * d, scBox.top + 12 * d, pText)
    }

    private fun smooth(a: List<Double>, k: Int = 15): DoubleArray {
        if (a.size < 3) return a.toDoubleArray()
        val half = k / 2
        return DoubleArray(a.size) { i ->
            val s = a.subList(max(0, i - half), min(a.size, i + half + 1)).sorted()
            s[s.size / 2]
        }
    }
}
