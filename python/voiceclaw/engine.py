#!/usr/bin/env python3
"""VoiceClaw Engine — JSON-RPC stdio server.

Reads JSON-RPC requests from stdin, writes responses/events to stdout.
Manages: microphone → VAD → STT → utterance events, and TTS playback.
"""

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Lazy imports — ML deps may not be available
_vad_mod = None
_audio_mod = None
_stt_mod = None
_tts_mod = None


def _import_deps():
    global _vad_mod, _audio_mod, _stt_mod, _tts_mod
    if _vad_mod is None:
        from . import vad as _v, audio as _a, stt as _s, tts as _t
        _vad_mod, _audio_mod, _stt_mod, _tts_mod = _v, _a, _s, _t


def _log(msg: str):
    """Log to stderr (Node.js captures this)."""
    print(f"[engine] {msg}", file=sys.stderr, flush=True)


class Engine:
    def __init__(self, config: dict):
        self.config = config
        self.running = False
        self._listen_thread = None

        # Init components
        self.vad = None
        self.audio = None
        self.wake_word = config.get("wakeWord", "미르야").lower()
        self._deps_loaded = False

    def _ensure_deps(self):
        """Load ML dependencies lazily."""
        if self._deps_loaded:
            return
        _import_deps()
        vad_cfg = self.config.get("vad", {})
        self.vad = _vad_mod.SileroVAD(threshold=vad_cfg.get("threshold", 0.5))
        self.audio = _audio_mod.AudioManager(self.vad)
        _stt_mod.init(self.config.get("stt", {}))
        _tts_mod.init(self.config.get("tts", {}))
        self._deps_loaded = True
        _log(f"Engine ready (wake={self.wake_word}, stt={_stt_mod.get_engine()}, tts={_tts_mod.get_engine()})")

    def emit(self, event_type: str, data: dict = None):
        """Send event notification to Node.js."""
        msg = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {"type": event_type, "data": data or {}},
        }
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def respond(self, req_id, result=None, error=None):
        """Send JSON-RPC response."""
        msg = {"jsonrpc": "2.0", "id": req_id}
        if error:
            msg["error"] = {"code": -1, "message": str(error)}
        else:
            msg["result"] = result
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def handle_request(self, req: dict):
        """Handle a JSON-RPC request."""
        method = req.get("method", "")
        params = req.get("params", {})
        req_id = req.get("id")

        try:
            if method == "ping":
                result = {"pong": True, "time": time.time()}
            elif method == "start":
                self._ensure_deps()
                result = self._start_listening()
            elif method == "stop":
                result = self._stop_listening()
            elif method == "shutdown":
                self._stop_listening()
                result = {"status": "shutting_down"}
                if req_id is not None:
                    self.respond(req_id, result)
                # Exit after responding
                threading.Timer(0.1, lambda: os._exit(0)).start()
                return
            elif method == "tts.speak":
                self._ensure_deps()
                text = params.get("text", "")
                voice = params.get("voice")
                if text:
                    duration = _tts_mod.speak(text, voice=voice)
                    result = {"duration": duration, "engine": _tts_mod.get_engine()}
                else:
                    result = {"duration": 0}
            elif method == "speak":
                # Notification from Node.js — speak agent response
                self._ensure_deps()
                text = params.get("text", "")
                if text:
                    _tts_mod.speak(text)
                return  # No response for notifications without id
            elif method == "stt.transcribe":
                self._ensure_deps()
                audio_path = params.get("audio_path", "")
                text = _stt_mod.transcribe(audio_path)
                result = {"text": text, "engine": _stt_mod.get_engine()}
            elif method == "config.update":
                if self._deps_loaded:
                    self._update_config(params)
                else:
                    self.config.update(params)
                result = {"updated": True}
            elif method == "status":
                result = {
                    "running": self.running,
                    "stt_engine": _stt_mod.get_engine() if _stt_mod else "not_loaded",
                    "tts_engine": _tts_mod.get_engine() if _tts_mod else "not_loaded",
                    "wake_word": self.wake_word,
                }
            elif method == "echo":
                result = {"echo": params}
            else:
                if req_id is not None:
                    self.respond(req_id, error=f"Unknown method: {method}")
                return

            if req_id is not None:
                self.respond(req_id, result)

        except Exception as e:
            _log(f"Error handling {method}: {e}")
            if req_id is not None:
                self.respond(req_id, error=str(e))

    def _start_listening(self) -> dict:
        if self.running:
            return {"status": "already_running"}
        self.running = True
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()
        return {"status": "started"}

    def _stop_listening(self) -> dict:
        self.running = False
        if self.audio:
            self.audio.stop()
        return {"status": "stopped"}

    def _listen_loop(self):
        """Main listening loop: mic → VAD → wake word → utterance."""
        _log("Listening loop started")
        self.audio.start()

        try:
            while self.running:
                # Phase 1: Wait for wake word
                audio_file = self.audio.record_speech(timeout=3.0, silence_duration=0.5)
                if not audio_file:
                    continue

                text = _stt_mod.transcribe(audio_file)
                Path(audio_file).unlink(missing_ok=True)

                if not text:
                    continue

                text_lower = text.strip().lower()
                if self.wake_word in text_lower:
                    _log(f"Wake word detected in: '{text}'")
                    self.emit("wake_word", {"text": text})

                    # Phase 2: Record full utterance
                    utt_file = self.audio.get_utterance(timeout=10.0)
                    if utt_file:
                        utt_text = _stt_mod.transcribe(utt_file)
                        Path(utt_file).unlink(missing_ok=True)
                        if utt_text.strip():
                            _log(f"Utterance: '{utt_text}'")
                            self.emit("utterance", {
                                "text": utt_text,
                                "session_id": f"voice-{int(time.time())}",
                            })
        except Exception as e:
            _log(f"Listen loop error: {e}")
            self.emit("error", {"message": str(e)})
        finally:
            self.audio.stop()
            _log("Listening loop stopped")

    def _update_config(self, new_config: dict):
        self.config.update(new_config)
        if "wakeWord" in new_config:
            self.wake_word = new_config["wakeWord"].lower()
        if "stt" in new_config and _stt_mod:
            _stt_mod.init(new_config["stt"])
        if "tts" in new_config and _tts_mod:
            _tts_mod.init(new_config["tts"])

    def run(self):
        """Main loop: read JSON-RPC from stdin."""
        _log("Engine stdio server running")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                self.handle_request(req)
            except json.JSONDecodeError as e:
                _log(f"Invalid JSON: {e}")
            except Exception as e:
                _log(f"Unexpected error: {e}")


def main():
    # Load config from env
    config_str = os.environ.get("VOICECLAW_CONFIG", "{}")
    try:
        config = json.loads(config_str)
    except json.JSONDecodeError:
        config = {}

    # Handle signals
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))

    engine = Engine(config)
    engine.run()


if __name__ == "__main__":
    main()
