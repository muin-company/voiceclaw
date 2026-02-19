"""Audio — PyAudio microphone capture with VAD-based utterance detection."""

import collections
import threading
import time
import wave
from typing import Optional

import numpy as np
import pyaudio

from .vad import SileroVAD

SAMPLE_RATE = 16000
CHUNK_SIZE = 512
CHANNELS = 1
FORMAT = pyaudio.paInt16
VAD_THRESHOLD = 0.5


class AudioManager:
    """Continuous mic recording + VAD-based utterance extraction."""

    def __init__(self, vad: SileroVAD):
        self.vad = vad
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Speech state
        self._speech_active = False
        self._speech_start_time = 0.0
        self._silence_start_time = 0.0

        # Buffers
        self._pre_buffer = collections.deque(maxlen=20)
        self._speech_frames: list[bytes] = []

        # Completed utterance queue
        self._utterance_ready = threading.Event()
        self._utterance_file: Optional[str] = None

        try:
            self.pa = pyaudio.PyAudio()
        except Exception as e:
            raise RuntimeError(f"PyAudio init failed: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def terminate(self):
        self.stop()
        self.pa.terminate()

    def _listen_loop(self):
        stream = self.pa.open(
            format=FORMAT, channels=CHANNELS,
            rate=SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while self._running:
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                except Exception:
                    continue
                chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                confidence = self.vad.is_speech(chunk)
                with self._lock:
                    self._process_chunk(data, confidence)
        finally:
            stream.stop_stream()
            stream.close()

    def _process_chunk(self, data: bytes, confidence: float):
        now = time.time()
        is_speech = confidence > VAD_THRESHOLD

        if not self._speech_active:
            self._pre_buffer.append(data)
            if is_speech:
                self._speech_active = True
                self._speech_start_time = now
                self._silence_start_time = 0.0
                self._speech_frames = list(self._pre_buffer)
                self._speech_frames.append(data)
        else:
            self._speech_frames.append(data)
            if is_speech:
                self._silence_start_time = 0.0
            else:
                if self._silence_start_time == 0.0:
                    self._silence_start_time = now
                else:
                    speech_duration = now - self._speech_start_time
                    silence_duration = now - self._silence_start_time
                    threshold = 2.0 if speech_duration < 0.5 else (1.5 if speech_duration < 2.0 else 1.0)
                    if silence_duration >= threshold:
                        self._finalize_utterance()

    def _finalize_utterance(self):
        if not self._speech_frames:
            self._speech_active = False
            return

        temp_file = "/tmp/voiceclaw-input.wav"
        try:
            with wave.open(temp_file, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.pa.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b''.join(self._speech_frames))
        except Exception:
            self._speech_active = False
            self._speech_frames = []
            return

        speech_dur = time.time() - self._speech_start_time
        n_frames = len(self._speech_frames)

        self._speech_active = False
        self._speech_frames = []
        self._pre_buffer.clear()

        if speech_dur < 0.2 or n_frames < 5:
            return

        self._utterance_file = temp_file
        self._utterance_ready.set()

    def get_utterance(self, timeout: float = 30.0) -> Optional[str]:
        """Wait for next utterance. Returns WAV file path."""
        self._utterance_ready.clear()
        self._utterance_file = None
        if self._utterance_ready.wait(timeout=timeout):
            return self._utterance_file
        return None

    def record_speech(self, timeout: float = 10.0, silence_duration: float = 1.5) -> Optional[str]:
        """Legacy: single-shot recording (for wake word detection)."""
        stream = self.pa.open(
            format=FORMAT, channels=CHANNELS,
            rate=SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK_SIZE,
        )

        frames = []
        pre_buffer = collections.deque(maxlen=15)
        speech_started = False
        speech_start_time = None
        silence_start = None
        start_time = time.time()

        try:
            while time.time() - start_time < timeout:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                confidence = self.vad.is_speech(chunk)

                if not speech_started:
                    pre_buffer.append(data)

                if confidence > VAD_THRESHOLD:
                    if not speech_started:
                        speech_started = True
                        speech_start_time = time.time()
                        frames.extend(pre_buffer)
                    silence_start = None
                    frames.append(data)
                elif speech_started:
                    frames.append(data)
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > silence_duration:
                        break
        finally:
            stream.stop_stream()
            stream.close()

        if not frames or not speech_started:
            return None

        temp_file = "/tmp/voiceclaw-wake.wav"
        with wave.open(temp_file, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.pa.get_sample_size(FORMAT))
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b''.join(frames))

        return temp_file
