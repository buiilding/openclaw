import type { ComputerConfig, OpenClawConfig } from "../config/config.js";

export type ResolvedComputerConfig = {
  enabled: boolean;
  exec: {
    path?: string;
    args: string[];
    timeoutMs: number;
  };
  vision: {
    path?: string;
    args: string[];
    timeoutMs: number;
    ocrMatchThreshold: number;
    ocrWaitTimeoutMs: number;
    modelName?: string;
  };
};

const DEFAULT_EXEC_TIMEOUT_MS = 20_000;
const DEFAULT_VISION_TIMEOUT_MS = 45_000;
const DEFAULT_OCR_MATCH_THRESHOLD = 0.8;
const DEFAULT_OCR_WAIT_TIMEOUT_MS = 5_000;
const DEFAULT_EXEC_PYTHON_PATH = "/home/peter/miniconda3/envs/computer-exec/bin/python";
const DEFAULT_VISION_PYTHON_PATH = "/home/peter/miniconda3/envs/computer-vision/bin/python";

function readEnv(key: string): string | undefined {
  const env =
    (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ??
    undefined;
  const raw = env?.[key];
  return raw?.trim() || undefined;
}

function resolvePythonPath(
  configured: string | undefined,
  envKey: string,
  fallback: string,
): string | undefined {
  return configured?.trim() || readEnv(envKey) || fallback;
}

export function resolveComputerConfig(
  cfg: ComputerConfig | undefined,
  _rootConfig?: OpenClawConfig,
): ResolvedComputerConfig {
  const enabled = cfg?.enabled === true;
  const execArgs = Array.isArray(cfg?.exec?.args) ? cfg?.exec?.args.map((arg) => String(arg)) : [];
  const visionArgs = Array.isArray(cfg?.vision?.args)
    ? cfg?.vision?.args.map((arg) => String(arg))
    : [];
  return {
    enabled,
    exec: {
      path: resolvePythonPath(
        cfg?.exec?.path,
        "OPENCLAW_COMPUTER_EXEC_PYTHON",
        DEFAULT_EXEC_PYTHON_PATH,
      ),
      args: execArgs,
      timeoutMs:
        typeof cfg?.exec?.timeoutMs === "number" && Number.isFinite(cfg.exec.timeoutMs)
          ? Math.max(1, Math.floor(cfg.exec.timeoutMs))
          : DEFAULT_EXEC_TIMEOUT_MS,
    },
    vision: {
      path: resolvePythonPath(
        cfg?.vision?.path,
        "OPENCLAW_COMPUTER_VISION_PYTHON",
        DEFAULT_VISION_PYTHON_PATH,
      ),
      args: visionArgs,
      timeoutMs:
        typeof cfg?.vision?.timeoutMs === "number" && Number.isFinite(cfg.vision.timeoutMs)
          ? Math.max(1, Math.floor(cfg.vision.timeoutMs))
          : DEFAULT_VISION_TIMEOUT_MS,
      ocrMatchThreshold:
        typeof cfg?.vision?.ocrMatchThreshold === "number" &&
        Number.isFinite(cfg.vision.ocrMatchThreshold)
          ? Math.min(1, Math.max(0, cfg.vision.ocrMatchThreshold))
          : DEFAULT_OCR_MATCH_THRESHOLD,
      ocrWaitTimeoutMs:
        typeof cfg?.vision?.ocrWaitTimeoutMs === "number" &&
        Number.isFinite(cfg.vision.ocrWaitTimeoutMs)
          ? Math.max(1, Math.floor(cfg.vision.ocrWaitTimeoutMs))
          : DEFAULT_OCR_WAIT_TIMEOUT_MS,
      modelName: cfg?.vision?.modelName?.trim() || undefined,
    },
  };
}
