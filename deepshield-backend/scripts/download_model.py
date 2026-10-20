"""Download the public Grad-CAM checkpoint once, from Hugging Face.

The weights are 72.8 MB and are intentionally not committed to Git. The
backend loads them lazily from ``DEEPSHIELD_MODEL_PATH`` (default
``deepshield-backend/models/best_model.pt``) on the first ``POST /explain``.

Usage::

    python3 scripts/download_model.py           # skip if already present
    python3 scripts/download_model.py --force   # re-download

No Hugging Face account or token is required: the repository is public and
not gated. ``urllib`` is used on purpose so this needs no extra dependency.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://huggingface.co/honi05/deepfake-detection/resolve/main/best_model.pt"
)
# Recorded so a re-uploaded / replaced checkpoint is caught instead of being
# silently loaded by a detector whose behaviour changed.
EXPECTED_BYTES = 72_790_421
MODEL_ID = "honi05/deepfake-detection"


def default_destination() -> Path:
    configured = os.getenv("DEEPSHIELD_MODEL_PATH")

    if configured:
        return Path(configured).expanduser()

    return Path(__file__).resolve().parent.parent / "models" / "best_model.pt"


def download(destination: Path, force: bool = False) -> Path:
    if destination.is_file() and not force:
        size = destination.stat().st_size

        if size == EXPECTED_BYTES:
            print(f"Checkpoint already present: {destination} ({size} bytes)")
            return destination

        raise SystemExit(
            f"{destination} exists but is {size} bytes, expected "
            f"{EXPECTED_BYTES}. Re-run with --force to replace it."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {MODEL_ID} best_model.pt -> {destination}")

    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=destination.parent,
        suffix=".part",
    ) as partial:
        with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
            while True:
                chunk = response.read(1024 * 1024)

                if not chunk:
                    break

                partial.write(chunk)

        total = partial.tell()

    if total != EXPECTED_BYTES:
        os.remove(partial.name)
        raise SystemExit(
            f"Downloaded {total} bytes, expected {EXPECTED_BYTES}. "
            "The hosted checkpoint may have changed; verify the model card "
            "before using it."
        )

    os.replace(partial.name, destination)

    print(f"Saved {destination} ({total} bytes)")

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--destination", type=Path, default=None)

    args = parser.parse_args()

    destination = args.destination or default_destination()

    download(destination, force=args.force)

    return 0


if __name__ == "__main__":
    sys.exit(main())
