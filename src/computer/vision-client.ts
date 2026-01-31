import { loadConfig } from "../config/config.js";
import { resolveComputerConfig, type ResolvedComputerConfig } from "./config.js";
import { PythonJsonRpcClient, resolvePythonScriptPath } from "./python-jsonrpc.js";

export type ComputerVisionIngest = {
  screenshotId: string;
};

export type ComputerVisionResolve = {
  screenshotId: string;
  x: number;
  y: number;
};

let visionClient: PythonJsonRpcClient | null = null;

export async function getComputerVisionClient(
  cfg?: ResolvedComputerConfig,
): Promise<PythonJsonRpcClient> {
  if (visionClient) return visionClient;
  const raw = loadConfig();
  const resolved = cfg ?? resolveComputerConfig(raw.computer, raw);
  const scriptPath = await resolvePythonScriptPath("python/grounding_service/server.py");
  visionClient = new PythonJsonRpcClient({
    label: "computer-vision",
    scriptPath,
    pythonPath: resolved.vision.path,
    pythonArgs: resolved.vision.args,
  });
  return visionClient;
}

export async function computerVisionIngest(params: {
  sessionKey: string;
  screenshot: string;
  screenshotId?: string;
  timeoutMs?: number;
}): Promise<ComputerVisionIngest> {
  const raw = loadConfig();
  const cfg = resolveComputerConfig(raw.computer, raw);
  const client = await getComputerVisionClient(cfg);
  const result = (await client.request(
    "ingest_screenshot",
    {
      session_key: params.sessionKey,
      screenshot_b64: params.screenshot,
      screenshot_id: params.screenshotId,
      ocr_wait_timeout_ms: cfg.vision.ocrWaitTimeoutMs,
    },
    params.timeoutMs ?? cfg.vision.timeoutMs,
  )) as ComputerVisionIngest;
  return result;
}

export async function computerVisionResolve(params: {
  sessionKey: string;
  method: "ocr" | "prediction";
  ocrText?: string;
  description?: string;
  screenshotId?: string;
  modelName?: string;
  timeoutMs?: number;
}): Promise<ComputerVisionResolve> {
  const raw = loadConfig();
  const cfg = resolveComputerConfig(raw.computer, raw);
  const client = await getComputerVisionClient(cfg);
  const result = (await client.request(
    "resolve",
    {
      session_key: params.sessionKey,
      method: params.method,
      ocr_text: params.ocrText,
      description: params.description,
      screenshot_id: params.screenshotId,
      ocr_match_threshold: cfg.vision.ocrMatchThreshold,
      ocr_wait_timeout_ms: cfg.vision.ocrWaitTimeoutMs,
      model_name: params.modelName ?? cfg.vision.modelName,
    },
    params.timeoutMs ?? cfg.vision.timeoutMs,
  )) as ComputerVisionResolve;
  return result;
}
