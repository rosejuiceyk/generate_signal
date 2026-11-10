"""Stateful positive/negative threshold trigger with hysteresis and hold time."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class TriggerState:
    """Cross-block trigger state in global sample coordinates."""

    next_sample_index: int = 0
    armed: bool = True
    pending_start_index: int = -1
    pending_count: int = 0


@dataclass(frozen=True, slots=True)
class DifferentialTriggerState:
    """Cross-block state for a finite-difference pulse-onset trigger.

    ``tail_samples_V`` supplies the delayed and optional smoothing-window
    samples required at the first sample of the next block.  It is deliberately kept separate from
    :class:`TriggerState` because the differentiated trace is an observation
    transform, rather than an additional dead-time or truth-event operation.
    """

    threshold_state: TriggerState
    tail_samples_V: npt.NDArray[np.float64]


class ThresholdTrigger:
    """Detect one candidate per hysteretic threshold excursion."""

    def __init__(
        self,
        sample_rate_hz: float,
        polarity: int,
        threshold_V: float,
        hysteresis_V: float,
        min_hold_s: float,
    ) -> None:
        """Validate and precompute sample-domain trigger parameters."""
        if not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be finite and positive")
        if polarity not in {-1, 1}:
            raise ValueError("trigger polarity must be -1 or 1")
        values = (threshold_V, hysteresis_V, min_hold_s)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("trigger parameters must be finite")
        aligned_threshold = polarity * threshold_V
        if aligned_threshold <= 0.0:
            raise ValueError("threshold sign must match trigger polarity")
        if hysteresis_V < 0.0 or hysteresis_V >= aligned_threshold:
            raise ValueError("hysteresis_V must be non-negative and below threshold magnitude")
        if min_hold_s < 0.0:
            raise ValueError("min_hold_s must be non-negative")
        self.sample_rate_hz = sample_rate_hz
        self.polarity = polarity
        self.aligned_threshold_V = aligned_threshold
        self.rearm_level_V = aligned_threshold - hysteresis_V
        self.hold_samples = max(1, math.ceil(min_hold_s * sample_rate_hz))

    def process_block(
        self,
        samples_V: npt.ArrayLike,
        sample_start: int,
        state: TriggerState | None = None,
    ) -> tuple[npt.NDArray[np.int64], TriggerState]:
        """Process a contiguous block and return global candidate sample indices."""
        samples = np.asarray(samples_V, dtype=np.float64)
        if samples.ndim != 1 or np.any(~np.isfinite(samples)):
            raise ValueError("trigger samples must be a finite vector")
        current = state or TriggerState()
        if sample_start != current.next_sample_index:
            raise ValueError("trigger blocks must be contiguous and ordered")
        if samples.size == 0:
            return np.empty(0, dtype=np.int64), current
        aligned = self.polarity * samples
        armed = current.armed
        pending_start = current.pending_start_index
        pending_count = current.pending_count
        above = aligned >= self.aligned_threshold_V
        starts = np.flatnonzero(above & np.concatenate(([True], ~above[:-1])))
        ends = np.flatnonzero(above & np.concatenate((~above[1:], [True]))) + 1
        rearm = np.flatnonzero(aligned <= self.rearm_level_V) + sample_start

        candidate_starts: list[int] = []
        for index, (start, end) in enumerate(zip(starts, ends, strict=True)):
            run_start = sample_start + int(start)
            run_length = int(end - start)
            if index == 0 and pending_count and start == 0:
                run_start = pending_start
                run_length += pending_count
            if run_length >= self.hold_samples:
                candidate_starts.append(run_start)

        candidates: list[int] = []
        unarmed_after = sample_start - 1
        for candidate in candidate_starts:
            if not armed:
                rearm_count = int(np.searchsorted(rearm, candidate, side="right"))
                if rearm_count == 0 or rearm[rearm_count - 1] <= unarmed_after:
                    continue
                armed = True
            candidates.append(candidate)
            armed = False
            unarmed_after = candidate

        if not armed and rearm.size:
            last_rearm = int(rearm[-1])
            if last_rearm > unarmed_after:
                armed = True

        pending_start = -1
        pending_count = 0
        if armed and starts.size and ends[-1] == samples.size:
            start_index = int(starts[-1])
            run_start = int(sample_start + start_index)
            run_length = int(samples.size - start_index)
            if start_index == 0 and current.pending_count:
                run_start = current.pending_start_index
                run_length += current.pending_count
            if run_length < self.hold_samples:
                pending_start = run_start
                pending_count = run_length
        next_state = TriggerState(
            next_sample_index=sample_start + samples.size,
            armed=armed,
            pending_start_index=pending_start,
            pending_count=pending_count,
        )
        return np.asarray(candidates, dtype=np.int64), next_state


class DifferentialThresholdTrigger:
    """Detect positive pulse onsets after a delayed finite difference.

    A conventional threshold remains unarmed while the long tail of a pulse
    stays above threshold, which can fuse correlated close arrivals into a
    single observation.  This trigger applies ``x[t] - x[t-delay]`` before the
    same hysteretic threshold logic, thereby responding to a new rising edge
    while suppressing a slowly decaying baseline.  It is an explicitly
    parameterized synthetic-observation algorithm, not a detector-calibration
    model.
    """

    def __init__(
        self,
        sample_rate_hz: float,
        polarity: int,
        derivative_threshold_V: float,
        hysteresis_V: float,
        min_hold_s: float,
        delay_s: float,
        smoothing_s: float = 0.0,
    ) -> None:
        if not math.isfinite(delay_s) or delay_s <= 0.0:
            raise ValueError("delay_s must be finite and positive")
        if not math.isfinite(smoothing_s) or smoothing_s < 0.0:
            raise ValueError("smoothing_s must be finite and non-negative")
        self.delay_samples = max(1, math.ceil(delay_s * sample_rate_hz))
        self.smoothing_samples = max(1, math.ceil(smoothing_s * sample_rate_hz))
        self.tail_length = self.delay_samples + self.smoothing_samples
        self._threshold = ThresholdTrigger(
            sample_rate_hz,
            polarity,
            derivative_threshold_V,
            hysteresis_V,
            min_hold_s,
        )

    def process_block(
        self,
        samples_V: npt.ArrayLike,
        sample_start: int,
        state: DifferentialTriggerState | None = None,
    ) -> tuple[npt.NDArray[np.int64], DifferentialTriggerState]:
        """Process contiguous waveform samples and return onset candidates."""

        samples = np.asarray(samples_V, dtype=np.float64)
        if samples.ndim != 1 or np.any(~np.isfinite(samples)):
            raise ValueError("trigger samples must be a finite vector")
        if state is None:
            threshold_state = TriggerState(next_sample_index=sample_start)
            tail = np.zeros(self.tail_length, dtype=np.float64)
        else:
            threshold_state = state.threshold_state
            tail = np.asarray(state.tail_samples_V, dtype=np.float64)
            if tail.shape != (self.tail_length,):
                raise ValueError("differential trigger tail has the wrong shape")
        extended = np.concatenate((tail, samples))
        sums = np.concatenate(([0.0], np.cumsum(extended, dtype=np.float64)))
        ends = np.arange(tail.size, tail.size + samples.size, dtype=np.int64)
        width = self.smoothing_samples
        current = (sums[ends + 1] - sums[ends + 1 - width]) / width
        delayed_ends = ends - self.delay_samples
        delayed = (sums[delayed_ends + 1] - sums[delayed_ends + 1 - width]) / width
        difference = current - delayed
        candidates, next_threshold_state = self._threshold.process_block(
            difference, sample_start, threshold_state
        )
        next_tail = extended[-self.tail_length :].copy()
        return candidates, DifferentialTriggerState(next_threshold_state, next_tail)
