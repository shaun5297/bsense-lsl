"""Platform-specific defaults and integrations for the experiment app."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path


AUDIO_PATTERNS = {
    "start": ((880, 130),),
    "close_eyes": ((740, 160), (0, 100), (740, 160)),
    "rest_start": ((784, 130), (0, 100), (784, 130)),
    "ending_soon": ((740, 100), (0, 90), (740, 100)),
    "open_eyes": ((880, 120), (0, 80), (1047, 180)),
    "complete": ((784, 120), (0, 70), (988, 120), (0, 70), (1175, 220)),
}
VOICE_CUE_TEXTS = {
    "start": "请准备。",
    "close_eyes": "请轻轻闭上眼睛。",
    "rest_start": "现在开始休息。",
    "ending_soon": "本阶段即将结束。",
    "open_eyes": "请缓慢睁开眼睛。",
    "complete": "本模块已完成。",
}
VOICE_CUE_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_CUE_RATE = "-8%"
MACOS_SOUND_BY_FREQUENCY = {
    740: "Tink.aiff",
    784: "Pop.aiff",
    880: "Ping.aiff",
    988: "Glass.aiff",
    1047: "Glass.aiff",
    1175: "Hero.aiff",
}
MACOS_SOUND_ROOT = Path("/System/Library/Sounds")
MACOS_AFPLAY = Path("/usr/bin/afplay")
VOICE_AUDIO_ROOT = Path(__file__).with_name("audio")
_PLAYBACK_LOCK = threading.Lock()
_ACTIVE_MACOS_PROCESS: subprocess.Popen[bytes] | None = None


def default_output_root(platform: str | None = None, home: Path | None = None) -> Path:
    """Return a writable, native default data directory."""

    current_platform = platform or sys.platform
    if current_platform == "win32":
        return Path(r"C:\BCI\data\bsense")
    home_directory = home or Path.home()
    if current_platform == "darwin":
        return home_directory / "Documents" / "BCI" / "data" / "bsense"
    return home_directory / "BCI" / "data" / "bsense"


def ui_font_family(platform: str | None = None) -> str:
    current_platform = platform or sys.platform
    if current_platform == "darwin":
        return "PingFang SC"
    if current_platform == "win32":
        return "Microsoft YaHei UI"
    return "Noto Sans CJK SC"


def audio_cues_supported(platform: str | None = None) -> bool:
    current_platform = platform or sys.platform
    if current_platform == "win32":
        return True
    if current_platform != "darwin" or not MACOS_AFPLAY.is_file():
        return False
    voice_assets_ready = all(voice_cue_path(cue).is_file() for cue in VOICE_CUE_TEXTS)
    tone_assets_ready = all((MACOS_SOUND_ROOT / name).is_file() for name in set(MACOS_SOUND_BY_FREQUENCY.values()))
    return voice_assets_ready or tone_assets_ready


def voice_cue_path(cue: str) -> Path:
    return VOICE_AUDIO_ROOT / f"{cue}.wav"


def _play_voice_cue(cue: str) -> bool:
    audio_path = voice_cue_path(cue)
    if not audio_path.is_file():
        return False
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(
            str(audio_path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        return True
    if sys.platform != "darwin" or not MACOS_AFPLAY.is_file():
        return False

    global _ACTIVE_MACOS_PROCESS
    with _PLAYBACK_LOCK:
        if _ACTIVE_MACOS_PROCESS is not None and _ACTIVE_MACOS_PROCESS.poll() is None:
            _ACTIVE_MACOS_PROCESS.terminate()
        _ACTIVE_MACOS_PROCESS = subprocess.Popen(
            [str(MACOS_AFPLAY), str(audio_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True


def play_audio_cue(cue: str) -> bool:
    """Play a cached voice cue, falling back to short operating-system tones."""

    if cue not in AUDIO_PATTERNS or not audio_cues_supported():
        return False
    if _play_voice_cue(cue):
        return True

    if sys.platform == "win32":

        def play() -> None:
            import winsound

            for frequency, duration_ms in AUDIO_PATTERNS[cue]:
                if frequency == 0:
                    time.sleep(duration_ms / 1000)
                else:
                    try:
                        winsound.Beep(frequency, duration_ms)
                    except RuntimeError:
                        winsound.MessageBeep()

    else:

        def play() -> None:
            for frequency, duration_ms in AUDIO_PATTERNS[cue]:
                if frequency == 0:
                    time.sleep(duration_ms / 1000)
                    continue
                sound_path = MACOS_SOUND_ROOT / MACOS_SOUND_BY_FREQUENCY[frequency]
                subprocess.run(
                    [str(MACOS_AFPLAY), "-t", f"{duration_ms / 1000:.3f}", str(sound_path)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

    threading.Thread(target=play, daemon=True).start()
    return True


def _default_labrecorder_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("LABRECORDER_APP")
    if configured:
        candidates.append(Path(configured).expanduser())

    project_root = Path(__file__).resolve().parents[2]
    workspace_root = project_root.parent
    candidates.extend(sorted(workspace_root.glob("LabRecorder*/LabRecorder.app"), reverse=True))
    candidates.extend(
        (
            Path("/Applications/LabRecorder.app"),
            Path.home() / "Applications" / "LabRecorder.app",
            Path("/opt/homebrew/opt/labrecorder/LabRecorder/LabRecorder.app"),
            Path("/usr/local/opt/labrecorder/LabRecorder/LabRecorder.app"),
        )
    )
    return candidates


def find_labrecorder_app(candidates: Iterable[Path] | None = None) -> Path | None:
    """Find a runnable macOS LabRecorder application bundle."""

    if sys.platform != "darwin":
        return None
    for candidate in candidates if candidates is not None else _default_labrecorder_candidates():
        app_path = Path(candidate).expanduser().resolve()
        if (app_path / "Contents" / "MacOS" / "LabRecorder").is_file():
            return app_path
    return None


def launch_labrecorder(app_path: Path | None = None) -> Path:
    """Open LabRecorder on macOS and return the application bundle used."""

    if sys.platform != "darwin":
        raise RuntimeError("自动打开 LabRecorder 目前仅支持 macOS；请在当前系统手动启动。")
    resolved = app_path or find_labrecorder_app()
    if resolved is None:
        raise FileNotFoundError(
            "未找到 LabRecorder.app。请放到 /Applications，或设置 LABRECORDER_APP 环境变量。"
        )
    subprocess.run(["/usr/bin/open", str(resolved)], check=True)
    return resolved
