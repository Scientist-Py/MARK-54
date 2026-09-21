"""
test_image_gen.py — Standalone Test Script for NVIDIA NIM FLUX.1-schnell Image Generation
"""

import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import requests

# Ensure UTF-8 output on Windows consoles
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Your NVIDIA NIM API Key
NVIDIA_API_KEY = "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"

# NVIDIA NIM FLUX.1-dev Endpoint (State-of-the-Art Photorealism)
API_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"

DESKTOP_DIR = Path.home() / "Desktop"


def generate_image(prompt: str, steps: int = 25) -> Path | None:
    print(f"\n🎨 Prompt: \"{prompt}\"")
    print("⏳ Sending request to NVIDIA NIM (FLUX.1-dev)...")
    start_time = time.time()

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt,
        "seed": 0,
        "steps": steps
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=90)
        elapsed = time.time() - start_time

        if resp.status_code != 200:
            print(f"❌ Error {resp.status_code}: {resp.text}")
            return None

        response_json = resp.json()
        artifacts = response_json.get("artifacts", [])
        if not artifacts:
            print("❌ No image artifact returned from API.")
            return None

        b64_data = artifacts[0].get("base64", "")
        if not b64_data:
            print("❌ Empty image data in response.")
            return None

        # Decode and save to Desktop
        img_bytes = base64.b64decode(b64_data)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = DESKTOP_DIR / f"flux_image_{timestamp}.png"

        output_path.write_bytes(img_bytes)
        print(f"✅ Image generated successfully in {elapsed:.2f} seconds!")
        print(f"📁 Saved to: {output_path}")

        # Automatically open image on Windows
        if sys.platform == "win32":
            try:
                os.startfile(str(output_path))
                print("🖼️  Opened image in default viewer.")
            except Exception:
                pass

        return output_path

    except Exception as e:
        print(f"❌ Error during generation: {e}")
        return None


def main():
    print("=" * 60)
    print("🚀 NVIDIA NIM FLUX.1-schnell Image Generator Test")
    print("=" * 60)

    # If passed as command line argument
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:]).strip()
        generate_image(prompt)
        return

    while True:
        try:
            prompt = input("\nEnter image prompt (or 'q' to quit): ").strip()
            if not prompt or prompt.lower() in ("q", "quit", "exit"):
                print("Exiting test script. Goodbye!")
                break

            generate_image(prompt)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break


if __name__ == "__main__":
    main()
