/** VoiceClaw plugin configuration (from openclaw.yaml) */
export interface VoiceClawConfig {
  stt?: {
    engine?: "sensevoice" | "faster-whisper" | "whisper";
    model?: string;
    language?: string;
  };
  tts?: {
    engine?: "edge-tts" | "piper" | "say";
    voice?: string;
  };
  wakeWord?: string;
  vad?: {
    threshold?: number;
    silenceDuration?: number;
  };
  autoStart?: boolean;
  pythonPath?: string;
  agentId?: string;
  sessionKey?: string;
}

/** JSON-RPC 2.0 request */
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: number;
  method: string;
  params?: Record<string, unknown>;
}

/** JSON-RPC 2.0 response */
export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

/** JSON-RPC 2.0 notification (no id) */
export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

/** Bridge status */
export interface BridgeStatus {
  running: boolean;
  pid: number | null;
  uptime: number | null;
  config: VoiceClawConfig | null;
}

/** Python event types */
export type VoiceEvent =
  | { type: "wake_word"; data?: { confidence?: number } }
  | { type: "speech_start" }
  | { type: "speech_end" }
  | { type: "utterance"; data: { text: string; audio_path?: string; session_id?: string } }
  | { type: "error"; data: { message: string } };
