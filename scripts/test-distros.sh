#!/usr/bin/env bash
# Dependencies: Docker daemon. Installs dependencies ONLY in disposable images.
set -euo pipefail
cd "$(dirname "$0")/.."
family="${1:?Usage: scripts/test-distros.sh apt|dnf|pacman|zypper}"
case "$family" in
  apt) distro=ubuntu:24.04 ;;
  dnf) distro=fedora:43 ;;
  pacman) distro=archlinux:latest ;;
  zypper) distro=opensuse/tumbleweed:latest ;;
  *) echo "Unknown family: $family" >&2; exit 2 ;;
esac
mkdir -p docs/validation
docker build --network "${NOVATO_DOCKER_NETWORK:-default}" -f scripts/containers/Dockerfile --build-arg "DISTRO=$distro" \
  --build-arg "FAMILY=$family" -t "novato-test:$family" . > "docs/validation/$family-build.log" 2>&1
docker run --rm --network "${NOVATO_DOCKER_NETWORK:-default}" "novato-test:$family" | tee "docs/validation/$family-smoke.txt"
docker run --rm --network "${NOVATO_DOCKER_NETWORK:-default}" "novato-test:$family" pytest | tee "docs/validation/$family-tests.txt"
