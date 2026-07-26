"""Pure scoring helpers for the three-minute brief psychomotor vigilance task."""

from __future__ import annotations

import statistics
from typing import Iterable, Mapping


PVT_B_DURATION_SECONDS = 180.0
PVT_B_ISI_MIN_SECONDS = 1.0
PVT_B_ISI_MAX_SECONDS = 4.0
PVT_B_FALSE_START_SECONDS = 0.1
PVT_B_LAPSE_SECONDS = 0.355
PVT_B_TIMEOUT_SECONDS = 30.0


def classify_pvt_response(
    response_time_s: float | None,
    *,
    stimulus_present: bool = True,
    false_start_threshold_s: float = PVT_B_FALSE_START_SECONDS,
    lapse_threshold_s: float = PVT_B_LAPSE_SECONDS,
    timed_out: bool = False,
) -> dict[str, object]:
    """Classify one PVT response without depending on the GUI."""

    if timed_out or (stimulus_present and response_time_s is None):
        outcome = "timeout"
        false_start = False
        lapse = True
        responded = False
    elif not stimulus_present or response_time_s < false_start_threshold_s:
        outcome = "false_start"
        false_start = True
        lapse = False
        responded = not stimulus_present or response_time_s is not None
    elif response_time_s >= lapse_threshold_s:
        outcome = "lapse"
        false_start = False
        lapse = True
        responded = True
    else:
        outcome = "hit"
        false_start = False
        lapse = False
        responded = True
    return {
        "responded": responded,
        "stimulus_present": stimulus_present,
        "outcome": outcome,
        "false_start": false_start,
        "lapse": lapse,
        "reaction_time_s": round(response_time_s, 6) if response_time_s is not None else None,
    }


def summarize_pvt_trials(trials: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate PVT-B outcomes while excluding trials truncated at task end."""

    rows = [
        row
        for row in trials
        if row.get("outcome") != "truncated" and not bool(row.get("invalidated"))
    ]
    response_rows = [
        row
        for row in rows
        if row.get("outcome") in {"hit", "lapse"} and row.get("reaction_time_s") is not None
    ]
    response_times = [float(row["reaction_time_s"]) for row in response_rows]
    reciprocal_times = [1.0 / value for value in response_times if value > 0]
    stimulus_count = sum(row.get("stimulus_present") is True for row in rows)
    false_start_count = sum(row.get("outcome") == "false_start" for row in rows)
    lapse_count = sum(row.get("outcome") in {"lapse", "timeout"} for row in rows)
    timeout_count = sum(row.get("outcome") == "timeout" for row in rows)

    return {
        "event_count": len(rows),
        "trial_count": stimulus_count,
        "stimulus_count": stimulus_count,
        "response_count": len(response_rows),
        "hit_count": sum(row.get("outcome") == "hit" for row in rows),
        "lapse_count": lapse_count,
        "timeout_count": timeout_count,
        "false_start_count": false_start_count,
        "mean_reaction_time_s": (
            round(statistics.fmean(response_times), 6) if response_times else None
        ),
        "median_reaction_time_s": (
            round(statistics.median(response_times), 6) if response_times else None
        ),
        "mean_response_speed_per_s": (
            round(statistics.fmean(reciprocal_times), 6) if reciprocal_times else None
        ),
        "lapse_threshold_s": PVT_B_LAPSE_SECONDS,
        "false_start_threshold_s": PVT_B_FALSE_START_SECONDS,
    }
