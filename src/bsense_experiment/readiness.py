"""Transparent readiness-screening rules for the M6 competition prototype."""

from __future__ import annotations

import math
import re
import statistics
from typing import Iterable, Mapping


READINESS_ALGORITHM_VERSION = "rules_v1_provisional"
READINESS_FALSE_START_SECONDS = 0.1
READINESS_DISCLAIMER = (
    "本结果仅用于当班状态筛查与复测辅助，不是医疗诊断，也不得作为自动化上岗、处罚或永久能力标签。"
)

STATUS_PRESENTATION = {
    "normal": ("正常", "当前未发现达到复测阈值的信号；仍应结合现场安全制度与本人感受。"),
    "retest": ("建议复测", "请离屏安静休息 10–15 分钟，以新的 Run 编号完成一次复测。"),
    "rest": ("建议休息", "复测后风险信号仍较明显，建议暂停高风险任务并按单位安全流程处理。"),
    "unable": ("无法评估", "数据质量或有效试次数不足；请检查佩戴和数据流后，以新的 Run 编号重测。"),
}

_CLOCK_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def sleep_duration_band(hours: float) -> str:
    """Map exact sleep duration to the legacy rule-engine band."""

    if hours < 5:
        return "少于5小时"
    if hours < 6:
        return "5–6小时"
    if hours < 7:
        return "6–7小时"
    if hours < 8:
        return "7–8小时"
    return "8小时及以上"


def normalize_readiness_context(
    values: Mapping[str, object],
    *,
    current_run_id: str,
) -> dict[str, object]:
    """Validate study metadata and derive fields used by the provisional rules."""

    normalized = {
        key: values.get(key)
        for key in (
            "sleep_duration_hours",
            "last_sleep_onset_time",
            "last_wake_time",
            "continuous_awake_hours",
            "caffeine_mg_last_8h",
            "last_caffeine_time",
            "shift_type",
            "kss_score",
            "parent_run_id",
            "rest_duration_minutes",
            "ready_to_test",
        )
    }
    for key, label in (
        ("last_sleep_onset_time", "最近一次入睡时间"),
        ("last_wake_time", "最近一次起床时间"),
    ):
        value = str(values.get(key) or "").strip()
        if not _CLOCK_TIME_PATTERN.fullmatch(value):
            raise ValueError(f"{label}必须使用 24 小时制 HH:MM")
        normalized[key] = value

    caffeine_mg = float(values.get("caffeine_mg_last_8h", 0.0))
    caffeine_time = str(values.get("last_caffeine_time") or "").strip()
    if caffeine_mg > 0 and not _CLOCK_TIME_PATTERN.fullmatch(caffeine_time):
        raise ValueError("摄入咖啡因时必须填写最近摄入时间（HH:MM）")
    if caffeine_time and not _CLOCK_TIME_PATTERN.fullmatch(caffeine_time):
        raise ValueError("最近咖啡因摄入时间必须使用 24 小时制 HH:MM")
    normalized["last_caffeine_time"] = caffeine_time or None

    parent_run_id = str(values.get("parent_run_id") or "").strip()
    rest_duration = values.get("rest_duration_minutes")
    if parent_run_id:
        if not _RUN_ID_PATTERN.fullmatch(parent_run_id):
            raise ValueError("关联首次检测 Run 只能包含字母、数字、下划线和连字符")
        if parent_run_id == current_run_id:
            raise ValueError("关联首次检测 Run 不能与当前 Run 相同")
        if rest_duration is None or float(rest_duration) <= 0:
            raise ValueError("复测必须填写大于 0 的实际休息分钟数")
        normalized["assessment_attempt"] = "复测"
        normalized["parent_run_id"] = parent_run_id
        normalized["rest_duration_minutes"] = float(rest_duration)
    else:
        if rest_duration not in {None, 0, 0.0}:
            raise ValueError("填写休息分钟数时必须同时填写关联首次检测 Run")
        normalized["assessment_attempt"] = "首次"
        normalized["parent_run_id"] = None
        normalized["rest_duration_minutes"] = None

    sleep_hours = float(values["sleep_duration_hours"])
    normalized["sleep_duration_hours"] = sleep_hours
    normalized["sleep_duration_band"] = sleep_duration_band(sleep_hours)
    return normalized


def classify_sart_trial(
    should_respond: bool,
    response_time_s: float | None,
    *,
    false_start_threshold_s: float = READINESS_FALSE_START_SECONDS,
) -> dict[str, object]:
    """Classify one SART/Go-NoGo trial without depending on the GUI."""

    responded = response_time_s is not None
    false_start = bool(responded and response_time_s < false_start_threshold_s)
    if false_start:
        # No-Go 试次上的抢按同时是抑制失败，按 commission 归类；
        # false_start 标志仍保留，供 false_start_rate 统计。
        outcome = "false_start" if should_respond else "commission"
        correct = False
    elif should_respond and responded:
        outcome = "hit"
        correct = True
    elif should_respond:
        outcome = "omission"
        correct = False
    elif responded:
        outcome = "commission"
        correct = False
    else:
        outcome = "correct_rejection"
        correct = True
    return {
        "responded": responded,
        "correct": correct,
        "outcome": outcome,
        "false_start": false_start,
        "reaction_time_s": round(response_time_s, 6) if response_time_s is not None else None,
    }


def summarize_sart_trials(trials: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate task metrics while keeping missing responses distinct from zero latency."""

    rows = list(trials)
    go_trials = sum(bool(row.get("should_respond")) for row in rows)
    no_go_trials = len(rows) - go_trials
    counts = {
        outcome: sum(row.get("outcome") == outcome for row in rows)
        for outcome in ("hit", "omission", "commission", "correct_rejection", "false_start")
    }
    # false_start 以标志位为准：No-Go 抢按的 outcome 归类为 commission，
    # 但仍是抢按，需要计入 false_start_rate。
    false_start_count = sum(
        bool(row.get("false_start", row.get("outcome") == "false_start")) for row in rows
    )
    valid_hit_rts = [
        float(row["reaction_time_s"])
        for row in rows
        if row.get("outcome") == "hit" and row.get("reaction_time_s") is not None
    ]
    median_rt = statistics.median(valid_hit_rts) if valid_hit_rts else None
    rt_cv = (
        statistics.pstdev(valid_hit_rts) / statistics.fmean(valid_hit_rts)
        if len(valid_hit_rts) >= 2 and statistics.fmean(valid_hit_rts) > 0
        else None
    )
    correct_count = counts["hit"] + counts["correct_rejection"]

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "trial_count": len(rows),
        "go_trial_count": go_trials,
        "no_go_trial_count": no_go_trials,
        "hit_count": counts["hit"],
        "omission_count": counts["omission"],
        "commission_count": counts["commission"],
        "correct_rejection_count": counts["correct_rejection"],
        "false_start_count": false_start_count,
        "accuracy": ratio(correct_count, len(rows)),
        "omission_rate": ratio(counts["omission"], go_trials),
        "commission_rate": ratio(counts["commission"], no_go_trials),
        "false_start_rate": ratio(false_start_count, len(rows)),
        "median_reaction_time_s": round(median_rt, 6) if median_rt is not None else None,
        "reaction_time_cv": round(rt_cv, 6) if rt_cv is not None else None,
    }


def _sleep_risk(sleep_duration_band: object) -> tuple[bool, bool]:
    value = str(sleep_duration_band)
    return value in {"少于5小时", "5–6小时"}, value == "少于5小时"


def assess_readiness(
    context: Mapping[str, object],
    trials: Iterable[Mapping[str, object]],
    *,
    expected_trials: int,
    signal_quality_ok: bool,
    signal_quality_issues: Iterable[str] = (),
) -> dict[str, object]:
    """Return one of four auditable states using provisional, conservative rules."""

    metrics = summarize_sart_trials(trials)
    issues = sorted(set(signal_quality_issues))
    minimum_trials = max(1, math.ceil(expected_trials * 0.9))
    reason_codes: list[str] = []

    try:
        kss_score = int(context["kss_score"])
        kss_missing = False
    except (KeyError, TypeError, ValueError):
        kss_score = 0
        kss_missing = True
        reason_codes.append("missing_kss")

    if not signal_quality_ok:
        reason_codes.append("signal_quality_gate_failed")
    if int(metrics["trial_count"]) < minimum_trials:
        reason_codes.append("insufficient_valid_trials")
    if not kss_missing and not 1 <= kss_score <= 9:
        reason_codes.append("invalid_kss")
    if context.get("sleep_duration_band") not in {
        "少于5小时",
        "5–6小时",
        "6–7小时",
        "7–8小时",
        "8小时及以上",
    }:
        reason_codes.append("invalid_sleep_duration_band")
    if context.get("shift_type") not in {"日班", "夜班", "倒班/跨时段", "不适用"}:
        reason_codes.append("invalid_shift_type")
    if context.get("assessment_attempt") not in {"首次", "复测"}:
        reason_codes.append("invalid_assessment_attempt")

    if reason_codes:
        status = "unable"
    else:
        moderate_flags: list[str] = []
        severe_flags: list[str] = []
        omission_rate = float(metrics["omission_rate"] or 0.0)
        commission_rate = float(metrics["commission_rate"] or 0.0)
        false_start_rate = float(metrics["false_start_rate"] or 0.0)
        rt_cv = float(metrics["reaction_time_cv"] or 0.0)
        median_rt = float(metrics["median_reaction_time_s"] or 0.0)
        accuracy = float(metrics["accuracy"] or 0.0)

        if accuracy < 0.80:
            moderate_flags.append("low_accuracy")
        if omission_rate >= 0.15:
            moderate_flags.append("high_omission_rate")
        if commission_rate >= 0.30:
            moderate_flags.append("high_commission_rate")
        if false_start_rate >= 0.05:
            moderate_flags.append("high_false_start_rate")
        if rt_cv >= 0.45:
            moderate_flags.append("unstable_reaction_time")
        if median_rt >= 0.65:
            moderate_flags.append("slow_median_reaction_time")
        if omission_rate >= 0.25:
            severe_flags.append("severe_omission_rate")
        if commission_rate >= 0.45:
            severe_flags.append("severe_commission_rate")
        if false_start_rate >= 0.15:
            severe_flags.append("severe_false_start_rate")
        if accuracy < 0.65:
            severe_flags.append("severe_low_accuracy")

        low_sleep, very_low_sleep = _sleep_risk(context.get("sleep_duration_band"))
        if kss_score >= 7:
            moderate_flags.append("high_kss")
        if low_sleep:
            moderate_flags.append("short_sleep")
        high_risk = (
            kss_score >= 8
            or bool(severe_flags)
            or (kss_score >= 7 and len(set(moderate_flags) - {"high_kss"}) >= 1)
            or (very_low_sleep and len(set(moderate_flags) - {"short_sleep"}) >= 1)
        )
        reason_codes.extend(dict.fromkeys([*moderate_flags, *severe_flags]))
        is_retest = context.get("assessment_attempt") == "复测"
        if reason_codes and is_retest and high_risk:
            status = "rest"
        elif reason_codes:
            status = "retest"
        else:
            status = "normal"

    label, recommendation = STATUS_PRESENTATION[status]
    return {
        "status": status,
        "label": label,
        "recommendation": recommendation,
        "reason_codes": reason_codes,
        "metrics": metrics,
        "signal_quality_ok": signal_quality_ok,
        "signal_quality_issues": issues,
        "expected_trials": expected_trials,
        "minimum_required_trials": minimum_trials,
        "algorithm_version": READINESS_ALGORITHM_VERSION,
        "validated_for_employment_decisions": False,
        "disclaimer": READINESS_DISCLAIMER,
    }
