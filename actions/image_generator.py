"""
actions/image_generator.py — High-Speed NVIDIA FLUX.1 Image Generation with Smart Prompt Enhancement
"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
import requests

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
CONFIG_PATH     = BASE_DIR / "config" / "api_keys.json"
OUTPUT_DIR      = Path.home() / "Desktop" / "JARVIS_Images"
FLUX_DEV_URL    = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
DEFAULT_NVIDIA_KEY = "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"


def _load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _get_nvidia_key() -> str:
    cfg = _load_config()
    return cfg.get("nvidia_api_key") or DEFAULT_NVIDIA_KEY


def _get_gemini_key() -> str:
    cfg = _load_config()
    return cfg.get("gemini_api_key", "")


def _enhance_prompt(prompt: str) -> str:
    """Use Gemini Flash to enrich short prompts into vivid, high-detail diffusion prompts."""
    # If the prompt is already long and detailed (>18 words), use it directly
    words = prompt.strip().split()
    if len(words) > 18:
        return prompt.strip()

    gemini_key = _get_gemini_key()
    if not gemini_key:
        return f"{prompt}, cinematic lighting, photorealistic, 8k resolution, sharp focus, highly detailed"

    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        
        system_instruction = (
            "You are an expert prompt engineer for FLUX diffusion models. "
            "Convert the user's short image idea into a single, highly detailed, visually stunning prompt. "
            "Describe the subject, lighting, environment, textures, camera angle, and artistic style. "
            "Rules:\n"
            "- Return ONLY the final prompt text.\n"
            "- Do NOT include explanations, quotes, markdown formatting, or introductory phrases.\n"
            "- Keep it between 30 and 60 words."
        )

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{system_instruction}\n\nUser Concept: {prompt}\n\nExpanded Prompt:"
        )
        enhanced = (response.text or "").strip()
        enhanced = re.sub(r"^[\"']|[\"']$", "", enhanced).strip()
        if enhanced and len(enhanced) > len(prompt):
            return enhanced
    except Exception as e:
        print(f"[ImageGen] ⚠️ Prompt enhancement skipped: {e}")

    return f"{prompt}, cinematic lighting, dramatic atmosphere, 8k resolution, sharp focus, octane render"


def _open_image(path: Path) -> None:
    """Cross-platform image viewer launcher."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        print(f"[ImageGen] ⚠️ Could not auto-open image: {e}")


def generate_image_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    raw_prompt = parameters.get("prompt", "").strip()
    enhance    = parameters.get("enhance", True)

    if not raw_prompt:
        msg = "Please provide a description of the image you would like me to generate, sir."
        _log(msg, player)
        return msg

    api_key = _get_nvidia_key()
    if not api_key:
        msg = "Sir, NVIDIA API key is missing. Please add it to your configuration."
        _log(msg, player)
        return msg

    _log(f"Received image request: \"{raw_prompt}\"", player)

    # 1. Enhance prompt
    if enhance:
        _log("Enhancing prompt for maximum visual fidelity...", player)
        final_prompt = _enhance_prompt(raw_prompt)
    else:
        final_prompt = raw_prompt

    print(f"[ImageGen] Final prompt: {final_prompt}")

    # 2. Call NVIDIA NIM FLUX.1
    _log("Rendering image via NVIDIA FLUX neural engine...", player)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": final_prompt,
        "seed": 0,
        "steps": 25
    }

    start_time = time.time()
    try:
        resp = requests.post(FLUX_DEV_URL, headers=headers, json=payload, timeout=90)
        elapsed = time.time() - start_time

        if resp.status_code != 200:
            err_msg = f"Image generation failed (HTTP {resp.status_code}): {resp.text[:200]}"
            _log(err_msg, player)
            return err_msg

        data = resp.json()
        artifacts = data.get("artifacts", [])
        if not artifacts:
            err_msg = "No image artifact returned by NVIDIA API."
            _log(err_msg, player)
            return err_msg

        b64_data = artifacts[0].get("base64", "")
        if not b64_data:
            err_msg = "Image data was empty."
            _log(err_msg, player)
            return err_msg

        # 3. Save to Desktop / JARVIS_Images
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_slug = re.sub(r"[^\w\s-]", "", raw_prompt.lower())[:25].strip().replace(" ", "_")
        if not clean_slug:
            clean_slug = "render"
        filename = f"{clean_slug}_{timestamp}.png"
        output_file = OUTPUT_DIR / filename

        img_bytes = base64.b64decode(b64_data)
        output_file.write_bytes(img_bytes)

        _log(f"Image rendered in {elapsed:.1f}s and saved to {output_file.name}", player)

        # 4. Display on screen
        _open_image(output_file)

        msg = f"I have generated your image for '{raw_prompt}'. It has been rendered in {elapsed:.1f} seconds, saved to your Desktop, and opened on your screen, sir."
        
        if session_memory:
            try:
                session_memory.set_last_search(query=f"Image: {raw_prompt}", response=msg)
            except Exception:
                pass

        return msg

    except Exception as e:
        err_msg = f"An error occurred while generating the image: {e}"
        _log(err_msg, player)
        return err_msg


def _log(message: str, player=None) -> None:
    print(f"[ImageGen] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "generate_image",
    "description": (
        "Generates a high-quality, photorealistic or artistic image based on the user's description "
        "using the NVIDIA FLUX.1 neural engine, enhances the prompt automatically, saves it to the "
        "Desktop/JARVIS_Images folder, and opens it on the screen."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The description or visual concept of the image to generate (e.g. 'a futuristic cybernetic car', 'sunset over mountains', 'Iron Man portrait')."
            },
            "enhance": {
                "type": "BOOLEAN",
                "description": "Whether to automatically enhance the prompt with professional photographic and visual details. Default is true."
            }
        },
        "required": [
            "prompt"
        ]
    },
    "handler": generate_image_action,
}
