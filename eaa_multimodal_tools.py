"""
EAA Multi-Modal Tools - Phase 1
Image analysis, generation, description, and OCR extraction.
All tools use the existing ToolResult/ToolRegistry pattern from eaa_agent_tools.py.
"""

import os
import sys
import json
import base64
import hashlib
import traceback
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

# Re-use the ToolResult from the main tools module
try:
    from eaa_agent_tools import ToolResult
except ImportError:
    @dataclass
    class ToolResult:
        success: bool
        output: str
        error: Optional[str] = None
        def to_dict(self):
            return {"success": self.success, "output": self.output, "error": self.error}


# ─── IMAGE ANALYZE ────────────────────────────────────────────────────────────
def tool_image_analyze(image_path: str, prompt: str = "Describe this image in detail.") -> ToolResult:
    """
    Analyze an image using AI vision (local transformers or llama-cpp vision).
    Falls back to PIL metadata extraction if no vision model is available.
    """
    try:
        image_path = os.path.expanduser(image_path)
        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        # Try using transformers vision pipeline first
        try:
            from transformers import BlipProcessor, BlipForConditionalGeneration
            from PIL import Image

            img = Image.open(image_path).convert("RGB")

            # Check if BLIP model is cached locally
            model_path = os.path.join(os.path.dirname(__file__), "..", "brains", "blip_model")
            if os.path.exists(model_path):
                processor = BlipProcessor.from_pretrained(model_path, local_files_only=True)
                model = BlipForConditionalGeneration.from_pretrained(model_path, local_files_only=True)
            else:
                # Use a small model from HuggingFace
                processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
                model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")

            inputs = processor(img, text=prompt, return_tensors="pt")
            output = model.generate(**inputs, max_new_tokens=300)
            caption = processor.decode(output[0], skip_special_tokens=True)
            return ToolResult(True, f"Image Analysis:\n{caption}")

        except Exception as vision_err:
            # Fallback: extract image metadata with PIL
            from PIL import Image
            import io

            img = Image.open(image_path)
            info = img.info if hasattr(img, 'info') else {}

            metadata = {
                "format": img.format,
                "mode": img.mode,
                "size": f"{img.width}x{img.height}",
                "width": img.width,
                "height": img.height,
                "file_size": f"{os.path.getsize(image_path)} bytes",
            }

            # Extract EXIF if available
            try:
                exif_data = img._getexif()
                if exif_data:
                    from PIL.ExifTags import TAGS
                    exif = {}
                    for tag_id, value in exif_data.items():
                        tag = TAGS.get(tag_id, tag_id)
                        exif[str(tag)] = str(value)
                    metadata["exif"] = exif
            except Exception:
                pass

            analysis = f"PIL Metadata Analysis (vision model unavailable: {vision_err}):\n"
            analysis += json.dumps(metadata, indent=2, default=str)
            return ToolResult(True, analysis)

    except Exception as e:
        return ToolResult(False, "", f"Image analysis failed: {str(e)}")


# ─── IMAGE DESCRIBE ───────────────────────────────────────────────────────────
def tool_image_describe(image_path: str, detail_level: str = "medium") -> ToolResult:
    """
    Describe an image in detail. Uses PIL analysis + color histogram for rich description.
    detail_level: 'low' (basic), 'medium' (colors + metadata), 'high' (full analysis)
    """
    try:
        image_path = os.path.expanduser(image_path)
        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        from PIL import Image
        import numpy as np

        img = Image.open(image_path).convert("RGB")
        pixels = np.array(img)

        description = []
        description.append(f"Image: {image_path}")
        description.append(f"Size: {img.width}x{img.height} pixels")
        description.append(f"Format: {img.format}")
        description.append(f"Mode: {img.mode}")

        if detail_level in ("medium", "high"):
            # Color analysis
            avg_color = pixels.mean(axis=(0, 1))
            description.append(f"Average Color: RGB({int(avg_color[0])}, {int(avg_color[1])}, {int(avg_color[2])})")

            # Brightness
            gray = np.mean(pixels, axis=2)
            brightness = np.mean(gray)
            description.append(f"Brightness: {brightness:.1f}/255 ({'dark' if brightness < 85 else 'bright' if brightness > 170 else 'balanced'})")

            # Dominant colors (simplified k-means)
            if detail_level == "high":
                try:
                    from collections import Counter
                    # Quantize colors
                    quantized = (pixels // 32) * 32
                    colors = [tuple(c) for row in quantized for c in row]
                    top_colors = Counter(colors).most_common(5)
                    description.append("\nDominant Colors:")
                    for color, count in top_colors:
                        hex_color = '#{:02x}{:02x}{:02x}'.format(*color)
                        pct = (count / len(colors)) * 100
                        description.append(f"  {hex_color} RGB{color} - {pct:.1f}%")
                except Exception:
                    pass

        if detail_level == "high":
            # Image statistics
            description.append(f"\nChannel Statistics:")
            for i, channel in enumerate(["Red", "Green", "Blue"]):
                ch = pixels[:, :, i]
                description.append(f"  {channel}: min={ch.min()}, max={ch.max()}, mean={ch.mean():.1f}, std={ch.std():.1f}")

            # Edge density (simplified)
            try:
                gray = np.mean(pixels, axis=2).astype(np.uint8)
                gx = np.abs(np.diff(gray, axis=1))
                gy = np.abs(np.diff(gray, axis=0))
                edge_density = (np.mean(gx) + np.mean(gy)) / 2
                complexity = "simple" if edge_density < 10 else "moderate" if edge_density < 30 else "complex"
                description.append(f"  Edge Complexity: {complexity} (density: {edge_density:.1f})")
            except Exception:
                pass

        return ToolResult(True, "\n".join(description))

    except Exception as e:
        return ToolResult(False, "", f"Image description failed: {str(e)}")


# ─── OCR EXTRACT ──────────────────────────────────────────────────────────────
def tool_ocr_extract(image_path: str, language: str = "eng", psm: int = 3) -> ToolResult:
    """
    Extract text from images using Tesseract OCR.
    language: ISO 639-3 language code (e.g., 'eng', 'ara', 'fra')
    psm: Page Segmentation Mode (3=auto, 6=uniform block, 11=sparse text)
    """
    try:
        image_path = os.path.expanduser(image_path)
        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        import pytesseract
        from PIL import Image

        img = Image.open(image_path)

        config = f"--psm {psm} -l {language}"

        # Extract text
        text = pytesseract.image_to_string(img, config=config)
        text = text.strip()

        if not text:
            return ToolResult(True, "[No text detected in image]")

        # Also extract confidence data
        try:
            data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0
            word_count = len([w for w in data['text'] if w.strip()])
            result = f"Extracted Text ({word_count} words, {avg_conf:.0f}% avg confidence):\n\n{text}"
        except Exception:
            result = f"Extracted Text:\n\n{text}"

        return ToolResult(True, result)

    except pytesseract.TesseractNotFoundError:
        return ToolResult(False, "", "Tesseract OCR not installed. Download from: https://github.com/UB-Mannheim/tesseract/wiki")
    except Exception as e:
        return ToolResult(False, "", f"OCR extraction failed: {str(e)}")


# ─── IMAGE GENERATE ───────────────────────────────────────────────────────────
def tool_image_generate(
    prompt: str,
    output_path: str = None,
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    guidance: float = 7.5,
    seed: int = -1
) -> ToolResult:
    """
    Generate images using local Stable Diffusion or ComfyUI pipeline.
    Falls back to simple placeholder if no GPU model is available.
    """
    try:
        import torch
        import numpy as np

        if not torch.cuda.is_available():
            return ToolResult(False, "", "GPU (CUDA) is required for image generation")

        # Try diffusers pipeline first
        try:
            from diffusers import StableDiffusionPipeline
            import torch

            model_id = "runwayml/stable-diffusion-v1-5"
            cache_dir = os.path.join(os.path.dirname(__file__), "..", "brains", "sd_model")

            if seed == -1:
                seed = np.random.randint(0, 2**32 - 1)

            generator = torch.Generator("cuda").manual_seed(seed)

            pipe = StableDiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.float16,
                cache_dir=cache_dir,
                safety_checker=None
            )
            pipe = pipe.to("cuda")

            image = pipe(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=generator
            ).images[0]

            if output_path:
                output_path = os.path.expanduser(output_path)
                os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
                image.save(output_path)
                return ToolResult(True, f"Image generated and saved to: {output_path}\nPrompt: {prompt}\nSeed: {seed}\nSize: {width}x{height}")
            else:
                # Save to default location
                default_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "generated")
                os.makedirs(default_dir, exist_ok=True)
                filename = f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{seed}.png"
                full_path = os.path.join(default_dir, filename)
                image.save(full_path)
                return ToolResult(True, f"Image generated: {full_path}\nPrompt: {prompt}\nSeed: {seed}\nSize: {width}x{height}")

        except Exception as pipe_err:
            return ToolResult(False, "", f"Image generation pipeline failed: {str(pipe_err)}\nMake sure stable-diffusion model is downloaded in brains/sd_model/")

    except ImportError:
        return ToolResult(False, "", "Required packages missing. Install: pip install torch diffusers transformers")
    except Exception as e:
        return ToolResult(False, "", f"Image generation failed: {str(e)}")


# ─── IMAGE INFO ───────────────────────────────────────────────────────────────
def tool_image_info(image_path: str) -> ToolResult:
    """Get detailed image file information including format, size, DPI, etc."""
    try:
        image_path = os.path.expanduser(image_path)
        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        from PIL import Image

        img = Image.open(image_path)
        file_size = os.path.getsize(image_path)

        info = {
            "file": image_path,
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "pixels": f"{img.width * img.height:,}",
            "file_size": f"{file_size:,} bytes ({file_size / 1024:.1f} KB)",
            "dpi": str(img.info.get("dpi", "N/A")),
        }

        # Animated GIF check
        if hasattr(img, 'n_frames'):
            info["frames"] = img.n_frames
            info["animated"] = img.n_frames > 1

        # Color depth
        bits = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "I": 32, "F": 32}
        info["bit_depth"] = bits.get(img.mode, "N/A")

        return ToolResult(True, json.dumps(info, indent=2))

    except Exception as e:
        return ToolResult(False, "", f"Failed to get image info: {str(e)}")


# ─── IMAGE CONVERT ────────────────────────────────────────────────────────────
def tool_image_convert(image_path: str, output_path: str, format: str = None) -> ToolResult:
    """Convert image to a different format. Format auto-detected from output_path extension."""
    try:
        image_path = os.path.expanduser(image_path)
        output_path = os.path.expanduser(output_path)

        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        from PIL import Image

        img = Image.open(image_path)

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        if format:
            img.save(output_path, format=format.upper())
        else:
            img.save(output_path)

        new_size = os.path.getsize(output_path)
        return ToolResult(True, f"Converted: {image_path} -> {output_path}\nNew size: {new_size:,} bytes")

    except Exception as e:
        return ToolResult(False, "", f"Image conversion failed: {str(e)}")


# ─── IMAGE RESIZE ─────────────────────────────────────────────────────────────
def tool_image_resize(image_path: str, output_path: str, width: int = None, height: int = None, percent: int = None) -> ToolResult:
    """Resize an image by specific dimensions or percentage."""
    try:
        image_path = os.path.expanduser(image_path)
        output_path = os.path.expanduser(output_path)

        if not os.path.exists(image_path):
            return ToolResult(False, "", f"Image not found: {image_path}")

        from PIL import Image

        img = Image.open(image_path)
        orig_w, orig_h = img.size

        if percent:
            new_w = int(orig_w * percent / 100)
            new_h = int(orig_h * percent / 100)
        elif width and height:
            new_w, new_h = width, height
        elif width:
            ratio = width / orig_w
            new_w, new_h = width, int(orig_h * ratio)
        elif height:
            ratio = height / orig_h
            new_w, new_h = int(orig_w * ratio), height
        else:
            return ToolResult(False, "", "Specify width, height, or percent")

        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        img_resized.save(output_path)

        return ToolResult(True, f"Resized: {orig_w}x{orig_h} -> {new_w}x{new_h}\nSaved: {output_path}")

    except Exception as e:
        return ToolResult(False, "", f"Image resize failed: {str(e)}")


# ─── REGISTRY ─────────────────────────────────────────────────────────────────
def register_multimodal_tools(registry) -> None:
    """Register all multi-modal tools with the existing ToolRegistry."""
    registry.register("image_analyze", tool_image_analyze, "Analyze image with AI vision. Args: image_path, prompt (optional)")
    registry.register("image_describe", tool_image_describe, "Describe image content. Args: image_path, detail_level (low/medium/high)")
    registry.register("ocr_extract", tool_ocr_extract, "Extract text from image (OCR). Args: image_path, language (default eng), psm (default 3)")
    registry.register("image_generate", tool_image_generate, "Generate image from text. Args: prompt, output_path, width, height, steps, seed")
    registry.register("image_info", tool_image_info, "Get image file information. Args: image_path")
    registry.register("image_convert", tool_image_convert, "Convert image format. Args: image_path, output_path, format (optional)")
    registry.register("image_resize", tool_image_resize, "Resize image. Args: image_path, output_path, width/height/percent")

__all__ = [
    "register_multimodal_tools",
    "tool_image_analyze",
    "tool_image_describe",
    "tool_ocr_extract",
    "tool_image_generate",
    "tool_image_info",
    "tool_image_convert",
    "tool_image_resize",
]
