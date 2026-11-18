package com.matan.sleepdetector

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Random
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

class SleepDetectorTest {
    private fun run(minutes: Int, prior: Double?, f: (Double) -> Double): SleepDetector {
        val rnd = Random(1)
        val det = SleepDetector(restPrior = prior)
        var bpm = f(0.0)
        val t0 = 1_700_000_000_000L
        for (i in 0 until minutes * 60) {
            val m = i / 60.0
            if (rnd.nextDouble() < 0.003) bpm += 6 + rnd.nextDouble() * 10
            bpm += 0.1 * (f(m) - bpm) + rnd.nextGaussian() * 1.3 * 0.5
            det.add(t0 + i * 1000L, Math.round(bpm).toDouble())
        }
        return det
    }
    private fun everAsleep(d: SleepDetector) = d.snapshots.any { it.state == SleepState.ASLEEP }

    private val settle = { m: Double -> 52 + 23 * exp(-m / 4) }
    private val startHigh = { m: Double -> if (m < 8) 70.0 else 50 + 20 * exp(-(m - 8) / 3) }
    private val wander = { m: Double -> 51 + 3 * sin(m / 9) }
    private val calm = { _: Double -> 50.0 }
    private val sleep = { m: Double -> if (m < 35) 50.0 else 50 - 6 * min(1.0, (m - 35) / 12) }
    private val startHighThenSleep = { m: Double ->
        if (m < 45) (if (m < 10) 62.0 else 50.0) else 50 - 6 * min(1.0, (m - 45) / 12)
    }

    @Test fun awakeScenariosNeverTrigger_withPrior() {
        for ((n, f) in listOf("settle" to settle, "startHigh" to startHigh, "wander" to wander, "calm" to calm))
            assertEquals(n, false, everAsleep(run(120, 50.0, f)))
    }

    @Test fun awakeScenariosNeverTrigger_coldStart() {
        for ((n, f) in listOf("settle" to settle, "startHigh" to startHigh, "wander" to wander, "calm" to calm))
            assertEquals(n, false, everAsleep(run(120, null, f)))
    }

    @Test fun realSleepIsDetected() {
        assertEquals(true, everAsleep(run(90, 50.0, sleep)))
        assertEquals(true, everAsleep(run(90, null, sleep)))
        assertEquals(true, everAsleep(run(110, 50.0, startHighThenSleep)))
    }

    @Test fun phoneUseBlocksSleep() {
        val det = SleepDetector(restPrior = 50.0)
        val rnd = Random(2)
        val t0 = 1_700_000_000_000L
        for (i in 0 until 90 * 60) {
            val m = i / 60.0
            val hr = if (m < 35) 50.0 else 44.0
            det.lastActivityMs = t0 + i * 1000L   // phone constantly in use
            det.add(t0 + i * 1000L, Math.round(hr + rnd.nextGaussian()).toDouble())
        }
        assertEquals(false, everAsleep(det))
    }
}
