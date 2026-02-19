"""TTS — Text-to-Speech (Edge TTS primary, macOS say fallback)."""

import re
import subprocess
import sys
import time
from pathlib import Path

_engine = None
_voice = "ko-KR-SunHiNeural"


def init(config: dict = None):
    global _engine, _voice
    if config:
        _voice = config.get("voice", "ko-KR-SunHiNeural")
        preferred = config.get("engine", "edge-tts")
    else:
        preferred = "edge-tts"
    _engine = preferred


def speak(text: str, voice: str = None) -> float:
    """Speak text. Returns duration in seconds."""
    if not text.strip():
        return 0.0

    if _engine is None:
        init()

    clean = _clean_text(text)
    if not clean:
        return 0.0

    t0 = time.time()
    use_voice = voice or _voice

    try:
        if _engine == "say" and sys.platform == "darwin":
            _speak_macos(clean)
        elif _engine == "piper":
            _speak_piper(clean)
        else:
            _speak_edge(clean, use_voice)
    except Exception as e:
        print(f"[tts] Error: {e}", file=sys.stderr, flush=True)
        # Fallback to macOS say
        if sys.platform == "darwin":
            try:
                _speak_macos(clean)
            except Exception:
                pass

    return time.time() - t0


def _speak_edge(text: str, voice: str):
    mp3_path = "/tmp/voiceclaw-tts.mp3"
    edge_cmd = "edge-tts"
    for p in [
        Path.home() / "Library" / "Python" / "3.9" / "bin" / "edge-tts",
        Path.home() / ".local" / "bin" / "edge-tts",
    ]:
        if p.exists():
            edge_cmd = str(p)
            break

    subprocess.run(
        [edge_cmd, "--voice", voice, "--text", text, "--write-media", mp3_path],
        capture_output=True, check=True, timeout=10,
    )
    if Path(mp3_path).exists() and Path(mp3_path).stat().st_size > 0:
        _play(mp3_path)
        Path(mp3_path).unlink(missing_ok=True)


def _speak_macos(text: str):
    subprocess.run(["say", "-v", "Yuna", "-r", "180", text],
                   capture_output=True, timeout=30)


def _speak_piper(text: str):
    # Placeholder for Piper TTS
    _speak_macos(text)


def _play(path: str):
    if sys.platform == "darwin":
        subprocess.run(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif path.endswith(".mp3"):
        subprocess.run(["mpg123", "-q", path], capture_output=True)
    else:
        subprocess.run(["aplay", "-q", path], capture_output=True)


def _clean_text(text: str) -> str:
    text = re.sub(r'```[^`]*```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'[#*_]', '', text)
    text = re.sub(r':[a-z_]+:', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]', '', text)
    return ' '.join(text.split())[:1000]


def get_engine() -> str:
    return _engine or "edge-tts"
