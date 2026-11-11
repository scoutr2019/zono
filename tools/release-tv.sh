#!/usr/bin/env bash
# Builds Zono for TV (LG + Android TV) into tv/ in the repository and pushes it.
# The files always have the same names, so zono.be/apps, zono.be/apk and zono.be/lg show the new version by themselves.
# (Not a GitHub release: "latest" belongs to Zono for Windows, whose updater reads it.)
# Needs: ares-package (webOS CLI), the Android SDK, and ZONO_TV_KEYSTORE + ZONO_TV_KEYSTORE_PASSWORD (never in git).
# Usage: tools/release-tv.sh "what changed"
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(grep -o 'VERSION = "[^"]*"' webos/js/app.js | cut -d'"' -f2)
NOTES=${1:-"Zono for TV $VERSION"}
OUT=$(mktemp -d)

rm -rf webos/dist && (cd webos && ares-package . -o dist >/dev/null)
cp webos/dist/*_"$VERSION"_all.ipk "$OUT/Zono-TV.ipk"
(cd android && ./gradlew --no-daemon -q assembleRelease)
cp android/app/build/outputs/apk/release/app-release.apk "$OUT/Zono-TV.apk"

mkdir -p tv
cp "$OUT/Zono-TV.ipk" "$OUT/Zono-TV.apk" tv/
printf '{"version": "%s", "date": "%s", "apk": %s, "ipk": %s}\n' "$VERSION" "$(date +%F)" "$(stat -c%s tv/Zono-TV.apk)" "$(stat -c%s tv/Zono-TV.ipk)" > tv/version.json
git add tv
git commit -qm "Zono TV $VERSION: $NOTES" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -q
echo "Zono TV $VERSION is online (zono.be/apps, zono.be/apk, zono.be/lg)."
