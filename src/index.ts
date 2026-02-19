/**
 * VoiceClaw — OpenClaw voice assistant plugin entry point.
 *
 * Registers:
 * - Service: Python process lifecycle (spawn/kill)
 * - Command: /voiceclaw start|stop|status
 * - Gateway methods: voiceclaw.status, voiceclaw.config
 * - HTTP handler: /voiceclaw (status page)
 */

import { PythonBridge } from "./bridge";
import type { VoiceClawConfig } from "./types";

export default function register(api: any) {
  const logger = api.logger ?? console;
  const bridge = new PythonBridge(logger);

  /** Resolve config from plugin settings */
  function getConfig(): VoiceClawConfig {
    return api.config?.plugins?.entries?.voiceclaw?.config ?? {};
  }

  // ── Service: Python process lifecycle ──

  api.registerService({
    id: "voiceclaw",
    start: async () => {
      const config = getConfig();

      // Forward utterances to gateway agent
      bridge.on("utterance", async (data: { text: string; session_id?: string }) => {
        if (!data.text?.trim()) return;
        logger.info(`[voiceclaw] Utterance: "${data.text}"`);
        try {
          const agentId = config.agentId ?? "main";
          const sessionKey = config.sessionKey;
          // Use gateway API to send message to agent
          const result = await api.runtime?.sendMessage?.({
            agentId,
            sessionKey,
            message: data.text,
            channel: "voice",
            metadata: { source: "voiceclaw", sessionId: data.session_id },
          });
          if (result?.text) {
            bridge.notify("speak", { text: result.text });
          }
        } catch (err: any) {
          logger.warn(`[voiceclaw] Agent send failed: ${err.message}`);
        }
      });

      bridge.on("wake_word", () => {
        logger.info("[voiceclaw] Wake word detected");
      });

      if (config.autoStart) {
        const msg = await bridge.start(config);
        logger.info(`[voiceclaw] Auto-start: ${msg}`);
      } else {
        logger.info("[voiceclaw] Service registered (use /voiceclaw start to begin)");
      }
    },
    stop: async () => {
      await bridge.stop();
      logger.info("[voiceclaw] Service stopped");
    },
  });

  // ── Command: /voiceclaw start|stop|status ──

  api.registerCommand({
    name: "voiceclaw",
    description: "Control VoiceClaw voice assistant",
    acceptsArgs: true,
    requireAuth: true,
    handler: async (ctx: any) => {
      const sub = (ctx.args ?? "").trim().split(/\s+/)[0];
      switch (sub) {
        case "start": {
          const msg = await bridge.start(getConfig());
          return { text: msg };
        }
        case "stop": {
          const msg = await bridge.stop();
          return { text: msg };
        }
        case "status":
          return { text: bridge.getStatusText() };
        default:
          return { text: "Usage: /voiceclaw start|stop|status" };
      }
    },
  });

  // ── Gateway methods: voiceclaw.status, voiceclaw.config ──

  api.registerGatewayMethod("voiceclaw.status", ({ respond }: any) => {
    respond(true, bridge.getStatus());
  });

  api.registerGatewayMethod("voiceclaw.config", ({ params, respond }: any) => {
    if (params?.action === "get") {
      respond(true, bridge.currentConfig ?? getConfig());
    } else if (params?.action === "set" && params.config) {
      bridge.currentConfig = { ...bridge.currentConfig, ...params.config };
      if (bridge.isRunning()) {
        bridge.notify("config.update", params.config);
      }
      respond(true, { updated: true });
    } else {
      respond(false, { error: "Use action: 'get' or 'set'" });
    }
  });

  // ── HTTP handler: /voiceclaw status page ──

  api.registerHttpHandler({
    path: "/voiceclaw",
    method: "GET",
    handler: (_req: any, res: any) => {
      const status = bridge.getStatus();
      const html = `<!DOCTYPE html>
<html><head><title>VoiceClaw</title>
<style>body{font-family:system-ui;max-width:600px;margin:40px auto;padding:0 20px}
.status{padding:12px;border-radius:8px;margin:16px 0}
.running{background:#d4edda;color:#155724}.stopped{background:#f8d7da;color:#721c24}
dt{font-weight:bold;margin-top:8px}dd{margin:0 0 4px 16px}</style></head>
<body>
<h1>🎙️ VoiceClaw</h1>
<div class="status ${status.running ? "running" : "stopped"}">
  ${status.running ? "🟢 Running" : "🔴 Stopped"}
  ${status.pid ? ` (pid ${status.pid})` : ""}
</div>
<dl>
  <dt>STT</dt><dd>${status.config?.stt?.engine ?? "sensevoice"}</dd>
  <dt>TTS</dt><dd>${status.config?.tts?.engine ?? "edge-tts"}</dd>
  <dt>Wake Word</dt><dd>${status.config?.wakeWord ?? "미르야"}</dd>
  <dt>Uptime</dt><dd>${status.uptime ? Math.floor(status.uptime / 1000) + "s" : "—"}</dd>
</dl>
</body></html>`;
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(html);
    },
  });
}
