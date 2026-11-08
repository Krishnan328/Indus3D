"""
tools/download_vision_model.py
---------------------------------
Downloads pre-trained 3D printing failure detection model weights (YOLO)
for Indus3D Edge Inspector.

Default model:
  ApatheticWithoutTheA/3D-Print-Failure-Detector (Hugging Face, MIT License)
  Trained on 9,000+ images for:
    - spaghetti
    - stringing
    - zits (blobs / under-extrusion)

Usage:
  python tools/download_vision_model.py
  python tools/download_vision_model.py --force
  python tools/download_vision_model.py --dest custom/path/best.pt
  python tools/download_vision_model.py --url https://...
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

DEFAULT_MODEL_URL = (
    "https://huggingface.co/ApatheticWithoutTheA/3D-Print-Failure-Detector/"
    "resolve/main/yolov11-3d-print-failure-detection"
)
DEFAULT_DEST_PATH = os.path.join(
    os.path.dirname(__file__), "..", "edge", "models", "best.pt"
)


def download_model(
    url: str = DEFAULT_MODEL_URL,
    dest: str = DEFAULT_DEST_PATH,
    force: bool = False,
) -> str:
    """Download pre-trained vision weights with progress reporting and atomic write."""
    dest_path = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    if os.path.isfile(dest_path) and not force:
        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        print(f"✅ Vision model already exists at {dest_path} ({size_mb:.2f} MB).")
        print("   Pass --force to re-download.")
        return dest_path

    print(f"📥 Downloading pre-trained 3D print failure model...")
    print(f"   Source URL:  {url}")
    print(f"   Destination: {dest_path}")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Indus3D-Vision-Downloader/1.0"},
    )

    start_time = time.time()
    tmp_path = dest_path + ".tmp"
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 64 * 1024  # 64 KB

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        print(
                            f"\r   Progress: {mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%)",
                            end="",
                            flush=True,
                        )

            # Atomic replace after full transfer
            os.replace(tmp_path, dest_path)
            duration = time.time() - start_time
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            print(f"\n✅ Download complete in {duration:.1f}s ({size_mb:.2f} MB)")
            print(f"   Model saved to {dest_path}")
            return dest_path
    except Exception as exc:
        print(f"\n❌ Download failed: {exc}", file=sys.stderr)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Download pre-trained 3D printer defect detection weights for Indus3D"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MODEL_URL,
        help="Direct download URL for model weights",
    )
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST_PATH,
        help="Destination file path for model weights",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite if file already exists",
    )
    args = parser.parse_args()

    try:
        download_model(url=args.url, dest=args.dest, force=args.force)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
