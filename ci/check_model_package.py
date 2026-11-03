"""Verify an inference package's files and approved weights digest without loading the model."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def verify_model_package(directory, expected_digest, weights_file="model.pt"):
    """Check package structure. The model team owns the contents and class mapping."""
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected_digest) is None:
        raise ValueError("--weights-sha256 must be a 64-digit hexadecimal SHA-256")
    if not directory.is_dir():
        raise ValueError(f"Model package directory not found: {directory}")
    if not re.fullmatch(r"[\w-][\w.-]*", weights_file) or weights_file.endswith("."):
        raise ValueError("--weights-file must be a single filename (letters, numbers, dots, underscores or hyphens)")

    config_names = ("model_config.json", "preprocess.json", "classes.json", "manifest.json")
    if weights_file.lower() in config_names:
        raise ValueError("--weights-file must be different from the four JSON configuration files")
    for name in config_names:
        path = directory / name
        try:
            with path.open(encoding="utf-8-sig") as source:
                document = json.load(source)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{name}: invalid UTF-8 JSON") from error
        allowed_types = (dict, list) if name == "classes.json" else (dict,)
        if not isinstance(document, allowed_types) or not document:
            expected = "object or array" if name == "classes.json" else "object"
            raise ValueError(f"{name}: expected a nonempty JSON {expected}")

    weights = directory / weights_file
    if not weights.is_file() or weights.stat().st_size == 0:
        raise ValueError(f"{weights_file}: weights file is missing or empty")
    digest = hashlib.sha256()
    with weights.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest.lower():
        raise ValueError(f"{weights_file}: SHA-256 differs from the supplied approved digest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing the model package")
    parser.add_argument("--weights-sha256", required=True, help="approved digest supplied by the model team")
    parser.add_argument("--weights-file", default="model.pt", help="single weights filename inside the package (default: model.pt)")
    args = parser.parse_args()
    try:
        verify_model_package(args.directory, args.weights_sha256, args.weights_file)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: four nonempty JSON documents and the {args.weights_file} SHA-256 match the preflight rules.")
    print("The model was not loaded. Class mappings, inference results and performance need separate checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
