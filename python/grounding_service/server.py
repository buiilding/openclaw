#!/usr/bin/env python3
import asyncio
import inspect
import base64
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from difflib import SequenceMatcher

from vision_internvl import InternVLModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("computer_vision")


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


OCR_AVAILABLE = False
try:
    from rapidocr import RapidOCR

    OCR_AVAILABLE = True
except Exception as e:
    logger.warning(f"OCR dependencies not available: {e}")
    RapidOCR = None


class OcrEngine:
    def __init__(self):
        self._engine = None
        self._use_cuda = False
        self._init()

    def _init(self):
        if not OCR_AVAILABLE:
            return
        try:
            params = {"EngineConfig.onnxruntime.use_cuda": True}
            self._engine = RapidOCR(params=params)
            self._use_cuda = True
            logger.info("OCR engine initialized (CUDA)")
        except Exception as e:
            logger.warning(f"OCR CUDA init failed, falling back to CPU: {e}")
            params = {"EngineConfig.onnxruntime.use_cuda": False}
            self._engine = RapidOCR(params=params)
            self._use_cuda = False
            logger.info("OCR engine initialized (CPU)")

    async def analyze(self, screenshot_b64: str) -> List[Dict[str, Any]]:
        if not self._engine:
            raise RuntimeError("OCR engine not available")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._analyze_sync, screenshot_b64)

    def _analyze_sync(self, screenshot_b64: str) -> List[Dict[str, Any]]:
        image_bytes = base64.b64decode(screenshot_b64)
        result = self._engine(image_bytes)
        if result is None or not hasattr(result, "txts"):
            return []
        texts = getattr(result, "txts", None)
        if texts is None:
            texts = []
        scores = getattr(result, "scores", None)
        if scores is None:
            scores = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            boxes = []
        bbox_list = []
        for box in boxes:
            if box is None or len(box) < 4:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x1 = int(min(xs))
            y1 = int(min(ys))
            x2 = int(max(xs))
            y2 = int(max(ys))
            bbox_list.append((x1, y1, x2, y2))
        ocr_results = []
        for i, (text, bbox) in enumerate(zip(texts, bbox_list)):
            x1, y1, x2, y2 = bbox
            confidence = float(scores[i]) if i < len(scores) and scores[i] is not None else 0.9
            ocr_results.append(
                {
                    "id": str(i),
                    "text": str(text).strip(),
                    "confidence": confidence,
                    "bbox": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                }
            )
        return ocr_results


def resolve_ocr_text(text: str, ocr_results: List[Dict[str, Any]], threshold: float) -> Tuple[int, int]:
    if not text:
        raise ValueError("ocr_text required for OCR resolution")
    best = None
    best_score = 0.0
    target = text.lower().strip()
    for item in ocr_results:
        current = str(item.get("text", "")).lower().strip()
        score = SequenceMatcher(None, target, current).ratio()
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= threshold:
        bbox = best["bbox"]
        x = bbox["x"] + bbox["width"] // 2
        y = bbox["y"] + bbox["height"] // 2
        return x, y
    raise ValueError(f"Could not find text '{text}' on screen (best score={best_score:.2f})")


@dataclass
class SessionCache:
    screenshot_id: Optional[str] = None
    screenshot_b64: Optional[str] = None
    ocr_results: Optional[List[Dict[str, Any]]] = None
    ocr_event: asyncio.Event = field(default_factory=asyncio.Event)


class GroundingService:
    def __init__(self):
        self._sessions: Dict[str, SessionCache] = {}
        self._ocr = OcrEngine()
        self._vision_model: Optional[InternVLModel] = None

    def _get_session(self, session_key: str) -> SessionCache:
        if session_key not in self._sessions:
            self._sessions[session_key] = SessionCache()
        return self._sessions[session_key]

    def _ensure_vision(self, model_name: Optional[str]) -> InternVLModel:
        if self._vision_model:
            return self._vision_model
        resolved = model_name or "OpenGVLab/InternVL3_5-4B"
        self._vision_model = InternVLModel(model_name=resolved, device="auto", trust_remote_code=True)
        return self._vision_model

    async def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "ocr_available": OCR_AVAILABLE,
            "vision_loaded": self._vision_model is not None,
        }

    async def ingest_screenshot(
        self,
        session_key: str,
        screenshot_b64: str,
        screenshot_id: Optional[str] = None,
        ocr_wait_timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        cache = self._get_session(session_key)
        if not screenshot_id:
            sample = screenshot_b64[:1024] if len(screenshot_b64) > 1024 else screenshot_b64
            screenshot_id = hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16]
        cache.screenshot_id = screenshot_id
        cache.screenshot_b64 = screenshot_b64
        cache.ocr_results = None
        cache.ocr_event.clear()

        async def run_ocr(current_id: str, screenshot: str):
            try:
                if OCR_AVAILABLE:
                    results = await self._ocr.analyze(screenshot)
                    if cache.screenshot_id == current_id:
                        cache.ocr_results = results
            except Exception as e:
                logger.error(f"OCR failed: {e}")
            finally:
                cache.ocr_event.set()

        asyncio.create_task(run_ocr(screenshot_id, screenshot_b64))
        if ocr_wait_timeout_ms:
            try:
                await asyncio.wait_for(cache.ocr_event.wait(), timeout=ocr_wait_timeout_ms / 1000.0)
            except asyncio.TimeoutError:
                pass
        return {"screenshotId": screenshot_id}

    async def resolve(
        self,
        session_key: str,
        method: str,
        ocr_text: Optional[str] = None,
        description: Optional[str] = None,
        screenshot_id: Optional[str] = None,
        ocr_match_threshold: Optional[float] = None,
        ocr_wait_timeout_ms: Optional[int] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        cache = self._get_session(session_key)
        if not cache.screenshot_b64 or not cache.screenshot_id:
            raise ValueError("No screenshot available for this session")
        if screenshot_id and cache.screenshot_id != screenshot_id:
            logger.warning("Screenshot id mismatch; using latest cached screenshot")
        if method == "ocr":
            if ocr_wait_timeout_ms:
                try:
                    await asyncio.wait_for(cache.ocr_event.wait(), timeout=ocr_wait_timeout_ms / 1000.0)
                except asyncio.TimeoutError:
                    logger.warning("OCR wait timed out; falling back to on-demand OCR")
            if cache.ocr_results is None:
                cache.ocr_results = await self._ocr.analyze(cache.screenshot_b64)
            threshold = ocr_match_threshold if ocr_match_threshold is not None else 0.8
            x, y = resolve_ocr_text(ocr_text or "", cache.ocr_results, threshold)
            return {"screenshotId": cache.screenshot_id, "x": x, "y": y}
        if method == "prediction":
            if not description:
                raise ValueError("description required for prediction")
            model = self._ensure_vision(model_name)
            coords = await model.predict_click_coordinates(cache.screenshot_b64, description)
            if not coords:
                raise ValueError("Vision model could not find target")
            x, y = coords
            return {"screenshotId": cache.screenshot_id, "x": x, "y": y}
        raise ValueError(f"Unknown method: {method}")


async def main() -> None:
    service = GroundingService()
    rpc = JsonRpcProtocol()
    rpc.register_method("status", service.status)
    rpc.register_method("ingest_screenshot", service.ingest_screenshot)
    rpc.register_method("resolve", service.resolve)

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
        logger.info("Grounding service terminated")
