# Novato daily-driver roadmap

Novato is a capable package-intent and beginner-help tool, but it is not yet a
complete daily Linux operator. This roadmap is based on a product, Linux-user,
debugging, testing, implementation, and execution audit of the real CLI.

## P0 — trust and correctness

- [x] Keep failed commands, stderr, paths, usernames, and secrets out of online
  error analysis.
- [x] Preserve the complete Trash estimate across recommended and manual
  storage-cleanup stages.
- [x] Recommend only structurally known download caches; keep generic
  application caches in the judgment-required tier.
- [x] Reject ambiguous slash commands such as `/clean code`.
- [x] Base reclaim estimates on allocated disk blocks, not apparent/sparse-file
  size, and deduplicate hard-linked inodes.
- [ ] Give every deep scan one shared time budget and report unreadable areas.

## P1 — become useful every day

- [ ] Add a read-only `/doctor [storage|network|boot|battery|all]` with
  timeout-bound probes and ranked findings.
- [ ] Add goal-based cleanup: reach healthy headroom or free a requested amount,
  using the smallest low-risk plan.
- [ ] Add measured cleanup providers for pip/uv/pnpm/Maven, Podman/Docker
  unused images and build cache, Flatpak unused runtimes, coredumps, paru/pamac,
  and other common developer caches. Never prune container volumes by default.
- [ ] Separate `/disk` (read-only diagnosis) from `/clean storage` (mutating).
- [ ] Add `/history` and recoverable file actions with `/undo` where possible.
- [ ] Improve `/mistake` with bounded, locally redacted error evidence and Fish
  shell support.

## P2 — reliability and distribution

- [ ] Add automated tests for Python 3.10+ and supported distro command plans.
- [ ] Add real Trash integration tests for spaces, Unicode, vanished paths, and
  permission failures.
- [ ] Replace GNU-only disk-usage assumptions with capability-detected fallbacks.
- [ ] Add shell completion and machine-readable diagnostic output.
- [ ] Publish and test `.deb`/RPM/AUR release paths; keep docs generated from the
  real CLI so commands and test counts do not drift.

## Product rule

New features must be evidence-based, distro-aware, timeout-bound, and
confirmation-gated. Language models may classify intent or explain verified
facts; they must not invent system state or bypass Novato's local safety layer.
