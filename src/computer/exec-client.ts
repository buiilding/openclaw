import { loadConfig } from "../config/config.js";
import { resolveComputerConfig, type ResolvedComputerConfig } from "./config.js";
import { PythonJsonRpcClient, resolvePythonScriptPath } from "./python-jsonrpc.js";

export type ComputerSnapshot = {
  screenshot: string;
  screenshotId: string;
  mimeType: string;
  width: number;
  height: number;
  systemState: Record<string, unknown>;
};

export type ComputerActResult = {
  ok: boolean;
  kind: string;
  message?: string;
};

let execClient: PythonJsonRpcClient | null = null;

export async function getComputerExecClient(
  cfg?: ResolvedComputerConfig,
): Promise<PythonJsonRpcClient> {
  if (execClient) return execClient;
  const raw = loadConfig();
  const resolved = cfg ?? resolveComputerConfig(raw.computer, raw);
  const scriptPath = await resolvePythonScriptPath("python/computer_exec/server.py");
  execClient = new PythonJsonRpcClient({
    label: "computer-exec",
    scriptPath,
    pythonPath: resolved.exec.path,
    pythonArgs: resolved.exec.args,
  });
  return execClient;
}

export async function computerSnapshot(params?: {
  delayMs?: number;
  timeoutMs?: number;
}): Promise<ComputerSnapshot> {
  const raw = loadConfig();
  const cfg = resolveComputerConfig(raw.computer, raw);
  const client = await getComputerExecClient(cfg);
  const result = (await client.request(
    "snapshot",
    {
      delay_ms: params?.delayMs,
    },
    params?.timeoutMs ?? cfg.exec.timeoutMs,
  )) as ComputerSnapshot;
  return result;
}

export async function computerAct(
  request: Record<string, unknown>,
  params?: { timeoutMs?: number },
): Promise<ComputerActResult> {
  const raw = loadConfig();
  const cfg = resolveComputerConfig(raw.computer, raw);
  const client = await getComputerExecClient(cfg);
  const result = (await client.request(
    "act",
    request,
    params?.timeoutMs ?? cfg.exec.timeoutMs,
  )) as ComputerActResult;
  return result;
}
