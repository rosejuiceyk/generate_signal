from __future__ import annotations

import numpy as np

from he3sim.acquisition.trigger import DifferentialThresholdTrigger, ThresholdTrigger, TriggerState


def test_positive_trigger_hold_and_hysteresis_cross_block() -> None:
    trigger = ThresholdTrigger(10.0, 1, 1.0, 0.2, 0.2)
    first, state = trigger.process_block([0.0, 1.1], 0)
    second, state = trigger.process_block([1.2, 0.9, 0.7, 1.1, 1.2], 2, state)

    assert first.size == 0
    np.testing.assert_array_equal(second, [1, 5])
    assert state.next_sample_index == 7


def test_negative_trigger_uses_signed_threshold() -> None:
    trigger = ThresholdTrigger(100.0, -1, -0.5, 0.1, 0.0)
    candidates, _ = trigger.process_block([0.0, -0.6, -0.7, -0.3, -0.6], 0)

    np.testing.assert_array_equal(candidates, [1, 4])


def test_vectorized_trigger_matches_samplewise_reference_across_blocks() -> None:
    trigger = ThresholdTrigger(10.0, 1, 1.0, 0.2, 0.2)
    rng = np.random.default_rng(20260817)
    samples = rng.choice(np.array([0.0, 0.75, 0.9, 1.0, 1.15]), size=401)
    state = TriggerState()
    reference_state = TriggerState()
    observed: list[int] = []
    expected: list[int] = []
    starts = (0, 17, 81, 190, 400, 401)

    for start, stop in zip(starts[:-1], starts[1:], strict=True):
        candidates, state = trigger.process_block(samples[start:stop], start, state)
        observed.extend(candidates.tolist())
        for offset, value in enumerate(samples[start:stop]):
            index = start + offset
            armed = reference_state.armed
            pending_start = reference_state.pending_start_index
            pending_count = reference_state.pending_count
            if not armed:
                if value <= trigger.rearm_level_V:
                    armed = True
            elif pending_count:
                if value >= trigger.aligned_threshold_V:
                    pending_count += 1
                    if pending_count >= trigger.hold_samples:
                        expected.append(pending_start)
                        armed = False
                        pending_start = -1
                        pending_count = 0
                else:
                    pending_start = -1
                    pending_count = 0
            elif value >= trigger.aligned_threshold_V:
                pending_start = index
                pending_count = 1
                if trigger.hold_samples == 1:
                    expected.append(pending_start)
                    armed = False
                    pending_start = -1
                    pending_count = 0
            reference_state = TriggerState(
                next_sample_index=index + 1,
                armed=armed,
                pending_start_index=pending_start,
                pending_count=pending_count,
            )

    np.testing.assert_array_equal(observed, expected)
    assert state == reference_state


def test_differential_trigger_rearms_on_a_second_rising_edge_above_a_tail() -> None:
    trigger = DifferentialThresholdTrigger(10.0, 1, 0.4, 0.1, 0.0, 0.2)
    first, state = trigger.process_block([0.0, 0.0, 0.7, 0.8], 0)
    second, state = trigger.process_block([0.7, 0.6, 1.3, 1.4, 1.2], 4, state)

    np.testing.assert_array_equal(first, [2])
    np.testing.assert_array_equal(second, [6])
    assert state.threshold_state.next_sample_index == 9
