#!/usr/bin/env python3
"""Generate cached Chinese voice cues; this maintainer tool requires edge-tts."""

from __future__ import annotations

import argparse
import asyncio
import array
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bsense_experiment.platform_support import (  # noqa: E402
    VOICE_AUDIO_ROOT,
    VOICE_CUE_RATE,
    VOICE_CUE_TEXTS,
    VOICE_CUE_VOICE,
)


def _convert_to_wav(source: Path, destination: Path) -> None:
    afconvert = shutil.which("afconvert")
    if afconvert:
        command = [afconvert, str(source), str(destination), "-f", "WAVE", "-d", "LEI16@24000", "-c", "1"]
    elif ffmpeg := shutil.which("ffmpeg"):
        command = [ffmpeg, "-y", "-i", str(source), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(destination)]
    else:
        raise RuntimeError("生成 WAV 需要 macOS afconvert 或 ffmpeg")
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _trim_silence(path: Path, margin_seconds: float = 0.08) -> None:
    with wave.open(str(path), "rb") as source:
        parameters = source.getparams()
        frames = source.readframes(source.getnframes())
    if parameters.nchannels != 1 or parameters.sampwidth != 2:
        raise RuntimeError(f"仅支持裁剪单声道 16-bit PCM：{path}")
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(sample) for sample in samples), default=0)
    threshold = max(200, int(peak * 0.02))
    active = [index for index, sample in enumerate(samples) if abs(sample) >= threshold]
    if not active:
        return
    margin = round(parameters.framerate * margin_seconds)
    start = max(0, active[0] - margin)
    stop = min(len(samples), active[-1] + margin + 1)
    trimmed = array.array("h", samples[start:stop])
    if sys.byteorder != "little":
        trimmed.byteswap()
    with wave.open(str(path), "wb") as destination:
        destination.setparams(parameters)
        destination.writeframes(trimmed.tobytes())


async def generate(*, missing_only: bool = False) -> None:
    try:
        import edge_tts
    except ImportError as error:
        raise RuntimeError('请先安装可选依赖：python -m pip install ".[voice-generation]"') from error

    VOICE_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bsense-voice-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        for cue, text in VOICE_CUE_TEXTS.items():
            wav_path = VOICE_AUDIO_ROOT / f"{cue}.wav"
            if missing_only and wav_path.is_file():
                continue
            mp3_path = temporary_root / f"{cue}.mp3"
            await edge_tts.Communicate(text, VOICE_CUE_VOICE, rate=VOICE_CUE_RATE).save(str(mp3_path))
            _convert_to_wav(mp3_path, wav_path)
            _trim_silence(wav_path)
            print(f"{cue}: {text} -> {wav_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--missing-only", action="store_true", help="Only generate cues without a WAV asset")
    arguments = parser.parse_args()
    asyncio.run(generate(missing_only=arguments.missing_only))
