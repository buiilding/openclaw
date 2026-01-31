// @ts-ignore: node types may be unavailable in editor environments
import { spawn } from "node:child_process";
// @ts-ignore: node types may be unavailable in editor environments
import { createInterface } from "node:readline";
// @ts-ignore: node types may be unavailable in editor environments
import { fileURLToPath } from "node:url";
// @ts-ignore: node types may be unavailable in editor environments
import path from "node:path";

import { attachChildProcessBridge } from "../process/child-process-bridge.js";
import { formatSpawnError, spawnWithFallback } from "../process/spawn-utils.js";
import { createSubsystemLogger } from "../logging/subsystem.js";
import { resolveOpenClawPackageRoot } from "../infra/openclaw-root.js";

type JsonRpcResponse = {
  jsonrpc?: string;
  id?: string | number | null;
  result?: unknown;
  error?: { code?: number; message?: string; data?: unknown };
};

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
  timer?: ReturnType<typeof setTimeout>;
};

type PythonRpcOptions = {
  label: string;
  scriptPath: string;
  pythonPath?: string;
  pythonArgs?: string[];
};

const log = createSubsystemLogger("computer/python-rpc");

export class PythonJsonRpcClient {
  private readonly label: string;
  private readonly scriptPath: string;
  private readonly pythonPath?: string;
  private readonly pythonArgs: string[];
  private child: ReturnType<typeof spawn> | null = null;
  private pending = new Map<string, PendingRequest>();
  private nextId = 1;

  constructor(options: PythonRpcOptions) {
    this.label = options.label;
    this.scriptPath = options.scriptPath;
    this.pythonPath = options.pythonPath;
    this.pythonArgs = options.pythonArgs ?? [];
  }

  async request(
    method: string,
    params?: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<unknown> {
    await this.ensureStarted();
    const id = `${this.label}-${this.nextId++}`;
    const payload = {
      jsonrpc: "2.0",
      id,
      method,
      params: params ?? {},
    };
    const child = this.child;
    if (!child || !child.stdin) throw new Error(`${this.label} sidecar unavailable`);
    const stdin = child.stdin;

    return await new Promise((resolve, reject) => {
      const timer =
        typeof timeoutMs === "number" && Number.isFinite(timeoutMs)
          ? setTimeout(
              () => {
                this.pending.delete(id);
                reject(new Error(`${this.label} request timed out`));
              },
              Math.max(1, Math.floor(timeoutMs)),
            )
          : undefined;
      this.pending.set(id, { resolve, reject, timer });
      try {
        if (!stdin) throw new Error(`${this.label} sidecar stdin unavailable`);
        stdin.write(`${JSON.stringify(payload)}\n`);
      } catch (err) {
        if (timer) clearTimeout(timer);
        this.pending.delete(id);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });
  }

  async stop(): Promise<void> {
    const child = this.child;
    if (!child) return;
    this.child = null;
    for (const pending of this.pending.values()) {
      pending.reject(new Error(`${this.label} sidecar stopped`));
      if (pending.timer) clearTimeout(pending.timer);
    }
    this.pending.clear();
    try {
      child.kill();
    } catch {
      // ignore
    }
  }

  private async ensureStarted(): Promise<void> {
    if (this.child && !this.child.killed) return;
    const candidates = await resolvePythonCommandCandidates({
      pythonPath: this.pythonPath,
      pythonArgs: this.pythonArgs,
      scriptPath: this.scriptPath,
    });
    let lastError: unknown = null;
    for (const candidate of candidates) {
      try {
        const procEnv = getNodeProcess()?.env ?? {};
        const result = await spawnWithFallback({
          argv: candidate,
          options: {
            stdio: ["pipe", "pipe", "pipe"],
            env: { ...procEnv, PYTHONUNBUFFERED: "1" },
          },
          spawnImpl: spawn,
        });
        this.child = result.child;
        break;
      } catch (err) {
        lastError = err;
        log.warn(`Failed to spawn ${this.label} sidecar`, {
          error: formatSpawnError(err),
          argv: candidate.join(" "),
        });
      }
    }
    if (!this.child) {
      throw new Error(
        `${this.label} sidecar failed to start: ${lastError ? formatSpawnError(lastError) : "unknown error"}`,
      );
    }
    attachChildProcessBridge(this.child, {
      onSignal: (signal) => log.info(`Forwarding ${signal} to ${this.label} sidecar`),
    });
    this.child.stderr?.on("data", (chunk: unknown) => {
      const text = String(chunk).trim();
      if (text) log.warn(`[${this.label}] ${text}`);
    });
    const rl = createInterface({ input: this.child.stdout! });
    rl.on("line", (line: string) => this.handleLine(line));
    this.child.once("exit", (code: number | null, signal: string | null) => {
      log.warn(`${this.label} sidecar exited`, { code, signal });
      void this.stop();
    });
    this.child.once("error", (err: Error) => {
      log.error(`${this.label} sidecar spawn error`, { error: String(err) });
      void this.stop();
    });
  }

  private handleLine(line: string) {
    const trimmed = line.trim();
    if (!trimmed) return;
    let payload: JsonRpcResponse | null = null;
    try {
      payload = JSON.parse(trimmed) as JsonRpcResponse;
    } catch {
      log.warn(`Non-JSON response from ${this.label} sidecar`, { line: trimmed.slice(0, 200) });
      return;
    }
    const id = payload?.id;
    if (!id) return;
    const pending = this.pending.get(String(id));
    if (!pending) return;
    this.pending.delete(String(id));
    if (pending.timer) clearTimeout(pending.timer);
    if (payload.error) {
      const message = payload.error.message ?? "RPC error";
      pending.reject(new Error(`${this.label} RPC error: ${message}`));
      return;
    }
    pending.resolve(payload.result);
  }
}

async function resolvePythonCommandCandidates(params: {
  pythonPath?: string;
  pythonArgs?: string[];
  scriptPath: string;
}): Promise<string[][]> {
  const pythonArgs = Array.isArray(params.pythonArgs) ? params.pythonArgs : [];
  const configured =
    params.pythonPath?.trim() || getNodeProcess()?.env?.OPENCLAW_PYTHON?.trim() || "";
  if (configured) {
    return [[configured, ...pythonArgs, params.scriptPath]];
  }
  return [
    ["python3", ...pythonArgs, params.scriptPath],
    ["python", ...pythonArgs, params.scriptPath],
  ];
}

export async function resolvePythonScriptPath(relativePath: string): Promise<string> {
  const proc = getNodeProcess();
  const root = await resolveOpenClawPackageRoot({
    cwd: proc?.cwd?.(),
    argv1: proc?.argv?.[1],
    moduleUrl: import.meta.url,
  });
  if (!root) {
    const here = path.dirname(fileURLToPath(import.meta.url));
    return path.join(here, "..", "..", relativePath);
  }
  return path.join(root, relativePath);
}

function getNodeProcess():
  | { env?: Record<string, string | undefined>; argv?: string[]; cwd?: () => string }
  | undefined {
  return (
    globalThis as {
      process?: { env?: Record<string, string | undefined>; argv?: string[]; cwd?: () => string };
    }
  ).process;
}
