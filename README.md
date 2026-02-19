# 🎙️ VoiceClaw

**OpenClaw voice assistant plugin** — wake word detection, speech-to-text, text-to-speech, all as a standard OpenClaw plugin.

## Features

- 🗣️ **Wake word** — "Hey Claw" triggers voice interaction
- 🎤 **STT** — SenseVoice (primary), faster-whisper, OpenAI Whisper
- 🔊 **TTS** — Edge TTS, Piper, macOS `say`
- 🧠 **Agent integration** — Voice input goes directly to your OpenClaw agent
- ⚙️ **Standard plugin** — `openclaw.plugin.json` manifest, config via `openclaw.yaml`

## Architecture

```
Node.js (OpenClaw plugin)  ◄── JSON-RPC stdio ──►  Python (audio/ML)
├── service.ts (lifecycle)                           ├── vad.py (Silero VAD)
├── bridge.ts (IPC)                                  ├── stt.py (SenseVoice/Whisper)
├── commands.ts (/voiceclaw)                         ├── tts.py (Edge TTS/Piper)
├── gateway-methods.ts (RPC)                         ├── audio.py (PyAudio)
└── tools.ts (voice_speak)                           └── server.py (JSON-RPC server)
```

## Quick Start

```bash
# Install
openclaw plugins install @openclaw/voiceclaw

# Setup Python deps
openclaw voiceclaw install

# Start
openclaw voiceclaw start
# or in chat: /voiceclaw start
```

## Config

In `openclaw.yaml`:

```yaml
plugins:
  entries:
    voiceclaw:
      enabled: true
      config:
        stt:
          engine: sensevoice
          language: ko
        tts:
          engine: edge-tts
          voice: ko-KR-SunHiNeural
        wakeWord: "hey claw"
        autoStart: false
```

## Design

See [DESIGN.md](DESIGN.md) for full architecture, bridge protocol, and component details.

## Status

🚧 **Design phase** — migrating from [openclaw-voice](https://github.com/muin-company/openclaw-voice) to plugin standard.

## License

MIT
