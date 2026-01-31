# Computer Tool

The `computer` tool enables OS-level automation using screenshots, OCR, and grounding models.
It mirrors the browser tool flow: take a snapshot, then act on coordinates.

## Quick usage

- `computer action="snapshot"` captures the current screen and system state.
- `computer action="act" request={...}` performs a click/type/scroll action.

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

Install python dependencies:

- Exec sidecar: `pip install -r python/requirements-computer-exec.txt`
- Vision sidecar: `pip install -r python/requirements-computer-vision.txt`
