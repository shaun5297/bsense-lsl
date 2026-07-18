"""Validation and local persistence for restricted participant profiles."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


SEX_OPTIONS = ("女", "男", "其他", "不愿透露")
HAND_OPTIONS = ("左", "右", "双手")
PROFILE_FIELDS = ("name", "age", "sex", "education_years", "dominant_hand")


def _restrict_profile_permissions(path: Path) -> None:
    """Keep direct identifiers private on POSIX; Windows relies on directory ACLs."""

    if os.name == "nt":
        return
    path.parent.chmod(0o700)
    if path.exists():
        path.chmod(0o600)


def validate_participant_profile(
    *,
    name: str,
    age: str,
    sex: str,
    education_years: str,
    dominant_hand: str,
) -> dict[str, object]:
    cleaned_name = name.strip()
    if len(cleaned_name) > 80 or any(ord(character) < 32 for character in cleaned_name):
        raise ValueError("姓名最多 80 个字符，且不能包含控制字符")

    try:
        parsed_age = int(age.strip())
    except ValueError as error:
        raise ValueError("年龄必须填写 1-120 的整数") from error
    if not 1 <= parsed_age <= 120:
        raise ValueError("年龄必须填写 1-120 的整数")

    if sex not in SEX_OPTIONS:
        raise ValueError("请选择性别")
    if dominant_hand not in HAND_OPTIONS:
        raise ValueError("请选择惯用手")

    education_text = education_years.strip()
    parsed_education: int | None = None
    if education_text:
        try:
            parsed_education = int(education_text)
        except ValueError as error:
            raise ValueError("受教育年限必须是 0-40 的整数，或留空") from error
        if not 0 <= parsed_education <= 40:
            raise ValueError("受教育年限必须是 0-40 的整数，或留空")

    return {
        "name": cleaned_name,
        "age": parsed_age,
        "sex": sex,
        "education_years": parsed_education,
        "dominant_hand": dominant_hand,
    }


def participant_profile_path(output_root: Path, participant: str, session: str) -> Path:
    return output_root / "participants" / f"sub-{participant}_ses-{session}_profile.json"


def save_participant_profile(
    output_root: Path,
    participant: str,
    session: str,
    profile: dict[str, object],
    app_version: str,
) -> tuple[Path, bool]:
    path = participant_profile_path(output_root, participant, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_profile_permissions(path)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"现有被试资料无法读取：{path}") from error
        differences = [field for field in PROFILE_FIELDS if existing.get(field) != profile.get(field)]
        if differences:
            raise ValueError(
                "当前表单与同一被试/会话的既有资料不一致："
                + "、".join(differences)
                + "。请核对资料，或使用新的会话编号。"
            )
        return path, False

    payload = {
        "schema_version": 1,
        "participant": participant,
        "session": session,
        **profile,
        "consent_confirmed": True,
        "app_version": app_version,
        "created_unix_time": time.time(),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(path, flags, 0o600)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    _restrict_profile_permissions(path)
    return path, True
