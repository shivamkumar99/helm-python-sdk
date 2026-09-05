# A ready-to-use Python environment with helm-python-sdk preinstalled.
#
#   docker build -t helm-python-sdk .
#   docker run -it --rm -v ~/.kube/config:/home/helm/.kube/config:ro \
#     helm-python-sdk python
#   >>> import helm_python as helm
#
# Intended as a base for Helm automation scripts and CI jobs:
#
#   FROM helm-python-sdk
#   COPY my_job.py .
#   CMD ["python", "my_job.py"]
#
# The SDK installs from PyPI as a prebuilt wheel — the native library
# arrives inside it, nothing compiles here and nothing is fetched from
# anywhere but PyPI. pip stays available so derived images can add their
# own dependencies.

ARG HELM_PYTHON_VERSION=0.2.1

FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
ARG HELM_PYTHON_VERSION
LABEL org.opencontainers.image.title="helm-python-sdk" \
      org.opencontainers.image.description="Python environment with the Helm v4 SDK binding preinstalled" \
      org.opencontainers.image.source="https://github.com/shivamkumar99/helm-python-sdk" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN pip install "helm-python-sdk==${HELM_PYTHON_VERSION}" \
    && python -c "import helm_python as h; assert h.__version__ == '${HELM_PYTHON_VERSION}'"

RUN useradd --create-home --shell /usr/sbin/nologin helm
USER helm
WORKDIR /home/helm

CMD ["python"]
