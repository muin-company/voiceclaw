# 🎙️ VoiceClaw

**OpenClaw voice assistant plugin** — wake word detection, speech-to-text, text-to-speech, all as a standard OpenClaw plugin.

## Features

- 🗣️ **Wake word** — configurable trigger (default: "미르야")
- 🎤 **STT** — SenseVoice (primary), faster-whisper, OpenAI Whisper
- 🔊 **TTS** — Edge TTS, Piper, macOS `say`
- 🧠 **Agent integration** — Voice input goes directly to your OpenClaw agent
- ⚙️ **Standard plugin** — `openclaw.plugin.json` manifest, config via `openclaw.yaml`

## Architecture

```
Node.js (OpenClaw plugin)  ◄── JSON-RPC stdio ──►  Python (audio/ML)
├── index.ts (entry)                                 ├── vad.py (Silero VAD)
├── bridge.ts (IPC)                                  ├── stt.py (SenseVoice/Whisper)
│                                                    ├── tts.py (Edge TTS)
│                                                    └── audio.py (PyAudio)
```

## Installation

```bash
# Install as OpenClaw plugin
cd ~/voiceclaw
openclaw plugins install .

# Install Python dependencies
bash scripts/install-python.sh
```

## Usage

```bash
# Via chat command
/voiceclaw start
/voiceclaw stop
/voiceclaw status

# Via Gateway RPC
# voiceclaw.status
# voiceclaw.config {action: "get"}
```

## Configuration (`openclaw.yaml`)

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
        wakeWord: "미르야"
        vad:
          threshold: 0.5
        autoStart: false
        agentId: main
```

## Development

```bash
npm install
npm run build    # TypeScript → dist/
npm run dev      # Watch mode
```
