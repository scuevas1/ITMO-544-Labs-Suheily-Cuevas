"""Python EC2 boot script generator for the existing Node.js applications."""
import base64
import gzip
import json
import re
from pathlib import Path


BOOT_TEMPLATE = r'''#!/usr/bin/python3
import base64
import gzip
import json
import subprocess
from pathlib import Path


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    data = json.loads(gzip.decompress(base64.b64decode("__PAYLOAD__")))
    tier = data["tier"]
    directory = Path("/opt/weather-advisor") / tier
    directory.mkdir(parents=True, exist_ok=True)

    run("dnf", "install", "-y", "nodejs22", "nodejs22-npm")

    for name, content in data["files"].items():
        file_path = directory / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    if "package-lock.json" in data["files"]:
        run("/usr/bin/npm-22", "ci", "--omit=dev", "--no-audit", "--no-fund", cwd=directory)
    else:
        run("/usr/bin/npm-22", "install", "--omit=dev", "--no-audit", "--no-fund", cwd=directory)

    environment = {"PORT": "3000", "AWS_REGION": data["region"], **data["environment"]}
    lines = [
        "[Unit]", "Description=Weather Advisor " + tier,
        "After=network-online.target", "Wants=network-online.target", "",
        "[Service]", "Type=simple", "User=ec2-user",
        "WorkingDirectory=" + str(directory),
        "ExecStart=/usr/bin/node-22 " + str(directory / "app.js"),
        "Restart=always", "RestartSec=5"
    ]
    for key, value in environment.items():
        if not key.replace("_", "").isalnum() or any(c in value for c in ('"', '\n', '\r', '%')):
            raise ValueError("Invalid environment setting")
        lines.append('Environment="' + key + '=' + value + '"')
    lines.extend(["", "[Install]", "WantedBy=multi-user.target", ""])

    service = "weather-advisor-" + tier
    Path("/etc/systemd/system/" + service + ".service").write_text("\n".join(lines))
    run("chown", "-R", "ec2-user:ec2-user", str(directory))
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", service)


if __name__ == "__main__":
    main()
'''


def build_user_data(tier, region, environment, base_dir):
    """Embed the existing Node.js app without including credentials."""
    if tier not in ("weather", "advisor"):
        raise ValueError("Invalid tier")
    if not re.fullmatch(r"[a-z0-9-]+", region):
        raise ValueError("Invalid AWS region")
    if not isinstance(environment, dict):
        raise ValueError("Invalid environment")

    files = {}
    folder = Path(base_dir) / f"{tier}-app"

    file_names = ["app.js", "package.json"]

    if tier == "advisor":
        file_names.append("public/style.css")

    for name in file_names:
        path = folder / name
        if not path.exists() and name == "package-lock.json":
            continue
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        files[name] = path.read_text(encoding="utf-8")

    for key, value in environment.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("Invalid environment key")
        if not isinstance(value, str) or any(c in value for c in ('"', "\n", "\r", "%")):
            raise ValueError("Invalid environment value")

    payload = {"tier": tier, "region": region, "environment": environment, "files": files}
    compressed = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
    script = BOOT_TEMPLATE.replace("__PAYLOAD__", base64.b64encode(compressed).decode())
    if len(script.encode()) > 16384:
        raise ValueError("EC2 user data exceeds 16 KiB")
    return script
