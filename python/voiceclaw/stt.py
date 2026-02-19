"""STT — Speech-to-Text (SenseVoice → faster-whisper → openai-whisper)."""

import re

_engine = None
_model = None
_config = {}


def init(config: dict = None):
    """Initialize or reinitialize STT with given config."""
    global _config, _engine, _model
    if config:
        _config = config
    _engine = None
    _model = None
    _load_model()


def _load_model():
    global _engine, _model

    preferred = _config.get("engine", "sensevoice")
    language = _config.get("language", "ko")
    model_name = _config.get("model", "base")

    # 1) SenseVoice via funasr
    if preferred in ("sensevoice", None):
        try:
            from funasr import AutoModel
            _model = AutoModel(
                model="iic/SenseVoiceSmall",
                model_revision="master",
                device="cpu",
                disable_update=True,
            )
            _engine = "sensevoice"
            return
        except Exception:
            pass

    # 2) faster-whisper
    if preferred in ("sensevoice", "faster-whisper", None):
        try:
            from faster_whisper import WhisperModel
            _model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _engine = "faster-whisper"
            return
        except Exception:
            pass

    # 3) openai-whisper
    try:
        import whisper
        _model = whisper.load_model(model_name)
        _engine = "openai-whisper"
    except Exception:
        _engine = None


def transcribe(audio_file: str, prompt_hint: str = None) -> str:
    """Transcribe audio file to text."""
    global _engine, _model
    if _model is None:
        _load_model()
    if _model is None:
        return ""

    try:
        if _engine == "sensevoice":
            result = _model.generate(input=audio_file, language="ko")
            if result and len(result) > 0:
                text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])
                text = re.sub(r'<\|[^|]*\|>', '', text).strip()
                return text
            return ""

        elif _engine == "faster-whisper":
            segments, _ = _model.transcribe(
                audio_file, language="ko",
                initial_prompt=prompt_hint, beam_size=5, vad_filter=True,
            )
            return " ".join(s.text for s in segments).strip()

        else:  # openai-whisper
            kwargs = {"language": "ko", "fp16": False, "verbose": False}
            if prompt_hint:
                kwargs["initial_prompt"] = prompt_hint
            result = _model.transcribe(audio_file, **kwargs)
            return result["text"].strip()

    except Exception:
        return ""


def get_engine() -> str:
    return _engine or "none"
