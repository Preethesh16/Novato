# Demo provenance

The PNGs are terminal output rendered from actual Novato subprocess captures.
They are not screenshots of desktop applications and do not simulate a package
installation. JSON files preserve the command, scripted input, distro identity,
and unedited stdout for each scene.

Each distro contributes three scenes: `/status`, `--dry-run "install tree"`,
and `/explain ls -la`. The GIF cycles through the four package previews; the
silent MP4 shows all 12 scenes, six seconds each. No AI-generated application
output, stock desktop screenshots, API keys, or personal home paths are used.

## Reproduce

First build/test the images from the repository root:

```bash
for family in pacman apt dnf zypper; do
  bash scripts/test-distros.sh "$family"
  docker run --rm "novato-test:$family" python scripts/capture_demo.py > "docs/media/$family.json"
done
uv run --with pillow python scripts/render_demo.py
```

Rendering requires FFmpeg and DejaVu Sans Mono. Set `NOVATO_DEMO_FONT` to the
absolute path of another monospace `.ttf` if needed. Package versions and
repository descriptions can change between recordings. The capture script
creates a temporary Basic-mode configuration and removes it on exit.

[Video](novato-demo.mp4) · [Preview](novato-demo.gif) · [Validation](../TESTING.md)
