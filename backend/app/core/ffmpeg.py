"""Locate and run FFmpeg / ffprobe safely (argument arrays, never shell strings)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

_WINGET_GLOB = [
    Path.home() / "AppData/Local/Microsoft/WinGet/Packages",
]


class FFmpegNotFound(RuntimeError):
    pass


def _candidates(name: str) -> list[str]:
    out: list[str] = []
    env = f"QVS_{name.upper()}"
    if os.environ.get(env):
        out.append(os.environ[env])
    which = shutil.which(name)
    if which:
        out.append(which)
    # winget-installed packages (path env may not be refreshed in this shell)
    for pkg_root in _WINGET_GLOB:
        if pkg_root.exists():
            bin_dirs = sorted(pkg_root.glob("*/ffmpeg*/bin"))
            for bin_dir in bin_dirs:
                cand = bin_dir / f"{name}.exe"
                if cand.exists():
                    out.append(str(cand))
    links = Path.home() / "AppData/Local/Microsoft/WinGet/Links"
    if links.exists():
        cand = links / f"{name}.exe"
        if cand.exists():
            out.append(str(cand))
    # common manual locations
    for p in (Path("C:/ffmpeg/bin"), Path.home() / "ffmpeg/bin", ROOT_TOOLS := Path(__file__).resolve().parents[3] / "tools/ffmpeg/bin"):
        cand = p / f"{name}.exe"
        if cand.exists():
            out.append(str(cand))
    return out


class FFmpegTools:
    """Lazy resolver + runner for ffmpeg/ffprobe."""

    def __init__(self) -> None:
        self._ffmpeg: str | None = None
        self._ffprobe: str | None = None
        self._version: str | None = None

    def _resolve(self, name: str) -> str:
        for cand in _candidates(name):
            try:
                proc = subprocess.run(
                    [cand, "-version"], capture_output=True, text=True, timeout=15
                )
                if proc.returncode == 0:
                    return cand
            except (OSError, subprocess.TimeoutExpired):
                continue
        raise FFmpegNotFound(
            f"{name} was not found on PATH. Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) "
            "or set the QVS_FFMPEG / QVS_FFPROBE environment variables."
        )

    @property
    def ffmpeg(self) -> str:
        if self._ffmpeg is None:
            self._ffmpeg = self._resolve("ffmpeg")
        return self._ffmpeg

    @property
    def ffprobe(self) -> str:
        if self._ffprobe is None:
            self._ffprobe = self._resolve("ffprobe")
        return self._ffprobe

    def check(self) -> dict[str, Any]:
        try:
            ffmpeg = self.ffmpeg
            ffprobe = self.ffprobe
        except FFmpegNotFound as exc:
            return {"ok": False, "error": str(exc)}
        proc = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15)
        m = re.search(r"ffmpeg version (\S+)", proc.stdout)
        return {"ok": True, "ffmpeg": ffmpeg, "ffprobe": ffprobe, "version": m.group(1) if m else "unknown"}

    def run(self, args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
        """Run ffmpeg/ffprobe with argument array (no shell)."""
        proc = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-nostdin", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return proc

    def probe_duration(self, media: Path) -> float:
        proc = subprocess.run(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(media)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {media.name}: {proc.stderr.strip()[:300]}")
        return float(proc.stdout.strip())

    def probe_json(self, media: Path) -> dict[str, Any]:
        proc = subprocess.run(
            [self.ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(media)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {media.name}: {proc.stderr.strip()[:300]}")
        return json.loads(proc.stdout)


tools = FFmpegTools()
