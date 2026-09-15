# A ready-to-use Python environment with helm-python-sdk preinstalled.
#
#   docker build -t helm-python-sdk .
#   docker run -it --rm -v ~/.kube/config:/home/nonroot/.kube/config:ro \
#     helm-python-sdk python
#   >>> import helm_python as helm
#
# Intended as a base for Helm automation scripts and CI jobs:
#
#   FROM helm-python-sdk
#   COPY my_job.py .
#   CMD ["python", "my_job.py"]
#
# Need extra Python packages in a derived image? The shipped stage has no
# installer by design, so add them the way this file does — build against
# the -dev variant and copy the venv forward:
#
#   FROM dhi.io/python:3.13-dev AS deps
#   COPY --from=helm-python-sdk /opt/venv /opt/venv
#   RUN /opt/venv/bin/pip install my-extra-dependency
#   FROM helm-python-sdk
#   COPY --from=deps /opt/venv /opt/venv
#
# The SDK installs from PyPI as a prebuilt wheel (amd64 and arm64), so
# nothing compiles here and nothing is fetched from anywhere but PyPI.
#
# Base: Docker Hardened Images (Debian/glibc), digest-pinned. The -dev
# variant builds; the runtime variant ships — non-root, no shell, no
# installers, minimal libraries. Shipping -dev instead would carry its
# whole build toolchain: 180 HIGH/CRITICAL against the runtime's 10.
# Pulling dhi.io needs a (free) Docker login.

ARG HELM_PYTHON_VERSION=0.2.2

# --- Build stage: resolve the wheel into a venv -----------------------------
FROM dhi.io/python:3.13-dev@sha256:0749e2f0f23d7f10f63ee1f35ef3061a59bac601f687a67505ca670a58c1b8fb AS build
ARG HELM_PYTHON_VERSION
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# --upgrade-deps: the venv's seeded pip/setuptools carry known CVEs
# (e.g. CVE-2025-47273); start from current ones.
RUN python -m venv --upgrade-deps /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install "helm-python-sdk==${HELM_PYTHON_VERSION}" \
    && python -c "import helm_python as h; assert h.__version__ == '${HELM_PYTHON_VERSION}'" \
    && pip uninstall -y setuptools wheel pip

# --- Runtime stage ----------------------------------------------------------
FROM dhi.io/python:3.13@sha256:eedfbaf99554976858bd219321f4e79c937d63d6582574eca9c8ef2e148a0e4c
LABEL org.opencontainers.image.title="helm-python-sdk" \
      org.opencontainers.image.description="Python environment with the Helm v4 SDK binding preinstalled" \
      org.opencontainers.image.source="https://github.com/shivamkumar99/helm-python-sdk" \
      org.opencontainers.image.licenses="Apache-2.0"

# The venv stays root-owned: the runtime user can execute but not modify it.
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/nonroot \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /home/nonroot

CMD ["python"]
