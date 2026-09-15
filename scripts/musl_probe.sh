#!/bin/sh
# What a user on musl (Alpine and kin) actually experiences.
#
# Go cannot yet build a c-shared library musl's loader will dlopen
# (golang/go#54805), so importing this package on musl must fail — but it
# must fail *well*: naming musl, citing the upstream issue, and not
# suggesting a source build that hits the same wall. This probe builds the
# whole stack against musl and asserts exactly that.
#
# It doubles as a watch on the upstream fix: if the import ever succeeds,
# the probe says so loudly, because musllinux wheels and an Alpine image
# become worth shipping that day.
#
# Run inside an Alpine container with the repository at /work and a
# helm-c-sdk checkout at /work/helm-c:
#   docker run --rm -v "$PWD:/work" -w /work python:3.13-alpine \
#     sh scripts/musl_probe.sh
set -eu

echo "installing the musl toolchain"
apk add --no-cache go gcc musl-dev make git >/dev/null

echo "building libhelm_c against musl"
( cd helm-c && CGO_ENABLED=1 make build VERSION=0.0.0-musl >/dev/null )

echo "installing the binding with that library"
mkdir -p src/helm_python/lib
cp helm-c/build/libhelm_c.so* src/helm_python/lib/
python -m venv /tmp/venv
/tmp/venv/bin/pip install --quiet . >/dev/null

/tmp/venv/bin/python - <<'PY'
import sys

try:
    import helm_python as helm
except Exception as exc:                      # noqa: BLE001 - any failure is the subject
    text = str(exc)
    print("import failed on musl, as expected:")
    print("  " + text[:400])
    problems = []
    if "musl" not in text:
        problems.append("the message does not name musl")
    if "golang/go#54805" not in text:
        problems.append("the message does not cite the upstream issue")
    if "HELM_PYTHON_BUILD=1" in text:
        problems.append("the message suggests a source build, which cannot work here")
    if problems:
        for problem in problems:
            print(f"::error::musl diagnosis regressed: {problem}")
        sys.exit(1)
    print("::notice::musl remains blocked upstream and the diagnosis is correct")
    sys.exit(0)

print(
    "::warning::helm_python imported successfully on musl — golang/go#54805 "
    "appears fixed. Ship musllinux wheels and revisit the Alpine base image."
)
print("versions:", helm.helm_c_version(), helm.helm_sdk_version())
PY
