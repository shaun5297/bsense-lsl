#!/usr/bin/env python3
"""Build and verify a native BSense LSL desktop release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
ENTRYPOINT_PATH = PROJECT_ROOT / "packaging" / "entrypoints" / "bsense_lsl.py"
RELEASE_README_PATH = PROJECT_ROOT / "packaging" / "RELEASE_README.txt"
THIRD_PARTY_NOTICES_PATH = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"
ASSET_ROOT = PROJECT_ROOT / "assets"
AUDIO_ROOT = PROJECT_ROOT / "src" / "bsense_experiment" / "audio"
APP_NAME = "BSense-LSL"
MACOS_BUNDLE_IDENTIFIER = "io.github.shaun5297.bsense-lsl"
REQUIRED_ASSETS = ("cup.png", "medicinebottle.png", "mobilephone.png")
REQUIRED_AUDIO = (
    "close_eyes.wav",
    "complete.wav",
    "ending_soon.wav",
    "open_eyes.wav",
    "rest_start.wav",
    "start.wav",
)


def project_version() -> str:
    with PYPROJECT_PATH.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def release_target() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"} and struct.calcsize("P") == 8:
        return "windows", "x64"
    if system == "Darwin" and machine == "arm64":
        return "macos", "arm64"
    raise RuntimeError(
        "只支持在 Windows x64 或 macOS Apple Silicon 原生环境中构建；"
        f"当前为 {system} {platform.machine()}。"
    )


def archive_basename(version: str, operating_system: str, architecture: str) -> str:
    return f"{APP_NAME}-{version}-{operating_system}-{architecture}"


def verify_sources() -> None:
    required_files = (
        ENTRYPOINT_PATH,
        RELEASE_README_PATH,
        THIRD_PARTY_NOTICES_PATH,
        *(ASSET_ROOT / name for name in REQUIRED_ASSETS),
        *(AUDIO_ROOT / name for name in REQUIRED_AUDIO),
    )
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("发行资源缺失：" + "、".join(missing))


def run(
    command: list[str],
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    try:
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, end="")
        raise


def build_with_pyinstaller(
    operating_system: str,
    architecture: str,
    work_root: Path,
) -> Path:
    spec_root = work_root / "spec"
    build_root = work_root / "build"
    dist_root = work_root / "dist"
    for path in (spec_root, build_root, dist_root):
        path.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--add-data",
        f"{AUDIO_ROOT}{os.pathsep}bsense_experiment/audio",
        "--specpath",
        str(spec_root),
        "--workpath",
        str(build_root),
        "--distpath",
        str(dist_root),
    ]
    for filename in REQUIRED_ASSETS:
        command.extend(["--add-data", f"{ASSET_ROOT / filename}{os.pathsep}assets"])
    if operating_system == "macos":
        command.extend(
            [
                "--target-arch",
                architecture,
                "--osx-bundle-identifier",
                MACOS_BUNDLE_IDENTIFIER,
            ]
        )
    command.append(str(ENTRYPOINT_PATH))
    pyinstaller_environment = os.environ.copy()
    pyinstaller_environment["PYINSTALLER_CONFIG_DIR"] = str(work_root / "cache")
    result = run(command, pyinstaller_environment)
    if result.stdout:
        print(result.stdout, end="")

    bundle = dist_root / (f"{APP_NAME}.app" if operating_system == "macos" else APP_NAME)
    if not bundle.exists():
        raise FileNotFoundError(f"PyInstaller 未生成预期目录：{bundle}")
    return bundle


def frozen_executable(bundle: Path, operating_system: str) -> Path:
    if operating_system == "macos":
        return bundle / "Contents" / "MacOS" / APP_NAME
    return bundle / f"{APP_NAME}.exe"


def verify_windows_x64(executable: Path) -> None:
    with executable.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise RuntimeError("Windows 发行文件不是有效的 PE 可执行文件")
        handle.seek(0x3C)
        pe_offset = struct.unpack("<I", handle.read(4))[0]
        handle.seek(pe_offset)
        if handle.read(4) != b"PE\0\0":
            raise RuntimeError("Windows 发行文件缺少 PE 标头")
        machine = struct.unpack("<H", handle.read(2))[0]
    if machine != 0x8664:
        raise RuntimeError(f"Windows 可执行文件不是 x64 架构（PE Machine=0x{machine:04x}）")


def verify_macos_arm64(executable: Path) -> None:
    result = run(["/usr/bin/file", str(executable)])
    if "arm64" not in result.stdout:
        raise RuntimeError(f"macOS 可执行文件不是 ARM64：{result.stdout.strip()}")


def verify_frozen_app(bundle: Path, operating_system: str) -> None:
    executable = frozen_executable(bundle, operating_system)
    if not executable.is_file():
        raise FileNotFoundError(f"发行主程序缺失：{executable}")
    if operating_system == "windows":
        verify_windows_x64(executable)
    else:
        verify_macos_arm64(executable)

    self_test_report = bundle.parent / "frozen-self-test.json"
    if self_test_report.exists():
        self_test_report.unlink()
    run(
        [
            str(executable),
            "--self-test",
            "--self-test-output",
            str(self_test_report),
        ]
    )
    if not self_test_report.is_file():
        raise FileNotFoundError("冻结程序未生成自检报告")
    payload = json.loads(self_test_report.read_text(encoding="utf-8"))
    self_test_report.unlink()
    if payload.get("status") != "ok":
        raise RuntimeError(f"冻结程序协议自检失败：{payload}")


def stage_release(
    bundle: Path,
    stage_root: Path,
    version: str,
    operating_system: str,
    architecture: str,
) -> Path:
    release_name = archive_basename(version, operating_system, architecture)
    staged_release = stage_root / release_name
    staged_release.mkdir(parents=True)
    shutil.copytree(bundle, staged_release / bundle.name, symlinks=True)
    shutil.copy2(RELEASE_README_PATH, staged_release / "README.txt")
    shutil.copy2(THIRD_PARTY_NOTICES_PATH, staged_release / "THIRD_PARTY_NOTICES.md")
    metadata = {
        "application": APP_NAME,
        "version": version,
        "operating_system": operating_system,
        "architecture": architecture,
        "python": platform.python_version(),
        "build_host": platform.platform(),
    }
    (staged_release / "VERSION.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return staged_release


def create_zip(staged_release: Path, output_root: Path, operating_system: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / f"{staged_release.name}.zip"
    if archive_path.exists():
        archive_path.unlink()
    if operating_system == "macos":
        run(
            [
                "/usr/bin/ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(staged_release),
                str(archive_path),
            ]
        )
    else:
        generated = Path(
            shutil.make_archive(
                str(archive_path.with_suffix("")),
                "zip",
                root_dir=staged_release.parent,
                base_dir=staged_release.name,
            )
        )
        if generated != archive_path:
            raise RuntimeError(f"压缩包路径异常：{generated}")
    return archive_path


def write_checksum(archive_path: Path) -> Path:
    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest.hexdigest()}  {archive_path.name}\n", encoding="ascii")
    return checksum_path


def verify_archive(archive_path: Path, operating_system: str) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        invalid_member = archive.testzip()
        if invalid_member is not None:
            raise RuntimeError(f"ZIP 内容校验失败：{invalid_member}")
        names = archive.namelist()

    executable_suffix = (
        f"{APP_NAME}.app/Contents/MacOS/{APP_NAME}"
        if operating_system == "macos"
        else f"{APP_NAME}/{APP_NAME}.exe"
    )
    required_suffixes = (
        executable_suffix,
        "README.txt",
        "THIRD_PARTY_NOTICES.md",
        "VERSION.json",
        *(f"assets/{name}" for name in REQUIRED_ASSETS),
        *(f"bsense_experiment/audio/{name}" for name in REQUIRED_AUDIO),
    )
    missing = [
        suffix
        for suffix in required_suffixes
        if not any(name.endswith(suffix) for name in names)
    ]
    if missing:
        raise RuntimeError("ZIP 缺少发行内容：" + "、".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "release",
        help="发行 ZIP 与校验文件输出目录（默认：release）",
    )
    parser.add_argument(
        "--expected-tag",
        help="可选 Git 标签，例如 v0.8.0；与 pyproject.toml 版本不符时停止构建",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    version = project_version()
    if args.expected_tag and args.expected_tag != f"v{version}":
        raise RuntimeError(
            f"标签 {args.expected_tag!r} 与项目版本 {version!r} 不一致；"
            f"预期标签为 v{version}"
        )
    verify_sources()
    operating_system, architecture = release_target()

    work_root = PROJECT_ROOT / "build" / f"release-{operating_system}-{architecture}"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)

    bundle = build_with_pyinstaller(operating_system, architecture, work_root)
    verify_frozen_app(bundle, operating_system)
    staged_release = stage_release(
        bundle,
        work_root / "stage",
        version,
        operating_system,
        architecture,
    )
    output_root = args.output_dir.resolve()
    archive_path = create_zip(staged_release, output_root, operating_system)
    verify_archive(archive_path, operating_system)
    checksum_path = write_checksum(archive_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "archive": str(archive_path),
                "checksum": str(checksum_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
