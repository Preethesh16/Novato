# Validation report

Validated on 2026-09-20 after restoring commit
`57a01f466d07df31fd602730787773c947c47fa1` and applying the fixes described below.
The exact restoration was pushed as `1aacd90`; subsequent changes intentionally
improve that baseline. A local backup branch preserves the former tip.

## Results

| Environment | Python | Automated suite | Live repository + CLI smoke |
|---|---|---|---|
| Arch host, isolated environment | 3.10.21 | 427 passed | — |
| Arch host, isolated environment | 3.12.13 | 427 passed | — |
| Arch host, isolated environment | 3.14.7 | 427 passed | — |
| `archlinux:latest` container | 3.14.7 | 427 passed | Passed |
| `ubuntu:24.04` container (24.04.5) | 3.12.3 | 427 passed | Passed |
| `fedora:43` container | 3.14.7 | 427 passed | Passed |
| `opensuse/tumbleweed:latest` container | 3.13.14 | 427 passed | Passed |

Coverage: **81% of executable lines** in the host run. This is line coverage,
not proof that all inputs, branches, or distro versions work. The restored
baseline started with 397 passing tests; this pass adds 30 cases.

Also checked: `ruff check .`, shell script syntax, `git diff --check`, source and
wheel builds, and installation of the built wheel into a fresh environment with
`novato --help` and `novato --version` entry-point checks.

Raw evidence is in [validation/](validation/): `*-tests.txt`, `*-smoke.txt`, and
`python*.txt`. These results are local runs, not a claim that a remote CI run has
completed. The new GitHub Actions workflow repeats the Python and distro matrix
on pushes and pull requests.

## What was exercised

The suite covers intent mapping, distro detection, repository parsing, installed
package detection, configuration persistence, safety refusals, dry runs,
confirmation and cancellation, installation/update/removal orchestration,
teaching, tutorial progress, shell hooks, backend fallback, model downloads,
process helpers, and storage planning/selection/measurement.

Storage tests create actual temporary files, verify classification and allocated
sizes, and move/delete only their own fixture data. A five-run workflow checks
batch selection, Trash handling, deletion of allocated blocks, and the exact
capacity sample shown to the user. Real personal files are never cleaned during
the test suite. `gio` present and absent cases are both covered.

Each container smoke run checks:

1. Detection against the container's real `/etc/os-release`.
2. A live package repository search for `bash` and its installed version.
3. `--help`, `--version`, `/status`, `/cheat files`, `/man "list files"`,
   `/explain ls -la`, and `/space`.
4. `--dry-run "install bash"`, including the installed-package update preview.
5. Separate demo captures of a live `tree` lookup and its install preview.

Package-manager metadata and dependencies are installed inside disposable
containers. Novato package operations in smoke tests and recordings are dry
runs. The unit tests replace command execution with controlled test doubles.

## Bugs fixed in this pass

- **Explicit package names:** `install tree` previously fuzzy-matched to theme
  switchers. Single named install requests now bypass fuzzy/AI reinterpretation.
- **Fedora DNF5:** live tab-delimited search output returned no packages. Both
  DNF4 colon rows and DNF5 tab rows now parse; dotted names stay intact.
- **Debian installed state:** removed packages with residual configuration were
  treated as installed. The query now checks dpkg's actual installed status.
- **AUR routing:** missing helpers no longer send AUR packages to pacman; Pamac
  uses `build` for AUR packages.
- **Invalid configuration:** null keys, wrong field types, and string booleans
  fall back to typed defaults instead of crashing or silently enabling features.
- **Malformed AUR responses:** invalid result collections, entries, and
  popularity values no longer crash the tested parsing paths.
- **Safety checks:** absolute destructive executable paths, force-delete flag
  combinations, and malformed command quoting are rejected.
- **Dry-run download:** model download preview neither downloads nor enables a
  model. Other configuration flows can still write settings; dry-run is not a
  general read-only sandbox.
- **Installer:** no fallback to system `pip --user` on externally managed Python.
  The script requires an isolated installer and explains what is missing.
- **Portable tests:** cache-action tests no longer assume `gio` is installed.
  Real deletion assertions measure their own fixture blocks instead of assuming
  global disk free space cannot change while other processes are running.

## Reproduce

```bash
uv sync --frozen
uv run pytest --cov=novato --cov-report=term-missing
uv run ruff check .
uv build
bash -n scripts/install.sh scripts/uninstall.sh scripts/test-distros.sh

# Optional interpreter matrix; uv may download an interpreter.
uv run --isolated --python 3.10 pytest
uv run --isolated --python 3.12 pytest
uv run --isolated --python 3.14 pytest

# Requires Docker and network access; installs only inside images.
for family in pacman apt dnf zypper; do
  bash scripts/test-distros.sh "$family"
done
```

On the validation host, Docker's default bridge could not reach package mirrors.
The runs used `NOVATO_DOCKER_NETWORK=host` to resolve that environment issue.
Final reruns mounted the final source read-only with `PYTHONPATH=/app` into the
built test images so each distro tested the same changes. The checked-in runner
builds the current source directly:

```bash
NOVATO_DOCKER_NETWORK=host bash scripts/test-distros.sh dnf
```

The images' rolling tags and Python dependencies can change. The repository's
`uv.lock` provides a locked host setup; the container matrix also checks
compatibility with dependencies resolved by each distro's Python at build time.
`procps`/`procps-ng` is included as a test prerequisite for the real `ps` parser
regression. Build logs remain local; summaries and smoke transcripts are tracked.

## What remains unverified

- Interactive root installs, system upgrades, package removal, and AUR builds on
  full desktop installations. Container demos preview these commands.
- Live Groq responses, credentials, rate limits, and actual multi-gigabyte
  llamafile downloads/inference. API/downloader/fallback behavior is mocked.
- Long-running Bash/Zsh sessions, desktop notification behavior, GUI Trash/GVFS,
  and Android SDK/emulator deletion with real developer installations.
- Every listed derivative, older distro release, CPU architecture, language,
  unusual filesystem/mount layout, and failure during power loss or disk errors.
- Arbitrary adversarial commands. Pattern checks are not a security sandbox.

These are explicit coverage gaps, not passing results. The new CI matrix and
reproducible scripts make future fixes and additional environment checks easier
without claiming that software can be proven “perfect” by one test pass.
