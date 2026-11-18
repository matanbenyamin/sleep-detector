package com.matan.sleepdetector

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/** Kotlin port of sleep_algo.py (adaptive, no fixed BPM threshold). Keep the two in sync. */

enum class SleepState { AWAKE, DROWSY, ASLEEP }

data class Snapshot(
    val tMs: Long,
    val state: SleepState,
    val score: Double,
    val rawScore: Double,
    val hr: Double,
    val baseline: Double,
    val drop: Double,
    val stability: Double,
    val smoothness: Double,
    val trend: Double,
    val penalty: Double,
    val reason: String,
)

class SleepConfig {
    val windowNowS = 120
    val windowRangeS = 300
    val historyS = 45 * 60
    val floorWindowS = 40 * 60
    val floorPercentile = 20.0
    val floorMinEpochs = 8
    val floorMinEpochsCold = 20
    val activityHoldS = 300
    val evalEveryS = 5.0
    val minDataS = 150
    val scoreSmoothTauS = 45.0
    val drowsyOn = 0.42
    val asleepOn = 0.65
    val asleepOff = 0.38
    val drowsyDwellS = 60
    val asleepDwellS = 240
    val wakeDwellS = 120
    val defaultDropFrac = 0.09
}

class SleepDetector(var dropRef: Double = 0.09, var nSleeps: Int = 0, restPrior: Double? = null) {
    val cfg = SleepConfig()

    /** Called once per confirmed sleep with (new dropRef, nSleeps) so the caller can persist it. */
    var onLearn: ((Double, Int) -> Unit)? = null

    /** Steps in the last minutes if known, else -1 (unknown). */
    var recentSteps = -1

    /** Last time the phone was used (screen on) in ms; counts as "awake". */
    @Volatile var lastActivityMs: Long? = null

    /** Persistent personal awake-resting HR, learned across sessions (seedable). */
    var restPrior: Double? = restPrior
        private set
    var onPrior: ((Double) -> Unit)? = null
    fun setRestPrior(v: Double?) { restPrior = v }

    /** Non-null while still learning the resting level: minutes collected / needed. */
    var calibration: Pair<Int, Int>? = null
        private set

    var state = SleepState.AWAKE
        private set
    var score = 0.0
        private set
    var baseline: Double? = null
        private set
    var asleepSinceMs: Long? = null
        private set
    var lastSampleMs: Long = 0
        private set

    val snapshots = ArrayList<Snapshot>()

    private val samples = ArrayDeque<DoubleArray>() // [seconds, bpm]
    private var lastEval = 0.0
    private var drowsySince: Double? = null
    private var aboveSince: Double? = null
    private var belowSince: Double? = null
    private var learnedThisSleep = false
    private val epochs = ArrayList<DoubleArray>() // [ts, 1-min median HR] collected while clearly awake
    private var nextEpoch: Double? = null
    private var lastPriorSave = 0.0

    val isAsleep get() = state == SleepState.ASLEEP

    @Synchronized
    fun add(tMs: Long, bpm: Double): Snapshot? {
        if (bpm < 30 || bpm > 220) return null
        val ts = tMs / 1000.0
        if (samples.isNotEmpty() && ts < samples.last()[0]) return null
        samples.addLast(doubleArrayOf(ts, bpm))
        val cutoff = ts - cfg.historyS
        while (samples.isNotEmpty() && samples.first()[0] < cutoff) samples.removeFirst()
        lastSampleMs = tMs
        if (ts - lastEval >= cfg.evalEveryS) {
            lastEval = ts
            return evaluate(tMs, ts)
        }
        return null
    }

    private fun window(now: Double, seconds: Double, lag: Double = 0.0): DoubleArray {
        val lo = now - lag - seconds
        val hi = now - lag
        val out = ArrayList<Double>()
        for (s in samples) if (s[0] in lo..hi) out.add(s[1])
        return out.toDoubleArray()
    }

    private fun evaluate(tMs: Long, now: Double): Snapshot? {
        if (samples.isEmpty() || now - samples.first()[0] < cfg.minDataS) return null
        val cur = window(now, cfg.windowNowS.toDouble())
        val rng = window(now, cfg.windowRangeS.toDouble())
        if (cur.size < 8) return null

        val hr = median(cur)

        // awake "floor": low percentile of 1-min medians recorded while clearly AWAKE. A real sleep
        // drop must go BELOW the lowest awake resting level; calming down never looks like sleep.
        if (nextEpoch == null) nextEpoch = samples.first()[0] + 60
        if (now >= nextEpoch!!) {
            nextEpoch = now + 60
            val prior0 = restPrior
            val clearlyAwake = state == SleepState.AWAKE && score < 0.3 && (prior0 == null || hr >= 0.94 * prior0)
            if (clearlyAwake) epochs.add(doubleArrayOf(now, hr))
            epochs.removeAll { it[0] < now - cfg.floorWindowS }
            if (state == SleepState.AWAKE && epochs.isNotEmpty()) {
                baseline = percentile(DoubleArray(epochs.size) { epochs[it][1] }, cfg.floorPercentile)
                updatePrior(now)
            }
        }
        val need = if (restPrior != null) cfg.floorMinEpochs else cfg.floorMinEpochsCold
        val calibrating = epochs.size < need && state == SleepState.AWAKE && asleepSinceMs == null
        calibration = if (calibrating) Pair(epochs.size, need) else null
        if (baseline == null) baseline = hr
        val prior = restPrior
        val base = if (prior != null) min(baseline!!, prior) else baseline!!

        // 1. drop
        val margin = max(1.5, 0.03 * base)
        val fullDrop = max(3.5, dropRef * base)
        val drop = clamp01((base - margin - hr) / fullDrop)

        // 2. stability
        val spread = if (rng.size >= 20) percentile(rng, 90.0) - percentile(rng, 10.0) else 10.0
        val stability = clamp01((9.0 - spread) / 7.0)

        // 3. smoothness
        val smoothness = if (cur.size >= 15) {
            val diffs = DoubleArray(cur.size - 1) { abs(cur[it + 1] - cur[it]) }
            clamp01((2.2 - median(diffs)) / 2.0)
        } else 0.0

        // 4. trend (bpm/min over 10 min)
        var trend = 0.0
        val tw = samples.filter { it[0] >= now - 600 }
        if (tw.size >= 60 && tw.last()[0] - tw.first()[0] > 300) {
            val xs = DoubleArray(tw.size) { (tw[it][0] - now) / 60.0 }
            val ys = DoubleArray(tw.size) { tw[it][1] }
            trend = clamp01(-slope(xs, ys) / 0.6)
        }

        // penalties
        var penalty = 0.0
        var reason = ""
        val recent = window(now, 120.0)
        if (state == SleepState.AWAKE && recent.isNotEmpty() && recent.max() - hr > max(10.0, 0.14 * base)) {
            penalty += 0.35
            reason = "HR spike (movement?)"
        }
        if (hr > base + 2) {
            penalty += 0.3
            if (reason.isEmpty()) reason = "HR above resting level"
        }
        val act = lastActivityMs
        if (act != null && tMs - act < cfg.activityHoldS * 1000L) {
            penalty += 0.7
            reason = "phone in use"
        }
        if (recentSteps > 0) {
            penalty += 0.6
            reason = "$recentSteps steps"
        }

        var raw = 0.60 * drop + 0.20 * stability + 0.15 * smoothness + 0.05 * trend
        raw = min(raw, 0.25 + 0.9 * drop)
        raw = clamp01(raw - penalty)
        if (calibrating) { raw = 0.0; reason = "calibrating ($need min needed)" }

        val lastT = if (snapshots.isNotEmpty()) snapshots.last().tMs / 1000.0 else now - cfg.evalEveryS
        val dtime = max(now - lastT, 0.1)
        score += (1 - exp(-dtime / cfg.scoreSmoothTauS)) * (raw - score)

        stepState(tMs, now, hr, base)

        val snap = Snapshot(tMs, state, score, raw, hr, base, drop, stability, smoothness, trend, penalty, reason)
        snapshots.add(snap)
        if (snapshots.size > 6000) snapshots.subList(0, 2000).clear()
        return snap
    }

    private fun updatePrior(now: Double) {
        val b = baseline ?: return
        if (epochs.size < cfg.floorMinEpochsCold) return
        val p = restPrior
        restPrior = if (p == null) b else p + (if (b < p) 0.03 else 0.02) * (b - p)
        if (now - lastPriorSave > 600) {
            lastPriorSave = now
            onPrior?.invoke(restPrior!!)
        }
    }

    private fun stepState(tMs: Long, now: Double, hr: Double, base: Double) {
        val s = score
        if (state == SleepState.AWAKE) {
            if (s >= cfg.drowsyOn) {
                if (drowsySince == null) drowsySince = now
                if (now - drowsySince!! >= cfg.drowsyDwellS) state = SleepState.DROWSY
            } else drowsySince = null
        }
        if (state == SleepState.DROWSY) {
            if (s >= cfg.asleepOn) {
                if (aboveSince == null) aboveSince = now
                if (now - aboveSince!! >= cfg.asleepDwellS) {
                    state = SleepState.ASLEEP
                    asleepSinceMs = tMs - cfg.asleepDwellS * 1000L
                    learnedThisSleep = false
                }
            } else {
                aboveSince = null
                if (s < cfg.drowsyOn - 0.1) {
                    state = SleepState.AWAKE
                    drowsySince = null
                }
            }
        } else if (state == SleepState.ASLEEP) {
            val since = asleepSinceMs
            if (!learnedThisSleep && since != null && (tMs - since) > 600_000) {
                val observed = ((base - hr) / base).coerceIn(0.04, 0.25)
                dropRef += (observed - dropRef) / min(nSleeps + 2, 10)
                nSleeps += 1
                learnedThisSleep = true
                onLearn?.invoke(dropRef, nSleeps)
            }
            if (s < cfg.asleepOff) {
                if (belowSince == null) belowSince = now
                if (now - belowSince!! >= cfg.wakeDwellS) {
                    state = SleepState.AWAKE
                    drowsySince = null; aboveSince = null; belowSince = null
                    asleepSinceMs = null
                }
            } else belowSince = null
        }
    }

    // ------------------------------------------------------------------ math
    private fun clamp01(x: Double) = if (x < 0) 0.0 else if (x > 1) 1.0 else x

    private fun median(a: DoubleArray): Double {
        val s = a.sortedArray()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
    }

    /** numpy-style linear-interpolated percentile. */
    private fun percentile(a: DoubleArray, p: Double): Double {
        val s = a.sortedArray()
        val pos = (s.size - 1) * p / 100.0
        val lo = pos.toInt()
        val hi = min(lo + 1, s.size - 1)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)
    }

    private fun slope(x: DoubleArray, y: DoubleArray): Double {
        val mx = x.average()
        val my = y.average()
        var num = 0.0
        var den = 0.0
        for (i in x.indices) {
            num += (x[i] - mx) * (y[i] - my)
            den += (x[i] - mx) * (x[i] - mx)
        }
        return if (den == 0.0) 0.0 else num / den
    }
}
