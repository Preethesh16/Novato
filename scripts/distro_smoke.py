"""Read-only distro integration checks; run inside a disposable container."""
import os
import subprocess
import tempfile

from novato.config import Config, save_config
from novato.detector import detect_system
from novato.installed import installed_versions
from novato.searcher import search


def main():
    system = detect_system()
    assert system.supported, system
    print(f"DISTRO: {system.distro_name} | {system.package_manager}", flush=True)
    versions = installed_versions(system.package_manager)
    assert "bash" in versions, versions
    results = search("bash", system.package_manager)
    assert any(result.name == "bash" for result in results), results
    print(f"PASS: real repository search + installed bash {versions['bash']}", flush=True)
    with tempfile.TemporaryDirectory(prefix="novato-smoke-") as home:
        os.environ["NOVATO_HOME"] = home
        save_config(Config(setup_complete=True, tips_shown=True))
        for args in (
            ["--help"], ["--version"], ["/status"], ["/cheat", "files"],
            ["/man", "list files"], ["/explain", "ls", "-la"], ["/space"],
            ["--dry-run", "install bash"],
        ):
            print("\n$ novato " + " ".join(args), flush=True)
            proc = subprocess.run(
                ["novato", *args], input="1\ny\nn\n", text=True,
                capture_output=True, timeout=90,
            )
            print(proc.stdout, end="", flush=True)
            assert proc.returncode == 0, (args, proc.returncode, proc.stderr)
            assert "Traceback" not in proc.stderr, proc.stderr
        print("PASS: CLI smoke checks (package changes were dry-run only)", flush=True)


if __name__ == "__main__":
    main()
