/**
 * Python ↔ Node.js JSON-RPC bridge over stdio.
 *
 * Spawns python -m voiceclaw.engine as a child process.
 * Communication: newline-delimited JSON-RPC on stdin/stdout.
 * stderr → logger.
 */

import { ChildProcess, spawn } from "child_process";
import { EventEmitter } from "events";
import * as path from "path";
import * as readline from "readline";
import type {
  VoiceClawConfig,
  JsonRpcRequest,
  JsonRpcResponse,
  JsonRpcNotification,
  BridgeStatus,
  VoiceEvent,
} from "./types";

const RPC_TIMEOUT = 30_000;

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class PythonBridge extends EventEmitter {
  private proc: ChildProcess | null = null;
  private requestId = 0;
  private pending = new Map<number, PendingRequest>();
  private startTime: number | null = null;
  public currentConfig: VoiceClawConfig | null = null;
  private logger: { info: (...a: unknown[]) => void; warn: (...a: unknown[]) => void; error: (...a: unknown[]) => void; debug: (...a: unknown[]) => void };

  constructor(logger?: any) {
    super();
    this.logger = logger ?? console;
  }

  /** Spawn Python engine process */
  async start(config: VoiceClawConfig): Promise<string> {
    if (this.proc) {
      return "VoiceClaw already running (pid " + this.proc.pid + ")";
    }

    const pythonPath =
      config.pythonPath ??
      path.join(__dirname, "..", "python", "venv", "bin", "python3");

    const engineModule = path.join(__dirname, "..", "python");

    this.logger.info(`[voiceclaw] Starting Python engine: ${pythonPath} -m voiceclaw.engine`);

    this.proc = spawn(pythonPath, ["-m", "voiceclaw.engine"], {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: engineModule,
      env: {
        ...process.env,
        VOICECLAW_CONFIG: JSON.stringify(config),
        PYTHONUNBUFFERED: "1",
      },
    });

    this.currentConfig = config;
    this.startTime = Date.now();

    // Read stdout line-by-line for JSON-RPC
    const rl = readline.createInterface({ input: this.proc.stdout! });
    rl.on("line", (line) => this.handleLine(line));

    // stderr → logger
    this.proc.stderr?.on("data", (chunk: Buffer) => {
      const msg = chunk.toString().trim();
      if (msg) this.logger.debug(`[voiceclaw:py] ${msg}`);
    });

    this.proc.on("exit", (code, signal) => {
      this.logger.info(`[voiceclaw] Python exited: code=${code} signal=${signal}`);
      this.cleanup();
      this.emit("exit", { code, signal });
    });

    this.proc.on("error", (err) => {
      this.logger.error(`[voiceclaw] Python spawn error: ${err.message}`);
      this.cleanup();
    });

    // Wait for ready or timeout
    try {
      await this.call("ping", {}, 10_000);
      return `VoiceClaw started (pid ${this.proc.pid})`;
    } catch {
      return `VoiceClaw started (pid ${this.proc?.pid}) — ping timeout (engine may still be loading)`;
    }
  }

  /** Stop Python process */
  async stop(): Promise<string> {
    if (!this.proc) {
      return "VoiceClaw is not running";
    }
    try {
      await this.call("shutdown", {}, 5_000);
    } catch {
      // force kill
    }
    this.proc.kill("SIGTERM");
    // Give it a moment
    await new Promise((r) => setTimeout(r, 500));
    if (this.proc) {
      this.proc.kill("SIGKILL");
    }
    this.cleanup();
    return "VoiceClaw stopped";
  }

  /** Send JSON-RPC request and wait for response */
  async call(method: string, params?: Record<string, unknown>, timeout?: number): Promise<unknown> {
    if (!this.proc?.stdin?.writable) {
      throw new Error("Python bridge not running");
    }

    const id = ++this.requestId;
    const msg: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`RPC timeout: ${method} (${(timeout ?? RPC_TIMEOUT) / 1000}s)`));
      }, timeout ?? RPC_TIMEOUT);

      this.pending.set(id, { resolve, reject, timer });
      this.proc!.stdin!.write(JSON.stringify(msg) + "\n");
    });
  }

  /** Send a notification (no response expected) */
  notify(method: string, params?: Record<string, unknown>): void {
    if (!this.proc?.stdin?.writable) return;
    const msg: JsonRpcNotification = { jsonrpc: "2.0", method, params };
    this.proc.stdin.write(JSON.stringify(msg) + "\n");
  }

  isRunning(): boolean {
    return this.proc !== null && !this.proc.killed;
  }

  getPid(): number | null {
    return this.proc?.pid ?? null;
  }

  getUptime(): number | null {
    return this.startTime ? Date.now() - this.startTime : null;
  }

  getStatus(): BridgeStatus {
    return {
      running: this.isRunning(),
      pid: this.getPid(),
      uptime: this.getUptime(),
      config: this.currentConfig,
    };
  }

  getStatusText(): string {
    if (!this.isRunning()) return "VoiceClaw is not running";
    const uptime = this.getUptime();
    const secs = uptime ? Math.floor(uptime / 1000) : 0;
    const mins = Math.floor(secs / 60);
    const uptimeStr = mins > 0 ? `${mins}m ${secs % 60}s` : `${secs}s`;
    return [
      `VoiceClaw running (pid ${this.getPid()}, uptime ${uptimeStr})`,
      `  STT: ${this.currentConfig?.stt?.engine ?? "sensevoice"}`,
      `  TTS: ${this.currentConfig?.tts?.engine ?? "edge-tts"}`,
      `  Wake: ${this.currentConfig?.wakeWord ?? "미르야"}`,
    ].join("\n");
  }

  // ── Internal ──

  private handleLine(line: string): void {
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      this.logger.debug(`[voiceclaw:py:stdout] ${line}`);
      return;
    }

    // Response to a request
    if (msg.id != null && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) {
        p.reject(new Error(msg.error.message ?? "RPC error"));
      } else {
        p.resolve(msg.result);
      }
      return;
    }

    // Notification / event from Python
    if (msg.method === "event" && msg.params) {
      const event = msg.params as VoiceEvent;
      this.emit("event", event);
      this.emit(event.type, "data" in event ? event.data : {});
      return;
    }

    // Other notification methods
    if (msg.method) {
      this.emit(msg.method, msg.params);
    }
  }

  private cleanup(): void {
    // Reject all pending
    for (const [id, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(new Error("Bridge closed"));
    }
    this.pending.clear();
    this.proc = null;
    this.startTime = null;
  }
}
