import asyncio
import base64
import logging
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image

from coordinates import extract_first_point, extract_last_bbox, scale_norm_to_pixels

logger = logging.getLogger("computer_vision")

VISION_MODELS_AVAILABLE = False
try:
    import torch
    import torchvision.transforms as T
    from torchvision.transforms.functional import InterpolationMode
    from transformers import AutoModel, AutoTokenizer

    VISION_MODELS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Vision model dependencies not available: {e}")
    torch = None
    T = None
    InterpolationMode = None
    AutoModel = None
    AutoTokenizer = None


class BaseVisionModel:
    def __init__(self, model_name: str, device: str = "auto", trust_remote_code: bool = True):
        if not VISION_MODELS_AVAILABLE:
            raise ImportError("Vision model dependencies not available")
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.trust_remote_code = trust_remote_code
        self._model_dtype = None
        self._inference_lock = asyncio.Lock()
        self._load()

    def _load(self):
        raise NotImplementedError


class InternVLModel(BaseVisionModel):
    def _load(self):
        try:
            try:
                import flash_attn

                use_flash_attn = True
            except ImportError:
                use_flash_attn = False

            try:
                model_dtype = torch.bfloat16
                self.model = AutoModel.from_pretrained(
                    self.model_name,
                    dtype=model_dtype,
                    low_cpu_mem_usage=True,
                    use_flash_attn=use_flash_attn,
                    device_map="auto",
                    trust_remote_code=self.trust_remote_code,
                ).eval()
                self._model_dtype = model_dtype
            except Exception:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                dtype = torch.float16 if device == "cuda" else torch.float32
                self.model = (
                    AutoModel.from_pretrained(
                        self.model_name,
                        dtype=dtype,
                        low_cpu_mem_usage=True,
                        use_flash_attn=False,
                        trust_remote_code=self.trust_remote_code,
                    )
                    .to(device)
                    .eval()
                )
                self._model_dtype = dtype

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=self.trust_remote_code, use_fast=False
            )
        except Exception as e:
            logger.error(f"Failed to load InternVL model {self.model_name}: {e}")
            raise

    def _build_transform(self, input_size: int):
        if not VISION_MODELS_AVAILABLE or T is None:
            raise ImportError("Vision model dependencies not available")
        mean = (0.485, 0.456, 0.406)
        std = (0.229, 0.224, 0.225)
        return T.Compose(
            [
                T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
                T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
                T.ToTensor(),
                T.Normalize(mean=mean, std=std),
            ]
        )

    def _dynamic_preprocess(
        self,
        image: Image.Image,
        min_num: int = 1,
        max_num: int = 12,
        image_size: int = 448,
        use_thumbnail: bool = True,
    ):
        orig_width, orig_height = image.size
        aspect_ratio = orig_width / orig_height
        target_ratios = set(
            (i, j)
            for n in range(min_num, max_num + 1)
            for i in range(1, n + 1)
            for j in range(1, n + 1)
            if i * j <= max_num and i * j >= min_num
        )
        target_ratios = sorted(target_ratios, key=lambda x: x[0] * x[1])
        best_ratio_diff = float("inf")
        best_ratio = (1, 1)
        area = orig_width * orig_height
        for ratio in target_ratios:
            target_aspect_ratio = ratio[0] / ratio[1]
            ratio_diff = abs(aspect_ratio - target_aspect_ratio)
            if ratio_diff < best_ratio_diff:
                best_ratio_diff = ratio_diff
                best_ratio = ratio
            elif ratio_diff == best_ratio_diff:
                if area > 0.5 * image_size * image_size * ratio[0] * ratio[1]:
                    best_ratio = ratio

        target_width = image_size * best_ratio[0]
        target_height = image_size * best_ratio[1]
        blocks = best_ratio[0] * best_ratio[1]
        resized_img = image.resize((target_width, target_height))
        processed_images = []
        for i in range(blocks):
            box = (
                (i % (target_width // image_size)) * image_size,
                (i // (target_width // image_size)) * image_size,
                ((i % (target_width // image_size)) + 1) * image_size,
                ((i // (target_width // image_size)) + 1) * image_size,
            )
            processed_images.append(resized_img.crop(box))
        if use_thumbnail and len(processed_images) != 1:
            processed_images.append(image.resize((image_size, image_size)))
        return processed_images

    def _images_to_pixel_values(self, images, input_size: int = 448, max_num: int = 12):
        transform = self._build_transform(input_size=input_size)
        pixel_values_list = []
        num_patches_list = []
        for img in images:
            tiles = self._dynamic_preprocess(img, image_size=input_size, use_thumbnail=True, max_num=max_num)
            pv = [transform(tile) for tile in tiles]
            pv = torch.stack(pv)
            num_patches_list.append(pv.shape[0])
            pixel_values_list.append(pv)
        if not pixel_values_list:
            return None, []
        pixel_values = torch.cat(pixel_values_list)
        return pixel_values, num_patches_list

    async def predict_click_coordinates(self, image_b64: str, instruction: str) -> Optional[Tuple[int, int]]:
        async with self._inference_lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._predict_sync, image_b64, instruction)

    def _predict_sync(self, image_b64: str, instruction: str) -> Optional[Tuple[int, int]]:
        try:
            img_bytes = base64.b64decode(image_b64)
            image = Image.open(BytesIO(img_bytes))
            width, height = image.size
            grounding_prompt = (
                f"Please provide the bounding box coordinate of the UI element this user instruction describes: <ref>{instruction}</ref>. "
                f"Answer in the format of [[x1, y1, x2, y2]]"
            )
            pixel_values, num_patches_list = self._images_to_pixel_values(
                [image], input_size=448, max_num=12
            )
            if pixel_values is None:
                return None
            model_dtype = self._model_dtype
            if model_dtype is None:
                try:
                    model_dtype = next(self.model.parameters()).dtype
                except Exception:
                    model_dtype = torch.bfloat16
            pixel_values = pixel_values.to(model_dtype).to(self.model.device)
            question = f"<image>\n{grounding_prompt}"
            generation_config = dict(
                max_new_tokens=256,
                do_sample=False,
                temperature=0.0,
            )
            if len(num_patches_list) > 1:
                response = self.model.chat(
                    self.tokenizer,
                    pixel_values,
                    question,
                    generation_config,
                    num_patches_list=num_patches_list,
                )
            else:
                response = self.model.chat(self.tokenizer, pixel_values, question, generation_config)
            output_text = response or ""
            if not output_text:
                return None
            point = extract_first_point(output_text)
            if point is None:
                bbox = extract_last_bbox(output_text)
                if bbox is None:
                    return None
                x1, y1, x2, y2 = bbox
                point = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            x_norm, y_norm = point
            return scale_norm_to_pixels(x_norm, y_norm, width, height)
        except Exception:
            logger.error("Vision prediction failed", exc_info=True)
            return None
