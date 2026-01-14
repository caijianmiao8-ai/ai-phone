"""Screenshot utilities for capturing Android device screen."""

import base64
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Tuple

from PIL import Image


@dataclass
class Screenshot:
    """Represents a captured screenshot."""

    base64_data: str
    width: int
    height: int
    is_sensitive: bool = False


def get_screenshot(device_id: str | None = None, timeout: int = 10) -> Screenshot:
    """
    Capture a screenshot from the connected Android device.

    Args:
        device_id: Optional ADB device ID for multi-device setups.
        timeout: Timeout in seconds for screenshot operations.

    Returns:
        Screenshot object containing base64 data and dimensions.

    Note:
        If the screenshot fails (e.g., on sensitive screens like payment pages),
        a black fallback image is returned with is_sensitive=True.
    """
    adb_prefix = _get_adb_prefix(device_id)

    try:
        # Use exec-out screencap to get PNG data directly via pipe
        # This is faster and more reliable than saving to device + pull
        result = subprocess.run(
            adb_prefix + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=timeout,
        )

        # Check for screenshot failure
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            if "Status: -1" in stderr_text or "Failed" in stderr_text:
                return _create_fallback_screenshot(is_sensitive=True)
            return _create_fallback_screenshot(is_sensitive=False)

        # Verify we got valid PNG data
        if not result.stdout or len(result.stdout) < 100:
            return _create_fallback_screenshot(is_sensitive=False)

        # PNG header check
        png_header = b'\x89PNG\r\n\x1a\n'
        if result.stdout[:8] != png_header:
            return _create_fallback_screenshot(is_sensitive=False)

        # Read and encode image
        img = Image.open(BytesIO(result.stdout))
        width, height = img.size

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

        return Screenshot(
            base64_data=base64_data, width=width, height=height, is_sensitive=False
        )

    except subprocess.TimeoutExpired:
        print(f"Screenshot error: Timeout after {timeout} seconds")
        return _create_fallback_screenshot(is_sensitive=False)
    except Exception as e:
        print(f"Screenshot error: {e}")
        return _create_fallback_screenshot(is_sensitive=False)


def _get_adb_prefix(device_id: str | None) -> list:
    """Get ADB command prefix with optional device specifier."""
    if device_id:
        return ["adb", "-s", device_id]
    return ["adb"]


def _create_fallback_screenshot(is_sensitive: bool) -> Screenshot:
    """Create a black fallback image when screenshot fails."""
    default_width, default_height = 1080, 2400

    black_img = Image.new("RGB", (default_width, default_height), color="black")
    buffered = BytesIO()
    black_img.save(buffered, format="PNG")
    base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return Screenshot(
        base64_data=base64_data,
        width=default_width,
        height=default_height,
        is_sensitive=is_sensitive,
    )
