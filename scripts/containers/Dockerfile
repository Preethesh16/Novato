ARG DISTRO=ubuntu:24.04
FROM ${DISTRO}
ARG FAMILY=apt
RUN if [ "$FAMILY" = apt ]; then \
      apt-get update && apt-get install -y python3 python3-venv python3-pip; \
    elif [ "$FAMILY" = dnf ]; then \
      dnf install -y python3 python3-pip; \
    elif [ "$FAMILY" = pacman ]; then \
      pacman -Syu --noconfirm python python-pip; \
    elif [ "$FAMILY" = zypper ]; then \
      zypper --non-interactive install python3 python3-pip; \
    else exit 1; fi
# ps is a test dependency for the real process-format regression check.
RUN if ! command -v ps >/dev/null; then \
      if [ "$FAMILY" = apt ]; then apt-get install -y procps; \
      elif [ "$FAMILY" = dnf ]; then dnf install -y procps-ng; \
      elif [ "$FAMILY" = pacman ]; then pacman -S --noconfirm procps-ng; \
      else zypper --non-interactive install procps; fi; fi
WORKDIR /app
COPY . .
RUN python3 -m venv /opt/novato && /opt/novato/bin/pip install '.[dev]'
ENV PATH="/opt/novato/bin:$PATH" SHELL=/bin/bash LC_ALL=C.UTF-8
CMD ["python", "scripts/distro_smoke.py"]
