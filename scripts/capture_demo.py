"""Capture real CLI output as JSON. Run inside a built distro test image."""
import json
import os
import subprocess
import tempfile

from novato.config import Config, save_config
from novato.detector import detect_system


def main():
    system = detect_system()
    scenes = []
    with tempfile.TemporaryDirectory(prefix="novato-demo-") as home:
        os.environ.update(NOVATO_HOME=home, COLUMNS="88", NO_COLOR="1", TERM="dumb")
        save_config(Config(setup_complete=True, tips_shown=True))
        for title, args, response in (
            ("Meet your system", ["/status"], ""),
            ("Find a package and preview its command", ["--dry-run", "install tree"], "1\ny\n"),
            ("Understand the command", ["/explain", "ls", "-la"], ""),
        ):
            proc = subprocess.run(
                ["novato", *args], input=response, text=True,
                capture_output=True, timeout=90,
            )
            if proc.returncode:
                raise RuntimeError((args, proc.returncode, proc.stderr))
            if "--dry-run" in args:
                expected = system.install_cmd + " tree"
                if expected not in proc.stdout or "(offline)" in proc.stdout:
                    raise RuntimeError(f"Expected a live repository preview of {expected}: {proc.stdout}")
            scenes.append({"title": title, "command": "novato " + " ".join(args),
                           "output": proc.stdout, "input": response.strip()})
    print(json.dumps({"distro": system.distro_name, "pm": system.package_manager,
                      "scenes": scenes}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
