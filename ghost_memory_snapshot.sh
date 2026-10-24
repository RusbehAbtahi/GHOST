#!/usr/bin/env bash
set -euo pipefail

REPO="/home/rusbeh_ab/project/RAGstream"
BUCKET="ghost-ragstream-memory-backup-108782059508-eu-central-1"
REGION="eu-central-1"

cd "$REPO"

# Do not snapshot while the MCP server is running.
if pgrep -f "python -m ragstream.mcp.server" >/dev/null; then
    echo "ERROR: GHOST MCP server is running. Stop it before creating the snapshot."
    exit 1
fi

TIMESTAMP="$(date -u +'%Y-%m-%dT%H-%M-%SZ')"
GIT_COMMIT="$(git rev-parse HEAD)"
SHORT_COMMIT="$(git rev-parse --short HEAD)"

SNAPSHOT="GHOST_MEMORY_LOCAL_${TIMESTAMP}_${SHORT_COMMIT}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

ARCHIVE="$TMPDIR/${SNAPSHOT}.tar.gz"
MANIFEST="$TMPDIR/${SNAPSHOT}.manifest.txt"
CHECKSUM="$TMPDIR/${SNAPSHOT}.sha256"

tar -czf "$ARCHIVE" \
    data/mcp/memory \
    data/memory

sha256sum "$ARCHIVE" > "$CHECKSUM"

cat > "$MANIFEST" <<EOF
snapshot_name=${SNAPSHOT}
source=LOCAL
created_utc=${TIMESTAMP}
git_commit=${GIT_COMMIT}
repository=${REPO}
included=data/mcp/memory
included=data/memory
archive_sha256=$(sha256sum "$ARCHIVE" | awk '{print $1}')
EOF

S3_PREFIX="s3://${BUCKET}/ghost-memory-snapshots/LOCAL/${TIMESTAMP}"

aws s3 cp "$ARCHIVE" \
    "${S3_PREFIX}/${SNAPSHOT}.tar.gz" \
    --region "$REGION" \
    --sse AES256 \
    --only-show-errors

aws s3 cp "$MANIFEST" \
    "${S3_PREFIX}/${SNAPSHOT}.manifest.txt" \
    --region "$REGION" \
    --sse AES256 \
    --only-show-errors

aws s3 cp "$CHECKSUM" \
    "${S3_PREFIX}/${SNAPSHOT}.sha256" \
    --region "$REGION" \
    --sse AES256 \
    --only-show-errors

echo
echo "Snapshot uploaded successfully:"
echo "${S3_PREFIX}/${SNAPSHOT}.tar.gz"