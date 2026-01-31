export type ComputerPythonConfig = {
  /** Python executable path (defaults to python3/python fallback). */
  path?: string;
  /** Extra args passed to the python process (e.g., ["-u"]). */
  args?: string[];
  /** Per-request timeout in ms. */
  timeoutMs?: number;
};

export type ComputerVisionConfig = ComputerPythonConfig & {
  /** OCR match threshold (0-1). */
  ocrMatchThreshold?: number;
  /** OCR wait timeout in ms before falling back to on-demand OCR. */
  ocrWaitTimeoutMs?: number;
  /** Vision model name (InternVL-compatible). */
  modelName?: string;
};

export type ComputerConfig = {
  /** Enable computer control tooling. */
  enabled?: boolean;
  /** Execution sidecar (mouse/keyboard/screenshot). */
  exec?: ComputerPythonConfig;
  /** OCR + vision grounding sidecar. */
  vision?: ComputerVisionConfig;
};
