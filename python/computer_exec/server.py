#!/usr/bin/env python3
import asyncio
import inspect
import base64
import hashlib
import io
import json
import logging
import platform
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("computer_exec")


class JsonRpcProtocol:
    def __init__(self):
        self.methods = {}

    def register_method(self, name: str, handler):
        self.methods[name] = handler

    async def handle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("jsonrpc") != "2.0":
            return self._error(payload.get("id"), -32600, "Invalid JSON-RPC version")
        method = payload.get("method")
        if not method:
            return self._error(payload.get("id"), -32600, "Method required")
        handler = self.methods.get(method)
        if not handler:
            return self._error(payload.get("id"), -32601, f"Method not found: {method}")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error(payload.get("id"), -32602, "Params must be an object")
        try:
            if inspect.iscoroutinefunction(handler):
                result = await handler(**params)
            else:
                result = handler(**params)
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}
        except Exception as e:
            logger.error("RPC error", exc_info=True)
            return self._error(payload.get("id"), -32603, str(e))

    def _error(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def send(self, response: Dict[str, Any]):
        data = json.dumps(response, ensure_ascii=False)
        sys.stdout.buffer.write((data + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def _get_active_window_sync() -> Optional[str]:
    if IS_WINDOWS:
        try:
            import win32gui

            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return title or None
        except Exception:
            return None
    if IS_MACOS:
        try:
            from AppKit import NSWorkspace

            app = NSWorkspace.sharedWorkspace().activeApplication()
            return app.get("NSApplicationName", None)
        except Exception:
            return None
    if IS_LINUX:
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except Exception:
            return None
    return None


def _get_mouse_position_sync() -> Optional[str]:
    try:
        import pyautogui

        pos = pyautogui.position()
        return f"({pos.x}, {pos.y})"
    except Exception:
        return None


def _get_screen_resolution_sync() -> Optional[str]:
    try:
        import pyautogui

        size = pyautogui.size()
        return f"{size.width}x{size.height}"
    except Exception:
        return None


async def get_system_state() -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    active_window = await loop.run_in_executor(None, _get_active_window_sync)
    mouse_position = await loop.run_in_executor(None, _get_mouse_position_sync)
    screen_resolution = await loop.run_in_executor(None, _get_screen_resolution_sync)
    return {
        "active_window": active_window or "Unknown",
        "mouse_position": mouse_position or "Unknown",
        "screen_resolution": screen_resolution or "Unknown",
        "time": datetime.now().isoformat(),
    }


async def capture_screenshot(delay_ms: Optional[float] = None) -> Dict[str, Any]:
    if delay_ms and delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)
    try:
        import pyautogui
        from PIL import Image

        def _capture():
            screenshot = pyautogui.screenshot()
            if screenshot.mode != "RGB":
                screenshot = screenshot.convert("RGB")
            width, height = screenshot.size
            buffer = io.BytesIO()
            screenshot.save(buffer, format="JPEG", quality=85, optimize=False, progressive=False)
            img_bytes = buffer.getvalue()
            return img_bytes, width, height

        loop = asyncio.get_event_loop()
        img_bytes, width, height = await loop.run_in_executor(None, _capture)
        screenshot_b64 = base64.b64encode(img_bytes).decode("utf-8")
        sample = screenshot_b64[:1024] if len(screenshot_b64) > 1024 else screenshot_b64
        screenshot_id = hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16]
        return {
            "screenshot": screenshot_b64,
            "screenshotId": screenshot_id,
            "mimeType": "image/jpeg",
            "width": width,
            "height": height,
        }
    except Exception as e:
        logger.error("Screenshot failed", exc_info=True)
        raise RuntimeError(f"Screenshot failed: {e}")


async def execute_action(kind: str, **kwargs) -> Dict[str, Any]:
    try:
        import pyautogui

        pyautogui.FAILSAFE = False

        if kind == "click":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                raise ValueError("x/y required for click")
            pyautogui.click(x, y)
            return {"ok": True, "kind": kind, "message": f"Clicked at ({x}, {y})"}
        if kind == "double_click":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                raise ValueError("x/y required for double_click")
            pyautogui.doubleClick(x, y)
            return {"ok": True, "kind": kind, "message": f"Double-clicked at ({x}, {y})"}
        if kind == "right_click":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                raise ValueError("x/y required for right_click")
            pyautogui.rightClick(x, y)
            return {"ok": True, "kind": kind, "message": f"Right-clicked at ({x}, {y})"}
        if kind == "move":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                raise ValueError("x/y required for move")
            pyautogui.moveTo(x, y)
            return {"ok": True, "kind": kind, "message": f"Moved to ({x}, {y})"}
        if kind == "drag":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                raise ValueError("x/y required for drag")
            duration_ms = kwargs.get("durationMs") or 200
            pyautogui.dragTo(x, y, duration=max(0.0, float(duration_ms) / 1000.0))
            return {"ok": True, "kind": kind, "message": f"Dragged to ({x}, {y})"}
        if kind == "scroll":
            amount = kwargs.get("scrollAmount")
            direction = kwargs.get("scrollDirection", "vertical")
            if amount is None:
                raise ValueError("scrollAmount required for scroll")
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
            if direction == "horizontal":
                try:
                    pyautogui.hscroll(int(-amount), x=x, y=y)
                except Exception:
                    pyautogui.scroll(int(-amount), x=x, y=y)
            else:
                pyautogui.scroll(int(-amount), x=x, y=y)
            return {"ok": True, "kind": kind, "message": f"Scrolled {amount} ({direction})"}
        if kind == "type":
            text = kwargs.get("text")
            if text is None:
                raise ValueError("text required for type")
            pyautogui.write(str(text), interval=0.01)
            return {"ok": True, "kind": kind, "message": "Typed text"}
        if kind == "press":
            key = kwargs.get("key")
            if not key:
                raise ValueError("key required for press")
            pyautogui.press(str(key))
            return {"ok": True, "kind": kind, "message": f"Pressed {key}"}
        if kind == "hotkey":
            keys = kwargs.get("keys")
            if not keys or not isinstance(keys, list):
                raise ValueError("keys array required for hotkey")
            pyautogui.hotkey(*[str(k) for k in keys])
            return {"ok": True, "kind": kind, "message": "Hotkey executed"}
        if kind == "wait":
            wait_ms = kwargs.get("waitMs") or 0
            time.sleep(max(0, float(wait_ms) / 1000.0))
            return {"ok": True, "kind": kind, "message": f"Waited {wait_ms}ms"}

        raise ValueError(f"Unknown action kind: {kind}")
    except Exception as e:
        logger.error("Action failed", exc_info=True)
        raise RuntimeError(f"Action failed: {e}")


class ComputerExecService:
    async def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "python": sys.executable,
            "platform": platform.system(),
        }

    async def snapshot(self, delay_ms: Optional[float] = None) -> Dict[str, Any]:
        shot = await capture_screenshot(delay_ms)
        state = await get_system_state()
        return {
            **shot,
            "systemState": state,
        }

    async def act(self, **kwargs) -> Dict[str, Any]:
        kind = kwargs.get("kind")
        if not kind:
            raise ValueError("kind required")
        kwargs.pop("kind", None)
        return await execute_action(kind, **kwargs)


async def main() -> None:
    service = ComputerExecService()
    rpc = JsonRpcProtocol()
    rpc.register_method("status", service.status)
    rpc.register_method("snapshot", service.snapshot)
    rpc.register_method("act", service.act)

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            rpc.send(rpc._error(None, -32700, "Parse error"))
            continue
        response = await rpc.handle(payload)
        rpc.send(response)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Computer exec server terminated")
