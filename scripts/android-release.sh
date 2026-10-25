#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DOCKET_API_ORIGIN:?Set the deployed HTTPS API origin before building a public release}"
if [[ "$DOCKET_API_ORIGIN" != https://* ]]; then echo "A release requires an HTTPS API origin." >&2; exit 1; fi
: "${DOCKET_UPLOAD_KEYSTORE:?Set DOCKET_UPLOAD_KEYSTORE to the private upload keystore path}"
: "${DOCKET_UPLOAD_STORE_PASSWORD:?Set upload store password through your secret manager}"
: "${DOCKET_UPLOAD_KEY_ALIAS:?Set upload key alias}"
: "${DOCKET_UPLOAD_KEY_PASSWORD:?Set upload key password through your secret manager}"
# Reuses the configured JDK/SDK and wrapper; secrets are consumed by Gradle from env.
bash scripts/android-build.sh :app:bundleRelease
printf 'Signed app bundle: %s/android/app/build/outputs/bundle/release/app-release.aab\n' "$PWD"
