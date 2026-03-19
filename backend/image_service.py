"""
image_service.py — Read/write Tezi image.json files served by Nginx.
"""

from __future__ import annotations

import json
import logging
import os
import traceback

from config import IMAGE_ROOT, IMAGE_LIST_FILE

logger = logging.getLogger("FlashBench.Images")


def read_image_list() -> list[str]:
    """Return list of relative ``image.json`` paths from ``image_list.json``."""
    with open(IMAGE_LIST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("images", [])


def read_image_json(relative_path: str) -> dict:
    """Read and return a single ``image.json``."""
    full_path = os.path.join(IMAGE_ROOT, relative_path)
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_image_json(relative_path: str, data: dict) -> None:
    """Write *data* back to an ``image.json`` file."""
    full_path = os.path.join(IMAGE_ROOT, relative_path)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def get_all_images() -> list[dict]:
    """Return enriched metadata for every registered Tezi image."""
    paths  = read_image_list()
    images: list[dict] = []
    for rel_path in paths:
        try:
            img = read_image_json(rel_path)
            folder = rel_path.rsplit("/", 1)[0] if "/" in rel_path else rel_path
            autoinstall_raw = img.get("autoinstall", False)
            autoinstall = autoinstall_raw is True or autoinstall_raw == "true"
            images.append({
                "path":         rel_path,
                "folder":       folder,
                "name":         img.get("name", folder),
                "description":  img.get("description", ""),
                "version":      img.get("version", ""),
                "release_date": img.get("release_date", ""),
                "autoinstall":  autoinstall,
            })
        except Exception:
            logger.warning("Cannot read image %s:\n%s", rel_path, traceback.format_exc())
    return images


def set_autoinstall(target_path: str) -> list[dict]:
    """
    Set ``autoinstall=true`` for *target_path*, ``false`` for all others.

    Returns the refreshed image list.

    Raises:
        FileNotFoundError: if *target_path* is not in the image list.
    """
    paths = read_image_list()
    if target_path not in paths:
        raise FileNotFoundError(f"Unknown image path: {target_path}")

    for rel_path in paths:
        try:
            img = read_image_json(rel_path)
            img["autoinstall"] = (rel_path == target_path)
            write_image_json(rel_path, img)
            logger.info("Image %s → autoinstall=%s", rel_path, img["autoinstall"])
        except Exception:
            logger.error("Error updating %s:\n%s", rel_path, traceback.format_exc())

    return get_all_images()
