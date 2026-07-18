"""Pure protocol definitions for the BSense-R acquisition modules."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal


AdvanceMode = Literal["timed", "operator", "form"]


@dataclass(frozen=True)
class InputField:
    key: str
    label: str
    kind: Literal["rating", "choice", "boolean"]
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    text: str
    detail: str
    duration: float
    event: str | None = None
    code: int | None = None
    block: str | None = None
    trial: int | None = None
    advance: AdvanceMode = "timed"
    completion_event: str | None = None
    completion_code: int | None = None
    response_key: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    fields: tuple[InputField, ...] = ()
    visual: str | None = None
    start_sound: str | None = None
    warning_sound: str | None = None
    warning_at: float | None = None
    end_sound: str | None = None


@dataclass(frozen=True)
class ProtocolInfo:
    task: str
    title: str
    description: str
    priority: str


PROTOCOLS = (
    ProtocolInfo("deviceqc", "设备 QC", "验证信号、同步与常见伪迹（正式采集前推荐）", "联调"),
    ProtocolInfo("m0_baseline", "M0 准备与基线", "设备检查、闭眼/睁眼静息及基线问卷", "必做"),
    ProtocolInfo("m1_mi", "M1 运动想象（探索）", "左手、右手、空闲三分类，共 4 Run", "探索"),
    ProtocolInfo("m2_nback", "M2 认知负荷", "0/1/2-back，每级 3 Block", "必做"),
    ProtocolInfo("m3a_safety", "M3A 安全动作", "坐姿下正常与异常动作采集", "重要"),
    ProtocolInfo("m3b_fatigue", "M3B 疲劳诱导", "分段持续 1-back，每 2 分钟评分", "重要"),
    ProtocolInfo("m4a_intent", "M4A 提示后意图", "有提示的拿取意图与无意图二分类", "探索"),
    ProtocolInfo("m4b_target", "M4B 目标注意（探索）", "三物体串行高亮中的目标注意", "探索"),
    ProtocolInfo("m5_debrief", "M5 结束问卷", "整体体验、困倦、舒适度与不适记录", "建议"),
)

PROTOCOL_BY_TASK = {protocol.task: protocol for protocol in PROTOCOLS}


def _shuffle_without_long_streaks(
    items: list[tuple[str, int, str, str]],
    rng: random.Random,
    max_streak: int = 2,
) -> list[tuple[str, int, str, str]]:
    for _attempt in range(200):
        shuffled = items.copy()
        rng.shuffle(shuffled)
        if all(
            not all(shuffled[index - offset][0] == shuffled[index][0] for offset in range(1, max_streak + 1))
            for index in range(max_streak, len(shuffled))
        ):
            return shuffled
    raise RuntimeError("无法生成满足连续条件限制的随机序列")


def _experiment_bounds(task: str, body: list[Step]) -> list[Step]:
    return [
        Step(
            "实验即将开始",
            PROTOCOL_BY_TASK[task].title,
            2.0,
            "experiment_start",
            10,
            metadata={"protocol": task},
            start_sound="start",
        ),
        *body,
        Step(
            "模块完成",
            "请保持放松，正在结束本模块录制",
            1.0,
            "experiment_end",
            11,
            end_sound="complete",
        ),
    ]


def build_deviceqc_plan(short: bool = False, **_: object) -> list[Step]:
    rest_seconds = 10.0 if short else 60.0
    repetitions = 1 if short else 5
    prepare_seconds = 1.0 if short else 2.0
    cue_seconds = 2.0
    recovery_seconds = 2.0 if short else 3.0

    plan = [
        Step(
            "实验即将开始",
            "保持坐姿，双脚平放，尽量放松",
            2.0,
            "experiment_start",
            10,
            start_sound="start",
        ),
        Step("睁眼静息", "注视屏幕中央，保持头部不动", rest_seconds, "rest_open_start", 100),
        Step("睁眼静息结束", "继续保持不动", 0.5, "rest_open_end", 101),
        Step(
            "闭眼静息",
            "轻轻闭眼，保持清醒和头部不动",
            rest_seconds,
            "rest_closed_start",
            110,
            warning_sound="ending_soon",
            warning_at=5.0,
            end_sound="open_eyes",
        ),
        Step("闭眼静息结束", "请睁开眼睛", 1.0, "rest_closed_end", 111),
    ]

    actions = [
        ("blink", 120, "自然眨眼 1 次", "不要用力挤眼"),
        ("jaw_clench", 130, "轻咬后放松", "咬紧约 1 秒，然后完全放松"),
        ("head_left", 201, "缓慢左转头并回中", "只转到舒适位置，不要转动身体"),
        ("head_right", 202, "缓慢右转头并回中", "只转到舒适位置，不要转动身体"),
        ("head_nod", 203, "缓慢点头并回中", "完成一次点头后回到正中"),
        ("head_cancel", 204, "快速左右摇头并回中", "幅度适中，完成后回到正中"),
    ]
    for block_name, code, cue_text, cue_detail in actions:
        plan.append(
            Step(
                f"准备：{cue_text}",
                f"本组共 {repetitions} 次",
                1.0,
                f"block_start_{block_name}",
                20,
                block_name,
            )
        )
        for trial in range(1, repetitions + 1):
            plan.extend(
                [
                    Step(
                        "准备",
                        f"{cue_text}，第 {trial}/{repetitions} 次",
                        prepare_seconds,
                        block=block_name,
                        trial=trial,
                    ),
                    Step(cue_text, cue_detail, cue_seconds, block_name, code, block_name, trial),
                    Step(
                        "恢复正中并静止",
                        "放松，等待下一次提示",
                        recovery_seconds,
                        block=block_name,
                        trial=trial,
                    ),
                ]
            )
        plan.append(
            Step(
                f"{cue_text}组结束",
                "保持正中姿势",
                0.5,
                f"block_end_{block_name}",
                21,
                block_name,
            )
        )

    plan.extend(
        [
            Step("结束睁眼静息", "注视屏幕中央，保持头部不动", rest_seconds, "rest_open_final_start", 100),
            Step("结束静息完成", "继续保持不动", 0.5, "rest_open_final_end", 101),
        Step("实验完成", "请等待数据文件保存完成", 1.0, "experiment_end", 11, end_sound="complete"),
        ]
    )
    return plan


def build_m0_plan(short: bool = False, **_: object) -> list[Step]:
    closed = 3.0 if short else 180.0
    opened = 2.0 if short else 120.0
    settle = 1.0 if short else 30.0
    questionnaire = (
        InputField("fatigue", "当前疲劳感（1-10）", "rating", 1, 10),
        InputField("sleep_quality", "睡眠质量（1-10）", "rating", 1, 10),
        InputField("neuroactive_medication", "是否服用影响神经系统的药物", "boolean"),
    )
    body = [
        Step(
            "设备与安全检查",
            "确认 EEG/fNIRS 信号质量、完成 Motion 校准，并确认被试坐姿安全",
            0.0,
            "baseline_preparation_start",
            400,
            advance="operator",
            completion_event="baseline_preparation_complete",
            completion_code=401,
        ),
        Step(
            "自然呼吸稳定",
            "睁眼注视中央，保持自然呼吸；不要刻意深呼吸",
            settle,
            "baseline_settle_start",
            402,
        ),
        Step("稳定段结束", "继续保持不动", 0.1, "baseline_settle_end", 403),
        Step(
            "闭眼静息",
            "轻轻闭眼、保持清醒，不刻意思考",
            closed,
            "rest_closed_start",
            110,
            warning_sound="ending_soon",
            warning_at=1.0 if short else 5.0,
            end_sound="open_eyes",
        ),
        Step("闭眼静息结束", "请缓慢睁眼", 0.5, "rest_closed_end", 111),
        Step("睁眼静息", "注视屏幕中央十字，保持头部不动", opened, "rest_open_start", 100),
        Step("睁眼静息结束", "继续保持放松", 0.5, "rest_open_end", 101),
        Step(
            "基线问卷",
            "由实验员询问并录入，不记录药物名称等直接身份信息",
            0.0,
            "baseline_questionnaire_start",
            410,
            advance="form",
            completion_event="baseline_questionnaire",
            completion_code=411,
            fields=questionnaire,
        ),
    ]
    return _experiment_bounds("m0_baseline", body)


def build_m1_plan(
    short: bool = False,
    older_adult: bool = False,
    seed: int = 0,
    **_: object,
) -> list[Step]:
    rng = random.Random(seed)
    runs = 1 if short else 4
    class_repetitions = 1 if short else 10
    imagine_seconds = 1.0 if short else (5.0 if older_adult else 4.0)
    rest_seconds = 1.0 if short else (4.0 if older_adult else 2.5)
    run_rest = 1.0 if short else (300.0 if older_adult else 180.0)
    conditions = (
        ("mi_left", 301, "←", "想象左手持续握拳/松开"),
        ("mi_right", 302, "→", "想象右手持续握拳/松开"),
        ("mi_idle", 300, "○", "放空，不想任何动作"),
    )
    run_ratings = (
        InputField("left_imagery_success", "本 Run 左手想象成功度（1-5）", "rating", 1, 5),
        InputField("right_imagery_success", "本 Run 右手想象成功度（1-5）", "rating", 1, 5),
        InputField("idle_stability", "本 Run 空闲态保持程度（1-5）", "rating", 1, 5),
        InputField("imagery_effort", "本 Run 总体主观努力度（1-5）", "rating", 1, 5),
    )
    body: list[Step] = []
    global_trial = 0
    for run_number in range(1, runs + 1):
        trials = _shuffle_without_long_streaks(
            [condition for condition in conditions for _ in range(class_repetitions)],
            rng,
        )
        body.append(
            Step(
                f"Run {run_number} 准备",
                f"本 Run 共 {len(trials)} 个随机试次",
                2.0 if not short else 0.5,
                "block_start",
                20,
                f"run_{run_number}",
                metadata={"run_in_task": run_number},
            )
        )
        for trial_in_run, (event, code, cue, detail) in enumerate(trials, start=1):
            global_trial += 1
            metadata = {
                "run_in_task": run_number,
                "trial_in_run": trial_in_run,
                "condition": event,
                "paradigm": "cued_motor_imagery_exploratory",
            }
            body.extend(
                [
                    Step("+", "注视中央十字", 0.5 if short else 2.0, block=f"run_{run_number}", trial=global_trial),
                    Step(
                        cue,
                        "准备执行提示条件",
                        0.5 if short else 1.0,
                        "mi_cue",
                        305,
                        f"run_{run_number}",
                        global_trial,
                        metadata=metadata,
                    ),
                    Step(
                        cue,
                        detail,
                        imagine_seconds,
                        event,
                        code,
                        f"run_{run_number}",
                        global_trial,
                        metadata=metadata,
                    ),
                    Step(
                        "休息",
                        "放松并保持不动",
                        rest_seconds,
                        "mi_trial_end",
                        306,
                        f"run_{run_number}",
                        global_trial,
                        metadata=metadata,
                    ),
                ]
            )
        body.append(Step(f"Run {run_number} 完成", "本组采集结束", 0.5, "block_end", 21, f"run_{run_number}"))
        body.append(
            Step(
                f"Run {run_number} 主观评分",
                "请按整个 Run 的总体体验评分，避免逐试次按键污染后续血氧响应",
                0.0,
                "mi_run_rating_start",
                303,
                f"run_{run_number}",
                advance="form",
                completion_event="mi_run_rating",
                completion_code=304,
                metadata={"run_in_task": run_number, "rating_scope": "run"},
                fields=run_ratings,
            )
        )
        if run_number < runs:
            body.append(
                Step(
                    "组间休息",
                    "可放松身体，但请勿触碰传感器",
                    run_rest,
                    "inter_run_rest",
                    310,
                    f"run_{run_number}",
                    warning_sound="ending_soon" if not short else None,
                    warning_at=10.0 if not short else None,
                    end_sound="start",
                )
            )
    return _experiment_bounds("m1_mi", body)


def _nback_sequence(level: int, count: int, rng: random.Random) -> list[tuple[str, bool]]:
    letters = "BCDFGHJKLMNPQRSTVWXYZ"
    sequence: list[str] = []
    eligible_positions = list(range(level, count))
    target_count = min(len(eligible_positions), max(1, round(count * 0.25)))
    target_positions = set(rng.sample(eligible_positions, target_count))
    targets: list[bool] = []
    for index in range(count):
        should_target = index in target_positions
        if level == 0:
            letter = "X" if should_target else rng.choice(letters)
        elif should_target:
            letter = sequence[index - level]
        else:
            forbidden = sequence[index - level] if index >= level else None
            candidates = [candidate for candidate in letters if candidate != forbidden]
            letter = rng.choice(candidates)
        sequence.append(letter)
        targets.append(should_target)
    return list(zip(sequence, targets, strict=True))


def _nback_stimulus_steps(
    level: int,
    count: int,
    rng: random.Random,
    block_name: str,
    duration: float,
    *,
    sequence: list[tuple[str, bool]] | None = None,
    position_offset: int = 0,
    extra_metadata: dict[str, object] | None = None,
) -> list[Step]:
    code = {0: 421, 1: 431, 2: 441}[level]
    steps: list[Step] = []
    items = sequence if sequence is not None else _nback_sequence(level, count, rng)
    for position_in_block, (letter, is_target) in enumerate(items, start=1):
        position = position_offset + position_in_block
        steps.append(
            Step(
                letter,
                "满足目标条件时按空格键",
                duration,
                "nback_stimulus",
                code,
                block_name,
                position,
                response_key="space",
                metadata={
                    "level": level,
                    "stimulus": letter,
                    "is_target": is_target,
                    "position": position,
                    "position_in_block": position_in_block,
                    **(extra_metadata or {}),
                },
            )
        )
    return steps


def build_m2_plan(
    short: bool = False,
    seed: int = 0,
    nback_order: str = "ascending",
    **_: object,
) -> list[Step]:
    rng = random.Random(seed)
    blocks_per_level = 1 if short else 3
    stimulus_count = 8 if short else 60
    stimulus_duration = 0.5 if short else 2.0
    instruction_duration = 1.0 if short else 15.0
    rest_duration = 1.0 if short else 60.0
    ratings = (
        InputField("fatigue", "主观疲劳（1-10）", "rating", 1, 10),
        InputField("difficulty", "主观难度（1-10）", "rating", 1, 10),
    )
    instructions = {
        0: "看到 X 时按空格键",
        1: "当前字母与上一个相同时按空格键",
        2: "当前字母与前两个相同时按空格键",
    }
    if nback_order == "ascending":
        levels = (0, 1, 2)
    elif nback_order == "counterbalanced":
        latin_square = ((0, 1, 2), (1, 2, 0), (2, 0, 1))
        levels = latin_square[seed % len(latin_square)]
    else:
        raise ValueError("N-Back 顺序必须是 ascending 或 counterbalanced")
    body: list[Step] = []
    for order_position, level in enumerate(levels, start=1):
        for block_number in range(1, blocks_per_level + 1):
            block_name = f"{level}back_{block_number}"
            body.append(
                Step(
                    f"{level}-back · Block {block_number}",
                    instructions[level],
                    instruction_duration,
                    "block_start",
                    {0: 420, 1: 430, 2: 440}[level],
                    block_name,
                    metadata={
                        "level": level,
                        "block_in_level": block_number,
                        "order_position": order_position,
                        "nback_order": nback_order,
                    },
                )
            )
            body.extend(_nback_stimulus_steps(level, stimulus_count, rng, block_name, stimulus_duration))
            body.append(
                Step(
                    "任务段结束",
                    "请停止作答，准备评分",
                    0.1,
                    "nback_task_end",
                    453,
                    block_name,
                    metadata={"level": level, "block_in_level": block_number},
                )
            )
            body.append(
                Step(
                    "区块评分",
                    "请报告刚完成区块的疲劳与难度",
                    0.0,
                    "block_rating_start",
                    450,
                    block_name,
                    advance="form",
                    completion_event="block_rating",
                    completion_code=451,
                    metadata={
                        "level": level,
                        "block_in_level": block_number,
                        "order_position": order_position,
                        "nback_order": nback_order,
                    },
                    fields=ratings,
                )
            )
            body.append(
                Step(
                    "休息",
                    "注视中央并保持自然呼吸，准备下一 Block",
                    rest_duration,
                    "block_rest",
                    452,
                    block_name,
                    warning_sound="ending_soon" if not short else None,
                    warning_at=5.0 if not short else None,
                    end_sound="start",
                )
            )
            body.append(
                Step(
                    "恢复段结束",
                    "准备进入下一步骤",
                    0.1,
                    "block_rest_end",
                    454,
                    block_name,
                    metadata={"level": level, "block_in_level": block_number},
                )
            )
            body.append(Step("区块完成", "", 0.1, "block_end", 21, block_name))
    return _experiment_bounds("m2_nback", body)


def build_m3a_plan(short: bool = False, **_: object) -> list[Step]:
    repetitions = 1 if short else 5
    body = [
        Step(
            "安全确认",
            "被试坐在有靠背的稳定座椅上；实验员全程在旁保护。任何不适立即中止",
            0.0,
            "safety_check_start",
            500,
            advance="operator",
            completion_event="safety_check_complete",
            completion_code=501,
        ),
        Step(
            "正常坐姿静止",
            "保持自然坐姿",
            3.0 if short else 30.0,
            "motion_sit_baseline",
            510,
            "sit_baseline",
            1,
            metadata={"action": "sit_still", "artifact_expectation": "none_expected"},
        ),
    ]
    actions = (
        ("motion_nod", 511, "缓慢点头并回中", repetitions),
        ("motion_shake", 512, "缓慢左右摇头并回中", repetitions),
        ("motion_forward", 513, "突然前倾并在控制下回中", repetitions),
        ("motion_side_left", 514, "突然向左侧倾并在控制下回中", repetitions),
        ("motion_side_right", 515, "突然向右侧倾并在控制下回中", repetitions),
        ("motion_stand", 516, "在实验员保护下快速起身", repetitions),
    )
    for event, code, cue, count in actions:
        body.append(Step(f"准备：{cue}", f"本组 {count} 次", 1.0, "block_start", 20, event))
        for trial in range(1, count + 1):
            body.append(
                Step(
                    cue,
                    f"第 {trial}/{count} 次",
                    2.0 if short else 4.0,
                    event,
                    code,
                    event,
                    trial,
                    metadata={
                        "action": event.removeprefix("motion_"),
                        "artifact_expectation": "motion_expected",
                        "quality_status": "requires_offline_review",
                    },
                )
            )
            body.append(Step("恢复并静止", "等待下一提示", 1.0 if short else 3.0, block=event, trial=trial))
        body.append(Step("本组完成", "", 0.2, "block_end", 21, event))
    body.append(
        Step(
            "正常行走 1 圈",
            "实验员陪同；完成后点击继续",
            0.0,
            "motion_walk_start",
            517,
            "walk_baseline",
            1,
            advance="operator",
            completion_event="motion_walk_end",
            completion_code=518,
            metadata={
                "action": "walk",
                "artifact_expectation": "motion_expected",
                "quality_status": "requires_offline_review",
            },
        )
    )
    return _experiment_bounds("m3a_safety", body)


def build_m3b_plan(short: bool = False, seed: int = 0, **_: object) -> list[Step]:
    rng = random.Random(seed)
    segment_count = 2 if short else 5
    stimuli_per_segment = 4 if short else 60
    stimulus_duration = 0.5 if short else 2.0
    fatigue_fields = (
        InputField("kss_score", "当前困倦程度 KSS（1=非常清醒，9=非常困倦）", "rating", 1, 9),
        InputField("mental_fatigue_score", "当前精神疲劳（1=无，5=很强）", "rating", 1, 5),
    )
    body: list[Step] = [
        Step(
            "分段持续 1-back 即将开始",
            "相同字母连续出现时按空格；每段内不休息，评分后重置序列",
            1.0 if short else 15.0,
            "fatigue_task_start",
            520,
        )
    ]
    for segment in range(1, segment_count + 1):
        block_name = f"fatigue_segment_{segment}"
        start = (segment - 1) * stimuli_per_segment
        segment_sequence = _nback_sequence(1, stimuli_per_segment, rng)
        body.append(
            Step(
                f"第 {segment}/{segment_count} 段",
                "连续 1-back，目标出现时按空格",
                0.1,
                "fatigue_segment_start",
                523,
                block_name,
                metadata={
                    "segment": segment,
                    "elapsed_minutes_start": (segment - 1) * 2,
                    "sequence_reset": True,
                },
            )
        )
        body.extend(
            _nback_stimulus_steps(
                1,
                stimuli_per_segment,
                rng,
                block_name,
                stimulus_duration,
                sequence=segment_sequence,
                position_offset=start,
                extra_metadata={"segment": segment, "sequence_reset": True},
            )
        )
        body.append(
            Step(
                "本段结束",
                "请立即完成 KSS 评分",
                0.1,
                "fatigue_segment_end",
                524,
                block_name,
                metadata={"segment": segment, "elapsed_minutes": segment * 2},
            )
        )
        body.append(
            Step(
                f"第 {segment * 2} 分钟疲劳评分",
                "评分后立即继续任务",
                0.0,
                "fatigue_rating_start",
                521,
                block_name,
                advance="form",
                completion_event="fatigue_rating",
                completion_code=522,
                metadata={"segment": segment, "elapsed_minutes": segment * 2},
                fields=fatigue_fields,
            )
        )
    body.extend(
        [
            Step(
                "任务后恢复",
                "睁眼注视中央，保持自然呼吸和身体静止",
                2.0 if short else 30.0,
                "fatigue_recovery_start",
                525,
            ),
            Step("恢复段结束", "继续保持放松", 0.1, "fatigue_recovery_end", 526),
        ]
    )
    return _experiment_bounds("m3b_fatigue", body)


def build_m4a_plan(short: bool = False, seed: int = 0, **_: object) -> list[Step]:
    rng = random.Random(seed)
    trials_per_condition = 2 if short else 40
    objects = ("水杯", "药瓶", "手机")
    conditions: list[tuple[bool, str, int, str]] = []
    for has_intent, label, code in ((True, "有意图", 601), (False, "无意图", 600)):
        cycles, remainder = divmod(trials_per_condition, len(objects))
        condition_objects = list(objects) * cycles + rng.sample(objects, remainder)
        conditions.extend((has_intent, label, code, object_name) for object_name in condition_objects)
    rng.shuffle(conditions)
    body: list[Step] = []
    for trial, (has_intent, label, code, object_name) in enumerate(conditions, start=1):
        detail = "想象用右手拿取该物体" if has_intent else "保持空闲，不想任何动作"
        metadata = {
            "has_intent": has_intent,
            "object": object_name,
            "condition": label,
            "paradigm": "externally_cued_intent",
        }
        body.extend(
            [
                Step("+", "注视中央", 0.5 if short else 1.0, block="intent", trial=trial),
                Step(
                    object_name,
                    label,
                    0.5 if short else 1.0,
                    "intent_cue",
                    602,
                    "intent",
                    trial,
                    metadata=metadata,
                    visual=object_name,
                ),
                Step(
                    object_name,
                    detail,
                    1.0 if short else 4.0,
                    "intent_present" if has_intent else "intent_absent",
                    code,
                    "intent",
                    trial,
                    metadata=metadata,
                    visual=object_name,
                ),
                Step(
                    "休息",
                    "",
                    0.5 if short else 1.0,
                    "intent_trial_end",
                    605,
                    "intent",
                    trial,
                    metadata=metadata,
                ),
            ]
        )
    body.append(
        Step(
            "意图任务评分",
            "请按整个模块的总体体验评分",
            0.0,
            "intent_rating_start",
            603,
            "intent",
            advance="form",
            completion_event="intent_rating",
            completion_code=604,
            fields=(
                InputField("intent_strength", "有意图试次的意图强度（1-5）", "rating", 1, 5),
                InputField("intent_difficulty", "区分有/无意图的难度（1-5）", "rating", 1, 5),
            ),
        )
    )
    return _experiment_bounds("m4a_intent", body)


def build_m4b_plan(
    short: bool = False,
    seed: int = 0,
    target_object: str = "水杯",
    **_: object,
) -> list[Step]:
    if target_object not in {"水杯", "药瓶", "手机"}:
        raise ValueError("目标物体必须是水杯、药瓶或手机")
    rng = random.Random(seed)
    rounds = 2 if short else 60
    body: list[Step] = [
        Step(
            f"目标：{target_object}",
            "物体将在中央依次出现；目标出现时心中默念“选它”，非目标出现时保持放松",
            1.0 if short else 10.0,
            "target_selection_start",
            610,
            metadata={
                "target_object": target_object,
                "paradigm": "serial_target_attention_exploratory",
                "eeg_analysis_scope": "event_related_exploratory",
                "fnirs_analysis_scope": "block_level_only",
            },
            visual=target_object,
        )
    ]
    for round_number in range(1, rounds + 1):
        objects = ["水杯", "药瓶", "手机"]
        rng.shuffle(objects)
        for position, object_name in enumerate(objects, start=1):
            selected = object_name == target_object
            body.append(
                Step(
                    f"▶ {object_name} ◀",
                    "心中默念“选它”" if selected else "保持放松",
                    0.5 if short else 1.0,
                    "target_highlight",
                    612 if selected else 611,
                    f"selection_round_{round_number}",
                    position,
                    metadata={
                        "round": round_number,
                        "position": position,
                        "object": object_name,
                        "target_object": target_object,
                        "is_target": selected,
                        "paradigm": "serial_target_attention_exploratory",
                        "eeg_analysis_scope": "event_related_exploratory",
                        "fnirs_analysis_scope": "block_level_only",
                    },
                    visual=object_name,
                )
            )
            body.append(
                Step(
                    "+",
                    "保持中央注视",
                    0.2 if short else 0.5,
                    block=f"selection_round_{round_number}",
                    trial=position,
                )
            )
        body.append(Step("休息", f"第 {round_number}/{rounds} 轮完成", 0.5 if short else 4.0))
    body.append(
        Step(
            "目标注意评分",
            "请按整个模块的总体体验评分",
            0.0,
            "target_attention_rating_start",
            613,
            "target_attention",
            advance="form",
            completion_event="target_attention_rating",
            completion_code=614,
            fields=(
                InputField("target_attention", "保持目标注意的成功度（1-5）", "rating", 1, 5),
                InputField("target_task_difficulty", "目标任务难度（1-5）", "rating", 1, 5),
            ),
        )
    )
    return _experiment_bounds("m4b_target", body)


def build_m5_plan(short: bool = False, **_: object) -> list[Step]:
    del short
    task_choices = ("M1 运动想象", "M2 认知负荷", "M3A 安全动作", "M3B 疲劳", "M4A 意图", "M4B 目标注意", "不适用")
    body = [
        Step(
            "结束问卷",
            "请按本次会话的整体体验作答；若有明显不适，请同时告知实验员",
            0.0,
            "debrief_start",
            650,
            advance="form",
            completion_event="debrief",
            completion_code=651,
            fields=(
                InputField("kss_score", "当前困倦程度 KSS（1-9）", "rating", 1, 9),
                InputField(
                    "mi_difficulty",
                    "运动想象难度（1-5）",
                    "choice",
                    choices=("1", "2", "3", "4", "5", "不适用"),
                ),
                InputField("easiest_task", "最容易的任务", "choice", choices=task_choices),
                InputField("hardest_task", "最困难的任务", "choice", choices=task_choices),
                InputField("device_comfort", "设备舒适度（1=很不舒适，5=很舒适）", "rating", 1, 5),
                InputField("headache", "是否出现头痛", "boolean"),
                InputField("dizziness_or_nausea", "是否出现眩晕或恶心", "boolean"),
                InputField("skin_or_device_discomfort", "是否出现皮肤或设备压迫不适", "boolean"),
            ),
        )
    ]
    return _experiment_bounds("m5_debrief", body)


def build_protocol_plan(
    task: str,
    *,
    short: bool = False,
    older_adult: bool = False,
    seed: int = 0,
    target_object: str = "水杯",
    nback_order: str = "ascending",
) -> list[Step]:
    builders = {
        "deviceqc": build_deviceqc_plan,
        "m0_baseline": build_m0_plan,
        "m1_mi": build_m1_plan,
        "m2_nback": build_m2_plan,
        "m3a_safety": build_m3a_plan,
        "m3b_fatigue": build_m3b_plan,
        "m4a_intent": build_m4a_plan,
        "m4b_target": build_m4b_plan,
        "m5_debrief": build_m5_plan,
    }
    try:
        builder = builders[task]
    except KeyError as error:
        raise ValueError(f"未知实验模块：{task}") from error
    return builder(
        short=short,
        older_adult=older_adult,
        seed=seed,
        target_object=target_object,
        nback_order=nback_order,
    )


def estimate_protocol_seconds(
    task: str,
    *,
    short: bool = False,
    older_adult: bool = False,
) -> float:
    return sum(
        step.duration
        for step in build_protocol_plan(task, short=short, older_adult=older_adult, seed=0)
    )
