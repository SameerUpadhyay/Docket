#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${JAVA_HOME:-}" && -x "$JAVA_HOME/bin/java" ]]; then
  docket_jdk="$JAVA_HOME"
elif [[ -x "$PWD/.tools/jdk17/Contents/Home/bin/java" ]]; then
  docket_jdk="$PWD/.tools/jdk17/Contents/Home"
elif [[ -x /usr/libexec/java_home ]]; then
  docket_jdk="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
else
  docket_jdk=""
fi
if [[ -z "$docket_jdk" || ! -x "$docket_jdk/bin/java" ]]; then
  echo 'Set JAVA_HOME to a JDK 17+ installation, then run this script again.' >&2
  exit 1
fi
export JAVA_HOME="$docket_jdk"
docket_sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
if [[ ! -f android/local.properties && -d "$docket_sdk" ]]; then
  printf 'sdk.dir=%s\n' "$docket_sdk" > android/local.properties
fi
if command -v gradle >/dev/null 2>&1; then
  docket_gradle="$(command -v gradle)"
else
  docket_gradle="$(find "${GRADLE_USER_HOME:-$HOME/.gradle}/wrapper/dists/gradle-8.14.3-all" -type f -path '*/bin/gradle' -print -quit 2>/dev/null || true)"
  if [[ -z "$docket_gradle" ]]; then docket_gradle="$PWD/android/gradlew"; fi
fi
"$docket_gradle" -p android :app:assembleDebug :app:testDebugUnitTest --console=plain "$@"
mkdir -p output/android
cp android/app/build/outputs/apk/debug/app-debug.apk output/android/docket-debug.apk
(cd output/android && shasum -a 256 docket-debug.apk > SHA256SUMS.txt)
printf '\nAPK: %s/output/android/docket-debug.apk\n' "$PWD"
