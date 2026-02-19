# VoiceClaw — OpenClaw Plugin Design Document

> Voice assistant plugin for OpenClaw: wake word detection, STT, TTS, continuous conversation.

## 1. Plugin Manifest (`openclaw.plugin.json`)

```json
{
  "id": "voiceclaw",
  "name": "VoiceClaw",
  "version": "0.1.0",
  "description": "Voice assistant plugin — wake word, STT, TTS for OpenClaw",
  "entry": "./src/index.ts",
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "stt": {
        "type": "object",
        "properties": {
          "engine": {
            "type": "string",
            "enum": ["sensevoice", "faster-whisper", "whisper"],
            "default": "sensevoice"
          },
          "model": {
            "type": "string",
            "default": "base"
          },
          "language": {
            "type": "string",
            "default": "ko"
          }
        }
      },
      "tts": {
        "type": "object",
        "properties": {
          "engine": {
            "type": "string",
            "enum": ["edge-tts", "piper", "say"],
            "default": "edge-tts"
          },
          "voice": {
            "type": "string",
            "default": "ko-KR-SunHiNeural"
          }
        }
      },
      "wakeWord": {
        "type": "string",
        "default": "hey claw"
      },
      "vad": {
        "type": "object",
        "properties": {
          "threshold": { "type": "number", "default": 0.5 },
          "silenceDuration": { "type": "number", "default": 0.5 }
        }
      },
      "autoStart": {
        "type": "boolean",
        "default": false
      },
      "pythonPath": {
        "type": "string",
        "description": "Path to Python 3.9+ binary. Defaults to bundled venv."
      }
    }
  },
  "uiHints": {
    "stt.engine": { "label": "STT Engine" },
    "stt.model": { "label": "STT Model", "placeholder": "base" },
    "tts.engine": { "label": "TTS Engine" },
    "tts.voice": { "label": "TTS Voice", "placeholder": "ko-KR-SunHiNeural" },
    "wakeWord": { "label": "Wake Word", "placeholder": "hey claw" },
    "autoStart": { "label": "Auto-start on gateway boot" }
  },
  "skills": ["skills/voiceclaw"]
}
```

## 2. Package Structure

```
voiceclaw/
├── openclaw.plugin.json          # Plugin manifest
├── package.json                  # npm package (@openclaw/voiceclaw)
├── tsconfig.json
├── src/
│   ├── index.ts                  # Plugin entry — registers everything
│   ├── service.ts                # Background mic listening service
│   ├── bridge.ts                 # Python ↔ Node.js bridge (child_process)
│   ├── commands.ts               # CLI commands: /voiceclaw start|stop|status
│   ├── gateway-methods.ts        # RPC: voiceclaw.status, voiceclaw.config
│   └── tools.ts                  # Agent tool: voice_speak
├── python/
│   ├── requirements.txt          # Python deps (pyaudio, torch, edge-tts, etc.)
│   ├── setup.py                  # pip install -e . support
│   ├── voiceclaw/
│   │   ├── __init__.py
│   │   ├── server.py             # JSON-RPC stdio server (bridge endpoint)
│   │   ├── vad.py                # Silero VAD
│   │   ├── stt.py                # SenseVoice / faster-whisper / whisper
│   │   ├── tts.py                # Edge TTS / Piper / macOS say
│   │   ├── audio.py              # PyAudio mic capture & playback
│   │   └── wakeword.py           # Wake word detection
│   └── venv/                     # Auto-created by install
├── skills/
│   └── voiceclaw/
│       └── SKILL.md              # Agent skill doc for voice interaction
├── scripts/
│   └── install-python.sh         # Auto-setup: venv + pip install
├── README.md
└── DESIGN.md                     # This file
```

## 3. Core Components

### 3.1 Plugin Entry (`src/index.ts`)

```ts
import { registerService } from "./service";
import { registerCommands } from "./commands";
import { registerGatewayMethods } from "./gateway-methods";
import { registerTools } from "./tools";

export default function register(api: any) {
  registerService(api);
  registerCommands(api);
  registerGatewayMethods(api);
  registerTools(api);
}
```

### 3.2 Background Service (`src/service.ts`) — `registerService`

The service manages the Python bridge process lifecycle.

```ts
api.registerService({
  id: "voiceclaw",
  start: async () => {
    const config = api.config.plugins?.entries?.voiceclaw?.config ?? {};
    if (config.autoStart) {
      await bridge.start(config);
    }
    api.logger.info("VoiceClaw service registered");
  },
  stop: async () => {
    await bridge.stop();
    api.logger.info("VoiceClaw service stopped");
  },
});
```

**Lifecycle:**
1. Gateway starts → service `start()` called
2. If `autoStart: true`, spawns Python bridge immediately
3. Otherwise, waits for `/voiceclaw start` command or RPC call
4. Gateway stops → service `stop()` kills Python process

### 3.3 CLI Commands (`src/commands.ts`) — `registerCommand`

```ts
api.registerCommand({
  name: "voiceclaw",
  description: "Control VoiceClaw voice assistant",
  acceptsArgs: true,
  requireAuth: true,
  handler: async (ctx) => {
    const sub = (ctx.args ?? "").trim().split(/\s+/)[0];
    switch (sub) {
      case "start":  return { text: await bridge.start(getConfig(ctx)) };
      case "stop":   return { text: await bridge.stop() };
      case "status": return { text: bridge.getStatus() };
      default:       return { text: "Usage: /voiceclaw start|stop|status" };
    }
  },
});
```

Also registers CLI command for `openclaw voiceclaw`:

```ts
api.registerCli(({ program }) => {
  const cmd = program.command("voiceclaw");
  cmd.command("start").action(async () => { /* start bridge */ });
  cmd.command("stop").action(async () => { /* stop bridge */ });
  cmd.command("status").action(async () => { /* print status */ });
  cmd.command("install").action(async () => { /* run install-python.sh */ });
}, { commands: ["voiceclaw"] });
```

### 3.4 Gateway RPC Methods (`src/gateway-methods.ts`) — `registerGatewayMethod`

```ts
api.registerGatewayMethod("voiceclaw.status", ({ respond }) => {
  respond(true, {
    running: bridge.isRunning(),
    pid: bridge.getPid(),
    uptime: bridge.getUptime(),
    sttEngine: bridge.currentConfig?.stt?.engine,
    ttsEngine: bridge.currentConfig?.tts?.engine,
  });
});

api.registerGatewayMethod("voiceclaw.config", ({ params, respond }) => {
  if (params?.action === "get") {
    respond(true, bridge.currentConfig);
  } else if (params?.action === "set") {
    bridge.updateConfig(params.config);
    respond(true, { updated: true });
  }
});
```

### 3.5 Agent Tool (`src/tools.ts`) — `voice_speak`

```ts
api.registerTool({
  name: "voice_speak",
  description: "Speak text aloud via TTS. Use when the user is in voice mode.",
  parameters: {
    type: "object",
    properties: {
      text: { type: "string", description: "Text to speak" },
      voice: { type: "string", description: "TTS voice override (optional)" },
    },
    required: ["text"],
  },
  handler: async ({ text, voice }) => {
    if (!bridge.isRunning()) {
      return { error: "VoiceClaw is not running. Use /voiceclaw start first." };
    }
    const result = await bridge.call("tts.speak", { text, voice });
    return { ok: true, duration: result.duration };
  },
});
```

## 4. Python ↔ Node.js Bridge Strategy

### Architecture: JSON-RPC over stdio

```
┌──────────────────┐     stdio (JSON-RPC)     ┌──────────────────────┐
│   Node.js (TS)   │ ◄──────────────────────► │   Python (server.py) │
│   bridge.ts       │   stdin/stdout            │                      │
│                    │                           │   ├── vad.py         │
│   Spawns child    │   Requests:               │   ├── stt.py         │
│   process         │   {"method":"stt.transcribe",│   ├── tts.py     │
│                    │    "params":{...}}        │   ├── audio.py       │
│                    │                           │   └── wakeword.py    │
│                    │   Events (notifications): │                      │
│                    │   {"event":"wake_word",   │   PyAudio            │
│                    │    "data":{...}}          │   Silero VAD         │
│                    │                           │   SenseVoice/Whisper │
│                    │   stderr → logger         │   Edge TTS           │
└──────────────────┘                           └──────────────────────┘
```

### Why stdio JSON-RPC?

| Alternative | Pros | Cons |
|---|---|---|
| **stdio JSON-RPC** ✅ | Zero deps, no ports, simple | Slightly verbose |
| HTTP/WebSocket | Familiar | Port management, extra dep |
| gRPC | Fast, typed | Heavy setup, protobuf |
| Shared memory | Fastest | Complex, platform-specific |

### Bridge Protocol

**Request (Node → Python):**
```json
{"jsonrpc":"2.0","id":1,"method":"stt.transcribe","params":{"audio_path":"/tmp/chunk.wav"}}
```

**Response (Python → Node):**
```json
{"jsonrpc":"2.0","id":1,"result":{"text":"오늘 날씨 어때?","engine":"sensevoice","elapsed":1.2}}
```

**Event/Notification (Python → Node, no id):**
```json
{"jsonrpc":"2.0","method":"event","params":{"type":"wake_word","data":{"confidence":0.95}}}
{"jsonrpc":"2.0","method":"event","params":{"type":"speech_start"}}
{"jsonrpc":"2.0","method":"event","params":{"type":"utterance","data":{"text":"날씨 알려줘","audio_path":"/tmp/utt.wav"}}}
```

### Bridge Methods

| Method | Direction | Description |
|---|---|---|
| `start` | Node→Py | Start mic listening loop |
| `stop` | Node→Py | Stop listening |
| `stt.transcribe` | Node→Py | Transcribe audio file |
| `tts.speak` | Node→Py | Speak text via TTS |
| `config.update` | Node→Py | Hot-reload config |
| `status` | Node→Py | Get Python process status |
| `event` | Py→Node | Wake word / utterance / error events |

### `bridge.ts` Implementation Sketch

```ts
class PythonBridge {
  private proc: ChildProcess | null = null;
  private requestId = 0;
  private pending = new Map<number, { resolve, reject, timer }>();

  async start(config: VoiceClawConfig) {
    const pythonPath = config.pythonPath ?? path.join(__dirname, "../python/venv/bin/python3");
    this.proc = spawn(pythonPath, ["-m", "voiceclaw.server"], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, VOICECLAW_CONFIG: JSON.stringify(config) },
    });
    this.proc.stdout.on("data", (chunk) => this.handleOutput(chunk));
    this.proc.stderr.on("data", (chunk) => logger.debug(chunk.toString()));
    await this.call("start", config);
  }

  async call(method: string, params?: any): Promise<any> {
    const id = ++this.requestId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("timeout")), 30000);
      this.pending.set(id, { resolve, reject, timer });
      this.proc!.stdin!.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }

  private handleOutput(chunk: Buffer) {
    // Parse JSON-RPC responses and events
    // Route events to service event handler (wake word → agent message)
  }
}
```

### Python Server (`python/voiceclaw/server.py`) Sketch

```python
"""JSON-RPC stdio server for VoiceClaw."""
import json, sys, threading
from .audio import AudioManager
from .vad import SileroVAD
from .stt import create_stt_engine
from .tts import create_tts_engine
from .wakeword import WakeWordDetector

class Server:
    def __init__(self, config):
        self.vad = SileroVAD(threshold=config.get("vad", {}).get("threshold", 0.5))
        self.stt = create_stt_engine(config.get("stt", {}))
        self.tts = create_tts_engine(config.get("tts", {}))
        self.audio = AudioManager(self.vad)
        self.wakeword = WakeWordDetector(config.get("wakeWord", "hey claw"), self.stt)
        self.running = False

    def send(self, msg):
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def emit(self, event_type, data=None):
        self.send({"jsonrpc": "2.0", "method": "event", "params": {"type": event_type, "data": data}})

    def handle_request(self, req):
        method = req["method"]
        params = req.get("params", {})
        rid = req.get("id")

        if method == "start":
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
            return {"status": "started"}
        elif method == "stop":
            self.running = False
            return {"status": "stopped"}
        elif method == "tts.speak":
            duration = self.tts.speak(params["text"], voice=params.get("voice"))
            return {"duration": duration}
        elif method == "stt.transcribe":
            text = self.stt.transcribe(params["audio_path"])
            return {"text": text, "engine": self.stt.engine_name}
        elif method == "status":
            return {"running": self.running, "stt_engine": self.stt.engine_name}

    def _listen_loop(self):
        """Continuous mic → VAD → wake word → utterance → event."""
        while self.running:
            audio_file = self.audio.record_speech(timeout=3.0, silence_duration=0.5)
            if not audio_file:
                continue
            if self.wakeword.detect(audio_file):
                self.emit("wake_word")
                utt_file = self.audio.record_speech(timeout=10.0, silence_duration=1.0)
                if utt_file:
                    text = self.stt.transcribe(utt_file)
                    if text.strip():
                        self.emit("utterance", {"text": text, "audio_path": utt_file})

    def run(self):
        for line in sys.stdin:
            req = json.loads(line.strip())
            result = self.handle_request(req)
            if req.get("id") is not None:
                self.send({"jsonrpc": "2.0", "id": req["id"], "result": result})
```

## 5. Event Flow (End-to-End)

```
User says "Hey Claw"
    │
    ▼
[Python] AudioManager → VAD detects speech → record chunk
    │
    ▼
[Python] WakeWordDetector → STT → matches "hey claw"
    │
    ▼
[Python] emit("wake_word") → stdio → [Node.js]
    │
    ▼
[Python] Record utterance → STT → emit("utterance", {text})
    │
    ▼
[Node.js] bridge receives "utterance" event
    │
    ▼
[Node.js] Service injects message into Gateway agent session
    │  (api.runtime.sendAgentMessage or equivalent)
    │
    ▼
[Gateway] Agent processes message → generates response
    │
    ▼
[Agent] Calls voice_speak tool → bridge.call("tts.speak", {text})
    │
    ▼
[Python] TTS engine → audio playback → speaker
```

## 6. Config in `openclaw.yaml`

```yaml
plugins:
  entries:
    voiceclaw:
      enabled: true
      config:
        stt:
          engine: sensevoice     # sensevoice | faster-whisper | whisper
          model: small
          language: ko
        tts:
          engine: edge-tts       # edge-tts | piper | say
          voice: ko-KR-SunHiNeural
        wakeWord: "hey claw"
        vad:
          threshold: 0.5
          silenceDuration: 0.5
        autoStart: false
        pythonPath: null         # null = use bundled venv
```

## 7. Installation Flow

```bash
# Install plugin
openclaw plugins install @openclaw/voiceclaw

# Install Python dependencies (auto-runs on first start too)
openclaw voiceclaw install

# Start
openclaw voiceclaw start

# Or via chat
/voiceclaw start
```

`openclaw voiceclaw install` runs `scripts/install-python.sh`:
1. Creates `python/venv` with `python3 -m venv`
2. `pip install -r python/requirements.txt`
3. Downloads Silero VAD model
4. Validates: PyAudio, torch, STT engine, TTS engine

## 8. Skill Definition (`skills/voiceclaw/SKILL.md`)

```markdown
---
name: voiceclaw
description: Voice assistant — listen for speech and speak responses
tools:
  - voice_speak
---

# VoiceClaw

You have access to a voice assistant. When the user is in voice mode
(VoiceClaw is running), their messages may come from speech recognition.

## voice_speak

Speak text aloud through the user's speakers. Use this when:
- The user is in voice conversation mode
- You want to give an audible response
- The user explicitly asks you to "say" something

Parameters:
- `text` (required): Text to speak
- `voice` (optional): TTS voice override
```

## 9. Migration from openclaw-voice

| openclaw-voice (v0.6) | voiceclaw plugin |
|---|---|
| `src/main.py` (monolith) | `python/voiceclaw/server.py` + modules |
| `bin/cli.js` (spawn) | `src/bridge.ts` (JSON-RPC) |
| `voice.env` config | `openclaw.yaml` plugin config |
| Direct Gateway HTTP | Plugin API (`api.runtime.*`) |
| Standalone process | In-process service + child Python |
| Manual start (`npm start`) | `openclaw voiceclaw start` or auto-start |

## 10. Future Considerations

- **Streaming STT**: WebSocket-based streaming for real-time transcription
- **GPU acceleration**: CUDA/MPS detection in install script
- **Voice cloning**: ElevenLabs / XTTS integration as TTS engine option
- **Multi-device**: Node.js paired device mic input via `nodes` API
- **Interruption**: Barge-in detection (stop TTS when user speaks)
- **Wake word models**: Custom trained models (OpenWakeWord) instead of STT-based
