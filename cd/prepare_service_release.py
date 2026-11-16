"""Generate Compose configuration from a validated CI publication handoff."""

import argparse
import importlib.util
import json
from pathlib import Path


def compose_for(images, source_commit):
    services = {
        name: {
            "image": image, "platform": "linux/amd64", "restart": "unless-stopped",
            "read_only": True, "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp:rw,nosuid,nodev,size=134217728,mode=1777"],
        }
        for name, image in images.items()
    }
    for name in ("api", "worker"):
        services[name]["environment"] = {
            "SKINAI_DB_PATH": "/data/db/backend.sqlite3",
            "SKINAI_PHOTO_DIR": "/data/photos",
        }
    services["api"].update(
        env_file=["runtime.env"], ports=["127.0.0.1:18165:8000"],
        volumes=["db:/data/db", "photos:/data/photos"],
    )
    depends = {"api": {"condition": "service_healthy"}}
    services["worker"].update(
        depends_on=depends, network_mode="none",
        volumes=["db:/data/db", "photos:/data/photos:ro"],
    )
    for name, port in (("patient-ui", 18166), ("doctor-ui", 18167)):
        services[name].update(depends_on=depends, ports=[f"127.0.0.1:{port}:8080"])
    return {"name": "skinai-service", "x-skinai-source-commit": source_commit,
            "services": services, "volumes": {"db": {}, "photos": {}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validator", type=Path, default=Path("ci/release/handoff/release.py"),
                        help="Trusted CI release validator from the project checkout")
    args = parser.parse_args()
    try:
        spec = importlib.util.spec_from_file_location("skinai_ci_release", args.validator)
        if spec is None or spec.loader is None:
            raise ValueError("Expected the project's release.py validator")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        release = validator.load_release(args.release)
        images = {name: record["image"] for name, record in release["services"].items()}
        config = compose_for(images, release["source"]["commit"])
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Prepared {release['release_id']} at {args.output}")


if __name__ == "__main__":
    main()
