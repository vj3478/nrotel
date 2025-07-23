#!/bin/bash

set -e

# Image list
IMAGES=(
  "newrelic/synthetics-job-manager"
  "newrelic/synthetics-node-api-runtime"
  "newrelic/synthetics-node-browser-runtime"
  "newrelic/synthetics-ping-runtime"
)

# Config
ARTIFACTORY="artifactory.localrepo.com"
USERNAME="your_artifactory_username"
TOKEN="your_artifactory_token"
BASE_IMAGE="artifactory.localrepo.baseimage:latest"
NOW=$(date -u +%s)
ONE_DAY_AGO=$((NOW - 86400))
WORKDIR="./docker-builds"
mkdir -p "$WORKDIR"

# Get Docker group GID from host
DOCKER_GID=$(getent group docker | cut -d: -f3)
echo "Host Docker group GID: $DOCKER_GID"

# Login once
echo "$TOKEN" | docker login "$ARTIFACTORY" --username "$USERNAME" --password-stdin

for IMAGE in "${IMAGES[@]}"; do
  echo "🔍 Checking $IMAGE..."

  TAG_INFO=$(curl -s "https://hub.docker.com/v2/repositories/${IMAGE}/tags?page_size=50" \
    | jq -r '.results[] | select(.name != "latest") | [.name, .last_updated] | @tsv' \
    | sort -k2 -r \
    | head -n1)

  TAG=$(echo "$TAG_INFO" | cut -f1)
  UPDATED_EPOCH=$(date -d "$(echo "$TAG_INFO" | cut -f2)" +%s)

  if [ "$UPDATED_EPOCH" -lt "$ONE_DAY_AGO" ]; then
    echo "⏩ No new image (tag $TAG older than 24h)"
    continue
  fi

  echo "✅ New tag detected: $TAG"

  IMAGE_NAME=$(basename "$IMAGE")
  TARGET_TAG="$ARTIFACTORY/newrelic/$IMAGE_NAME:$TAG"
  DOCKERFILE="$WORKDIR/Dockerfile.$IMAGE_NAME"

  echo "📝 Writing Dockerfile for $IMAGE_NAME..."

  cat > "$DOCKERFILE" <<EOF
FROM ${BASE_IMAGE} as golden
USER root
RUN groupadd -g ${DOCKER_GID} docker && groupadd -g 12345 runusergrp && \
    useradd -u 12345 -g 12345 runusergrp && \
    usermod -u 1000 runuser && usermod -aG docker runuser

FROM ${ARTIFACTORY}/${IMAGE}:${TAG}
COPY --from=golden /etc/passwd /etc/passwd
COPY --from=golden /etc/shadow /etc/shadow
COPY --from=golden /etc/group /etc/group

LABEL LABEL1=LABEL11
LABEL LABEL2=LABEL22
LABEL LABEL3=LABEL33
EOF

  if [[ "$IMAGE" == *"job-manager"* ]]; then
    echo 'RUN chmod 777 /data/synthetics-job-manager/bin/control' >> "$DOCKERFILE"
    echo 'USER runuser' >> "$DOCKERFILE"
  elif [[ "$IMAGE" == *"ping-runtime"* ]]; then
    echo 'RUN chmod 755 /data/synthetics-ping-runtime/bin/control' >> "$DOCKERFILE"
    echo 'USER runuser' >> "$DOCKERFILE"
  fi

  echo "🏗️  Building image: $TARGET_TAG"
  docker build -t "$TARGET_TAG" -f "$DOCKERFILE" "$WORKDIR"

  echo "📦 Pushing image: $TARGET_TAG"
  docker push "$TARGET_TAG"
  echo "✅ Done with $TARGET_TAG"
  echo "--------------------------------"
done