#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
RELEASE_YAML="${REPO_ROOT}/brain/infrastructure/service/agent_abilities/releases/current/RELEASE.yaml"

# 从 RELEASE.yaml 读取版本号
if [[ -f "${RELEASE_YAML}" ]]; then
    VERSION="v$(grep '^version:' "${RELEASE_YAML}" | head -1 | awk '{print $2}' | tr -d '"')"
else
    echo "WARNING: RELEASE.yaml not found, using 'dev' as version"
    VERSION="dev"
fi

echo "Building brain-spec:${VERSION}"

# .dockerignore 必须在 build context 根目录才能生效
DOCKERIGNORE="${REPO_ROOT}/.dockerignore"
DOCKERIGNORE_BAK=""
if [[ -f "${DOCKERIGNORE}" ]]; then
    DOCKERIGNORE_BAK="${DOCKERIGNORE}.bak.brain-spec"
    cp "${DOCKERIGNORE}" "${DOCKERIGNORE_BAK}"
fi
cp "${SCRIPT_DIR}/.dockerignore" "${DOCKERIGNORE}"
trap 'if [[ -n "${DOCKERIGNORE_BAK}" ]]; then mv "${DOCKERIGNORE_BAK}" "${DOCKERIGNORE}"; else rm -f "${DOCKERIGNORE}"; fi' EXIT

docker build \
    -f "${SCRIPT_DIR}/Dockerfile" \
    --build-arg SPEC_VERSION="${VERSION}" \
    -t "brain-spec:${VERSION}" \
    -t "brain-spec:latest" \
    "${REPO_ROOT}"

echo "Done. Images:"
docker images brain-spec --format "  {{.Repository}}:{{.Tag}}  {{.Size}}"
