# Computer Tool

The `computer` tool enables OS-level automation using screenshots, OCR, and grounding models.
It mirrors the browser tool flow: take a snapshot, then act on coordinates.

## How it works

Computer control is implemented as two Python sidecars:

- **Exec sidecar**: takes screenshots and performs mouse and keyboard actions.
- **Vision sidecar**: caches screenshots per session, runs OCR, and resolves coordinates
  from either OCR text or a vision grounding model.

OpenClaw calls these sidecars over a lightweight JSON-RPC bridge. A snapshot
always goes to both sidecars: the exec sidecar captures the screen and system
state, and the vision sidecar ingests the screenshot so OCR or vision resolution
can be done without a second capture.

## Quick usage

- `computer action="snapshot"` captures the current screen and system state.
- `computer action="act" request={...}` performs a click/type/scroll action.

## Tool responses

The tool returns an image payload plus metadata in `details`.

### Snapshot response details

`details` includes:

- `screenshotId`: identifier for the ingested screenshot.
- `systemState`: a small system snapshot (see below).
- `width` and `height`: screenshot dimensions.

### Act response details

`details` includes:

- `action`: the requested action kind.
- `actionResult`: `{ ok, kind, message? }` from the exec sidecar.
- `screenshotId`, `systemState`, `width`, `height` for the post-action snapshot.

### Status response details

Returns exec and vision sidecar status payloads (Python path, platform, OCR availability,
and whether the vision model is loaded).

## System state fields

`systemState` contains:

- `active_window`: active app name or window title when available.
- `mouse_position`: the current cursor position.
- `screen_resolution`: display resolution string.
- `time`: local timestamp string from the exec sidecar.

### OCR-based click

```
computer action="act" request={{
  "kind": "click",
  "find_coordinates_by": "ocr",
  "ocr_text": "Search"
}}
```

### Vision grounding click

```
computer action="act" request={{
  "kind": "click",
  "find_coordinates_by": "prediction",
  "description": "The green login button on the top right"
}}
```

## Configuration

Computer control is disabled by default. Enable it in `~/.openclaw/openclaw.json`:

```
{
  "computer": {
    "enabled": true
  }
}
```

Optional overrides:

```
{
  "computer": {
    "exec": {
      "path": "python3",
      "args": ["-u"],
      "timeoutMs": 20000
    },
    "vision": {
      "path": "python3",
      "args": ["-u"],
      "timeoutMs": 45000,
      "ocrMatchThreshold": 0.8,
      "ocrWaitTimeoutMs": 5000,
      "modelName": "OpenGVLab/InternVL3_5-4B"
    }
  }
}
```

Environment overrides:

- `OPENCLAW_COMPUTER_EXEC_PYTHON`
- `OPENCLAW_COMPUTER_VISION_PYTHON`

Set these if you want explicit control over which Python binaries are used.

Install python dependencies:

- Exec sidecar: `pip install -r python/requirements-computer-exec.txt`
- Vision sidecar: `pip install -r python/requirements-computer-vision.txt`

## Actions and coordinate resolution

Supported action kinds:

- `click`, `double_click`, `right_click`, `move`, `drag`
- `scroll`, `type`, `press`, `hotkey`, `wait`

Coordinate resolution options for click-like actions:

- `find_coordinates_by="manual"`: supply `x` and `y` directly.
- `find_coordinates_by="ocr"`: provide `ocr_text` and let OCR resolve the target.
- `find_coordinates_by="prediction"`: provide `description` for vision grounding.

OCR matching is fuzzy and controlled by `computer.vision.ocrMatchThreshold`.
The vision sidecar keeps a per-session screenshot cache so OCR and grounding
operate on the most recent snapshot without re-capturing the screen.

## Sidecar implementation notes

- The exec sidecar uses `pyautogui` for input control and `Pillow` for screenshots.
- The vision sidecar uses RapidOCR and an InternVL-compatible model for grounding.
- OCR is started asynchronously during ingestion to reduce latency for `act`.
