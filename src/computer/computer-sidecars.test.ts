import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { PythonJsonRpcClient, resolvePythonScriptPath } from "./python-jsonrpc.js";

const runSidecarTests = process.env.OPENCLAW_RUN_SIDECAR_TESTS === "1";
const fallbackPython = process.env.OPENCLAW_SIDECAR_TEST_PYTHON?.trim() || undefined;
const execPython =
  process.env.OPENCLAW_SIDECAR_TEST_PYTHON_EXEC?.trim() || fallbackPython || undefined;
const visionPython =
  process.env.OPENCLAW_SIDECAR_TEST_PYTHON_VISION?.trim() || fallbackPython || undefined;

describe(runSidecarTests ? "computer sidecars" : "computer sidecars (skipped)", () => {
  if (!runSidecarTests) {
    test.skip("set OPENCLAW_RUN_SIDECAR_TESTS=1 to run sidecar tests", () => {
      expect(true).toBe(true);
    });
    return;
  }

  let execClient: PythonJsonRpcClient;
  let visionClient: PythonJsonRpcClient;

  beforeAll(async () => {
    execClient = new PythonJsonRpcClient({
      label: "test-computer-exec",
      scriptPath: await resolvePythonScriptPath("python/computer_exec/server.py"),
      pythonPath: execPython,
      pythonArgs: ["-u"],
    });
    visionClient = new PythonJsonRpcClient({
      label: "test-computer-vision",
      scriptPath: await resolvePythonScriptPath("python/grounding_service/server.py"),
      pythonPath: visionPython,
      pythonArgs: ["-u"],
    });
  });

  afterAll(async () => {
    await execClient?.stop();
    await visionClient?.stop();
  });

  test("exec sidecar responds to status", async () => {
    const result = (await execClient.request("status", {}, 10_000)) as Record<string, unknown>;
    expect(result?.ok).toBe(true);
    expect(result?.python).toBeTypeOf("string");
  });

  test("vision sidecar responds to status", async () => {
    const result = (await visionClient.request("status", {}, 10_000)) as Record<string, unknown>;
    expect(result?.ok).toBe(true);
    expect(result).toHaveProperty("ocr_available");
  });
});
