import { loadConfig } from "../../config/config.js";
import { saveMediaBuffer } from "../../media/store.js";
import { resolveComputerConfig } from "../../computer/config.js";
import {
  computerAct,
  computerSnapshot,
  getComputerExecClient,
} from "../../computer/exec-client.js";
import {
  computerVisionIngest,
  computerVisionResolve,
  getComputerVisionClient,
} from "../../computer/vision-client.js";
import { createSubsystemLogger } from "../../logging/subsystem.js";
import { ComputerToolSchema } from "./computer-tool.schema.js";
import {
  type AnyAgentTool,
  imageResult,
  jsonResult,
  readNumberParam,
  readStringParam,
} from "./common.js";
// @ts-ignore: editor may not have deps installed
import { Buffer } from "node:buffer";

const log = createSubsystemLogger("agents/tools/computer");

const COORDINATE_KINDS = new Set(["click", "double_click", "right_click", "move", "drag"]);

function formatSystemStateText(systemState: Record<string, unknown>, actionLine?: string): string {
  const activeWindow =
    typeof systemState.active_window === "string" ? systemState.active_window : "";
  const mousePosition =
    typeof systemState.mouse_position === "string" ? systemState.mouse_position : "";
  const screenResolution =
    typeof systemState.screen_resolution === "string" ? systemState.screen_resolution : "";
  const time = typeof systemState.time === "string" ? systemState.time : "";
  const parts = [
    actionLine?.trim() ? actionLine.trim() : undefined,
    activeWindow ? `Active window: ${activeWindow}` : undefined,
    mousePosition ? `Mouse: ${mousePosition}` : undefined,
    screenResolution ? `Screen: ${screenResolution}` : undefined,
    time ? `Time: ${time}` : undefined,
  ].filter(Boolean);
  return parts.join(" | ");
}

export function createComputerTool(options?: { agentSessionKey?: string }): AnyAgentTool {
  return {
    label: "Computer",
    name: "computer",
    description: [
      "Control the local computer using snapshots + coordinate-based actions (click/type/scroll).",
      "Use action=snapshot to capture the current screen with system state.",
      "Use action=act with request.kind to click/type/scroll/press/hotkey/drag/wait.",
      "Rely on system state (active window, mouse position, screen resolution) to avoid unnecessary actions.",
      "Prefer keybinds and app controls over manual clicking when reliable.",
      "Ensure text inputs are focused before typing; verify typed text appears in the next screenshot.",
      'For visible text targets: use find_coordinates_by="ocr" with exact ocr_text (no description).',
      'For non-text targets: use find_coordinates_by="prediction" with a detailed visual description (no ocr_text).',
      "Use manual x/y only as a fallback when OCR or prediction fails.",
      "If an action should trigger UI changes, include waitMs so the next screenshot reflects the change.",
    ].join(" "),
    parameters: ComputerToolSchema,
    execute: async (_toolCallId: string, args: unknown) => {
      const params = args as Record<string, unknown>;
      const action = readStringParam(params, "action", { required: true });
      const sessionKey =
        typeof options?.agentSessionKey === "string" && options.agentSessionKey.trim()
          ? options.agentSessionKey.trim()
          : "main";
      const cfgRaw = loadConfig();
      const cfg = resolveComputerConfig(cfgRaw.computer, cfgRaw);
      if (!cfg.enabled) {
        throw new Error(
          "Computer control is disabled. Set computer.enabled=true in ~/.openclaw/openclaw.json.",
        );
      }

      const timeoutMs = readNumberParam(params, "timeoutMs");

      if (action === "status") {
        const execClient = await getComputerExecClient(cfg);
        const visionClient = await getComputerVisionClient(cfg);
        const execStatus = await execClient.request("status", {}, timeoutMs ?? cfg.exec.timeoutMs);
        const visionStatus = await visionClient.request(
          "status",
          {},
          timeoutMs ?? cfg.vision.timeoutMs,
        );
        return jsonResult({ exec: execStatus, vision: visionStatus });
      }

      if (action === "snapshot") {
        const delayMs = readNumberParam(params, "delayMs", { integer: true });
        const snapshot = await computerSnapshot({
          delayMs,
          timeoutMs,
        });
        const ingest = await computerVisionIngest({
          sessionKey,
          screenshot: snapshot.screenshot,
          screenshotId: snapshot.screenshotId,
          timeoutMs,
        });
        const buffer = Buffer.from(snapshot.screenshot, "base64");
        const saved = await saveMediaBuffer(buffer, snapshot.mimeType ?? "image/jpeg", "computer");
        return await imageResult({
          label: "computer:snapshot",
          path: saved.path,
          base64: snapshot.screenshot,
          mimeType: snapshot.mimeType ?? "image/jpeg",
          extraText: formatSystemStateText(snapshot.systemState),
          details: {
            screenshotId: ingest.screenshotId,
            systemState: snapshot.systemState,
            width: snapshot.width,
            height: snapshot.height,
          },
        });
      }

      if (action !== "act") {
        throw new Error(`Unknown computer action: ${action}`);
      }

      const request = params.request as Record<string, unknown> | undefined;
      if (!request || typeof request !== "object") {
        throw new Error("request required for computer act");
      }
      const kind = readStringParam(request, "kind", { required: true });
      const findMethod = readStringParam(request, "find_coordinates_by");
      const modelName = readStringParam(request, "model_name");
      let x = readNumberParam(request, "x");
      let y = readNumberParam(request, "y");
      const endX = readNumberParam(request, "endX");
      const endY = readNumberParam(request, "endY");
      if (typeof x !== "number" && typeof endX === "number") x = endX;
      if (typeof y !== "number" && typeof endY === "number") y = endY;

      if (findMethod && findMethod !== "manual" && COORDINATE_KINDS.has(kind)) {
        const ocrText = readStringParam(request, "ocr_text", { allowEmpty: true });
        const description = readStringParam(request, "description", { allowEmpty: true });
        const resolved = await computerVisionResolve({
          sessionKey,
          method: findMethod === "ocr" ? "ocr" : "prediction",
          ocrText,
          description,
          modelName,
          timeoutMs,
        });
        x = resolved.x;
        y = resolved.y;
      }

      if (COORDINATE_KINDS.has(kind)) {
        if (typeof x !== "number" || typeof y !== "number") {
          throw new Error("x/y coordinates required for this action");
        }
      }

      const execRequest = {
        ...request,
        kind,
        x,
        y,
      };
      delete (execRequest as Record<string, unknown>).find_coordinates_by;
      delete (execRequest as Record<string, unknown>).ocr_text;
      delete (execRequest as Record<string, unknown>).description;
      delete (execRequest as Record<string, unknown>).model_name;

      const actResult = await computerAct(execRequest, {
        timeoutMs,
      });

      const waitMs =
        readNumberParam(request, "waitMs", { integer: true }) ??
        readNumberParam(params, "delayMs", { integer: true });
      const snapshot = await computerSnapshot({
        delayMs: waitMs,
        timeoutMs,
      });
      const ingest = await computerVisionIngest({
        sessionKey,
        screenshot: snapshot.screenshot,
        screenshotId: snapshot.screenshotId,
        timeoutMs,
      });
      const buffer = Buffer.from(snapshot.screenshot, "base64");
      const saved = await saveMediaBuffer(buffer, snapshot.mimeType ?? "image/jpeg", "computer");

      log.info("Computer action executed", { kind, actResult });
      const actionMessage =
        actResult?.message && typeof actResult.message === "string" ? actResult.message.trim() : "";
      const actionLine = actionMessage
        ? `Action: ${kind} (${actionMessage})`
        : `Action: ${kind} (${actResult.ok ? "ok" : "failed"})`;
      return await imageResult({
        label: "computer:act",
        path: saved.path,
        base64: snapshot.screenshot,
        mimeType: snapshot.mimeType ?? "image/jpeg",
        extraText: formatSystemStateText(snapshot.systemState, actionLine),
        details: {
          action: kind,
          actionResult: actResult,
          screenshotId: ingest.screenshotId,
          systemState: snapshot.systemState,
          width: snapshot.width,
          height: snapshot.height,
        },
      });
    },
  };
}
