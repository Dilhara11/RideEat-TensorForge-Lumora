#!/usr/bin/env bash
# Build the API image inside AWS from a commit that is already on GitHub (CodeBuild project from build.yaml):
#   1) native x86_64 and arm64 builds in parallel  -> ECR <tag>-amd64, <tag>-arm64
#   2) join them                                     -> ECR <tag>  (multi-arch: use this one)
# Only small API calls leave this machine. Prints the tag to put in samconfig.toml (ImageTag).
#   ./scripts/cloud-build.sh              # the commit checked out (HEAD)
#   ./scripts/cloud-build.sh <git-ref>    # any pushed branch, tag or commit
set -euo pipefail
PROJECT=${PROJECT:-tensorforge-api-image}
REF=${1:-HEAD}

SHA=$(git rev-parse --verify "$REF^{commit}")
git fetch -q origin
if [ -z "$(git branch -r --contains "$SHA")" ]; then
  echo "commit $SHA is not on GitHub yet: push it first (git push)" >&2
  exit 1
fi
TAG=${TAG:-$(date -u +%Y%m%d-%H%M)-${SHA:0:7}}

start() { # start <stage> [extra start-build args]
  local stage=$1
  shift
  aws codebuild start-build --project-name "$PROJECT" \
    --environment-variables-override \
      "name=STAGE,value=$stage" "name=GIT_SHA,value=$SHA" "name=IMAGE_TAG,value=$TAG" \
    "$@" --query build.id --output text
}

wait_for() { # wait_for <build id>...
  local status
  while :; do
    status=$(aws codebuild batch-get-builds --ids "$@" \
      --query 'builds[].[buildStatus,currentPhase,id]' --output text)
    echo "$(date +%T)"
    echo "$status" | sed 's/^/  /'
    if echo "$status" | grep -qE '^(FAILED|FAULT|STOPPED|TIMED_OUT)'; then
      echo "build failed. Logs: aws logs tail /tensorforge/codebuild --since 1h" >&2
      return 1
    fi
    if [ "$(echo "$status" | grep -c '^SUCCEEDED')" -eq "$#" ]; then
      return 0
    fi
    sleep 30
  done
}

echo "building commit $SHA as $TAG (amd64 + arm64, ~10-20 min)"
AMD64=$(start image)
ARM64=$(start image --environment-type-override ARM_CONTAINER \
  --image-override aws/codebuild/amazonlinux-aarch64-standard:3.0 --compute-type-override BUILD_GENERAL1_MEDIUM)
wait_for "$AMD64" "$ARM64"

echo "joining into one multi-arch tag"
INDEX=$(start index)
wait_for "$INDEX"

echo
echo "Done. In samconfig.toml [api.deploy.parameters] set:  ImageTag=\"$TAG\""
