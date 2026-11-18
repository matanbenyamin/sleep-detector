"""
Adaptive sleep-onset detector (no hard-coded BPM threshold).

Idea: sleep onset is a *relative* change in *your* physiology, not an absolute number.
Every few seconds we compare the last few minutes of heart rate with a slowly-adapting,
lagged "awake baseline" learned from this very session, and combine four signals:

  1. DROP       - how far HR is below the awake baseline (relative to the baseline)
  2. STABILITY  - HR plateau: narrow range over the last minutes
  3. SMOOTHNESS - low sample-to-sample jitter (restless / moving HR is jagged)
  4. TREND      - HR has been falling over the last ~10 minutes (onset descent)

Penalties: sudden HR spikes (movement / arousal) and, if available, recent steps.

A hysteresis state machine (AWAKE -> DROWSY -> ASLEEP) with minimum dwell times turns the
smoothed score into a decision, so a single dip or a quiet minute can't trigger it.

The baseline is lagged and frozen once drowsiness starts, so a slow descent is not
absorbed into "normal". Typical personal drop is remembered across sessions in a small
profile file so the detector gets better as data accumulates.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

AWAKE, DROWSY, ASLEEP = "awake", "drowsy", "asleep"

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_DIR, "hr_logs")
PROFILE_PATH = os.path.join(PROJECT_DIR, "sleep_profile.json")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


@dataclass
class Snapshot:
    """One evaluation of the detector; this is what the UI plots."""
    t: dt.datetime
    state: str
    score: float          # smoothed 0..1 "probability of sleep"
    raw_score: float
    hr: float             # robust current HR (median of last ~2 min)
    baseline: float       # adaptive awake baseline
    drop: float
    stability: float
    smoothness: float
    trend: float
    penalty: float
    reason: str = ""


@dataclass
class Config:
    window_now_s: int = 120          # window for "current" HR
    window_range_s: int = 300        # window for plateau stability
    history_s: int = 45 * 60         # kept samples
    floor_window_s: int = 40 * 60    # awake epochs used to learn the resting "floor"
    floor_percentile: float = 20.0   # floor = this percentile of awake 1-min medians
    floor_min_epochs: int = 8        # warm-up (awake minutes) when we already know your resting HR
    floor_min_epochs_cold: int = 20  # ...and when we don't (first run)
    eval_every_s: float = 5.0
    min_data_s: int = 150
    activity_hold_s: int = 300       # phone used within this long => awake
    score_smooth_tau_s: float = 45.0
    drowsy_on: float = 0.42
    asleep_on: float = 0.65
    asleep_off: float = 0.38
    drowsy_dwell_s: int = 60
    asleep_dwell_s: int = 240        # score must stay >= asleep_on this long
    wake_dwell_s: int = 120
    default_drop_frac: float = 0.09  # prior for "full" sleep drop, learned over time


class SleepDetector:
    def __init__(self, cfg: Config = None, profile_path: Optional[str] = PROFILE_PATH):
        self.cfg = cfg or Config()
        self.profile_path = profile_path
        self.samples: Deque[Tuple[float, float]] = deque()   # (epoch_s, bpm)
        self.snapshots: List[Snapshot] = []
        self.state = AWAKE
        self.score = 0.0
        self.baseline: Optional[float] = None
        self._last_eval = 0.0
        self._last_t = None
        self._above_since: Optional[float] = None    # asleep_on dwell
        self._drowsy_since: Optional[float] = None
        self._below_since: Optional[float] = None    # wake dwell
        self.asleep_since: Optional[dt.datetime] = None
        self.recent_steps = -1                       # -1 = unknown
        self.last_activity: Optional[float] = None   # epoch s of last phone use / known movement
        self._epochs: Deque[Tuple[float, float]] = deque()   # (ts, 1-min median HR) while awake
        self._next_epoch: Optional[float] = None
        self.profile = self._load_profile()
        self.drop_ref = self.profile.get("typical_drop_frac", self.cfg.default_drop_frac)
        # Persistent personal awake-resting level (learned across sessions; can be seeded).
        self.rest_prior: Optional[float] = self.profile.get("rest_floor")
        self._last_prior_save = 0.0
        self._learned_this_sleep = False

    # ---------------------------------------------------------------- profile
    def _load_profile(self) -> dict:
        if self.profile_path and os.path.exists(self.profile_path):
            try:
                with open(self.profile_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _update_prior(self, now: float):
        """Slowly track the user's awake resting level (down faster than up)."""
        if len(self._epochs) < self.cfg.floor_min_epochs_cold or self.baseline is None:
            return
        if self.rest_prior is None:
            self.rest_prior = self.baseline
        else:
            a = 0.03 if self.baseline < self.rest_prior else 0.02
            self.rest_prior += a * (self.baseline - self.rest_prior)
        if now - self._last_prior_save > 600:
            self._last_prior_save = now
            self.profile["rest_floor"] = round(self.rest_prior, 2)
            self._save_profile()

    def _save_profile(self):
        if not self.profile_path:
            return
        try:
            with open(self.profile_path, "w") as f:
                json.dump(self.profile, f, indent=2)
        except Exception:
            pass

    def _learn(self, observed_drop_frac: float):
        """Blend an observed confirmed-sleep drop into the personal prior."""
        observed = float(np.clip(observed_drop_frac, 0.04, 0.25))
        old = self.profile.get("typical_drop_frac", self.cfg.default_drop_frac)
        n = self.profile.get("n_sleeps", 0)
        new = old + (observed - old) / min(n + 2, 10)
        self.profile.update(typical_drop_frac=round(new, 4), n_sleeps=n + 1)
        self.drop_ref = new
        self._save_profile()

    # ------------------------------------------------------------------ input
    def add(self, t: dt.datetime, bpm: float) -> Optional[Snapshot]:
        if not (30 <= bpm <= 220):
            return None
        ts = t.timestamp()
        self.samples.append((ts, float(bpm)))
        cutoff = ts - self.cfg.history_s
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        self._last_t = t
        if ts - self._last_eval >= self.cfg.eval_every_s:
            self._last_eval = ts
            return self._evaluate(t, ts)
        return None

    # --------------------------------------------------------------- features
    def _window(self, now: float, seconds: float, lag: float = 0.0) -> np.ndarray:
        lo, hi = now - lag - seconds, now - lag
        return np.array([b for ts, b in self.samples if lo <= ts <= hi], dtype=float)

    def _evaluate(self, t: dt.datetime, now: float) -> Optional[Snapshot]:
        cfg = self.cfg
        if not self.samples or now - self.samples[0][0] < cfg.min_data_s:
            return None
        cur = self._window(now, cfg.window_now_s)
        rng = self._window(now, cfg.window_range_s)
        if len(cur) < 8:
            return None

        hr = float(np.median(cur))

        # ---- awake "floor": low percentile of 1-min medians recorded while AWAKE.
        # A genuine sleep drop must go BELOW the lowest awake resting level, so merely
        # calming down (or an elevated HR at app start) never looks like sleep.
        if self._next_epoch is None:
            self._next_epoch = self.samples[0][0] + 60
        if now >= self._next_epoch:
            self._next_epoch = now + 60
            clearly_awake = self.state == AWAKE and self.score < 0.3 and (
                self.rest_prior is None or hr >= 0.94 * self.rest_prior)
            if clearly_awake:       # never learn the "floor" from drowsy/sleeping minutes
                self._epochs.append((now, hr))
            while self._epochs and self._epochs[0][0] < now - cfg.floor_window_s:
                self._epochs.popleft()
            if self.state == AWAKE and len(self._epochs) >= 1:
                self.baseline = float(np.percentile([e[1] for e in self._epochs], cfg.floor_percentile))
                self._update_prior(now)
        need = cfg.floor_min_epochs if self.rest_prior else cfg.floor_min_epochs_cold
        calibrating = len(self._epochs) < need and self.state == AWAKE and not self.asleep_since
        if self.baseline is None:
            self.baseline = hr
        # Never let an elevated start inflate the reference: use the lower of session and personal level.
        base = min(self.baseline, self.rest_prior) if self.rest_prior else self.baseline

        # ---- 1. drop: relative to baseline, normalised by the personal expected drop
        margin = max(1.5, 0.03 * base)                 # ordinary awake wobble below the floor
        full_drop = max(3.5, self.drop_ref * base)
        drop = _clamp01((base - margin - hr) / full_drop)

        # ---- 2. stability: robust range over 5 min
        if len(rng) >= 20:
            spread = float(np.percentile(rng, 90) - np.percentile(rng, 10))
        else:
            spread = 10.0
        stability = _clamp01((9.0 - spread) / 7.0)            # <=2 bpm ->1, >=9 bpm ->0

        # ---- 3. smoothness: median absolute successive difference
        if len(cur) >= 15:
            jitter = float(np.median(np.abs(np.diff(cur))))
            # Many sensors repeat values at 1 Hz; normalise by how much the HR actually moves
            smoothness = _clamp01((2.2 - jitter) / 2.0)
        else:
            smoothness = 0.0

        # ---- 4. trend: slope over last 10 min (bpm/min); falling = onset
        trend = 0.0
        tw = [(ts, b) for ts, b in self.samples if ts >= now - 600]
        if len(tw) >= 60 and tw[-1][0] - tw[0][0] > 300:
            x = (np.array([p[0] for p in tw]) - now) / 60.0
            y = np.array([p[1] for p in tw])
            slope = float(np.polyfit(x, y, 1)[0])
            trend = _clamp01(-slope / 0.6)   # weak evidence: calming down also falls

        # ---- penalties: spikes (movement/arousal) and steps
        penalty = 0.0
        reason = ""
        recent = self._window(now, 120)
        if len(recent):
            if self.state == AWAKE and recent.max() - hr > max(10.0, 0.14 * base):
                penalty += 0.35
                reason = "HR spike (movement?)"
        if hr > base + 2:
            penalty += 0.3
            reason = reason or "HR above resting level"
        if self.last_activity is not None and now - self.last_activity < cfg.activity_hold_s:
            penalty += 0.7
            reason = "phone in use"
        if self.recent_steps > 0:
            penalty += 0.6
            reason = f"{self.recent_steps} steps"

        raw = (0.60 * drop + 0.20 * stability + 0.15 * smoothness + 0.05 * trend)
        # A plateau with no drop is just resting, never sleep: cap by drop.
        raw = min(raw, 0.25 + 0.9 * drop)
        raw = _clamp01(raw - penalty)
        if calibrating:
            raw, reason = 0.0, f"calibrating ({len(self._epochs)}/{need} min)"

        dtime = now - (self.snapshots[-1].t.timestamp() if self.snapshots else now - cfg.eval_every_s)
        a = 1 - np.exp(-max(dtime, 0.1) / cfg.score_smooth_tau_s)
        self.score += a * (raw - self.score)

        self._step_state(t, now, hr, base)

        snap = Snapshot(t, self.state, self.score, raw, hr, base, drop, stability,
                        smoothness, trend, penalty, reason)
        self.snapshots.append(snap)
        if len(self.snapshots) > 6 * 3600 // max(1, int(cfg.eval_every_s)):
            self.snapshots = self.snapshots[-1000:]
        return snap

    # ------------------------------------------------------------ state logic
    def _step_state(self, t: dt.datetime, now: float, hr: float, base: float):
        cfg, s = self.cfg, self.score
        if self.state == AWAKE:
            if s >= cfg.drowsy_on:
                self._drowsy_since = self._drowsy_since or now
                if now - self._drowsy_since >= cfg.drowsy_dwell_s:
                    self.state = DROWSY
            else:
                self._drowsy_since = None
        if self.state == DROWSY:
            if s >= cfg.asleep_on:
                self._above_since = self._above_since or now
                if now - self._above_since >= cfg.asleep_dwell_s:
                    self.state = ASLEEP
                    self.asleep_since = t - dt.timedelta(seconds=cfg.asleep_dwell_s)
                    self._learned_this_sleep = False
            else:
                self._above_since = None
                if s < cfg.drowsy_on - 0.1:
                    self.state = AWAKE
                    self._drowsy_since = None
        elif self.state == ASLEEP:
            if (not self._learned_this_sleep and self.asleep_since
                    and (t - self.asleep_since).total_seconds() > 600):
                self._learn((base - hr) / base)
                self._learned_this_sleep = True
            if s < cfg.asleep_off:
                self._below_since = self._below_since or now
                if now - self._below_since >= cfg.wake_dwell_s:
                    self.state = AWAKE
                    self._reset_dwell()
            else:
                self._below_since = None

    def _reset_dwell(self):
        self._above_since = self._drowsy_since = self._below_since = None
        self.asleep_since = None

    @property
    def is_asleep(self) -> bool:
        return self.state == ASLEEP


# ------------------------------------------------------------------- logging
class HRLogger:
    """Appends every sample to hr_logs/hr_YYYY-MM-DD.csv so data accumulates for tuning."""

    def __init__(self, directory: str = LOG_DIR):
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)

    def log(self, t: dt.datetime, bpm: float):
        path = os.path.join(self.dir, f"hr_{t:%Y-%m-%d}.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "bpm"])
            w.writerow([t.isoformat(timespec="seconds"), f"{bpm:.0f}"])


def load_csv(path: str) -> List[Tuple[dt.datetime, float]]:
    out = []
    with open(path) as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            try:
                out.append((dt.datetime.fromisoformat(row[0]), float(row[1])))
            except Exception:
                continue
    return out


def synthetic_night(minutes: int = 90, seed: int = 1, start: Optional[dt.datetime] = None,
                    resting: float = 68.0, sleep_drop: float = 0.13, onset_min: int = 35,
                    wake_min: Optional[int] = None) -> List[Tuple[dt.datetime, float]]:
    """1 Hz synthetic data: watching TV (restless), descent, sleep, optional wake-up."""
    rng = np.random.default_rng(seed)
    start = start or dt.datetime(2026, 1, 1, 22, 0, 0)
    out, bpm = [], resting
    for i in range(minutes * 60):
        m = i / 60.0
        target = resting
        if m > onset_min:
            frac = min(1.0, (m - onset_min) / 12.0)
            target = resting * (1 - sleep_drop * frac)
        if wake_min and m > wake_min:
            target = resting + 6
        noise = rng.normal(0, 1.6 if target >= resting - 1 else 0.7)
        if rng.random() < 0.004 and (m < onset_min or (wake_min and m > wake_min)):   # fidgeting
            bpm += rng.uniform(8, 18)
        bpm += 0.08 * (target - bpm) + noise * 0.5
        out.append((start + dt.timedelta(seconds=i), float(round(bpm))))
    return out


def run_offline(data: List[Tuple[dt.datetime, float]], profile_path=None) -> SleepDetector:
    det = SleepDetector(profile_path=profile_path)
    for t, b in data:
        det.add(t, b)
    return det
