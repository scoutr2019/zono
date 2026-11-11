#!/usr/bin/env bash
# Publishes Zono for TV (LG + Android TV) on GitHub, in the release with tag "tv".
# The files always have the same names, so zono.be/apps, zono.be/apk and zono.be/lg show the new version by themselves.
# The release is never marked "latest": that one belongs to Zono for Windows (its updater reads it).
# Needs: ares-package (webOS CLI), the Android SDK, gh, and ZONO_TV_KEYSTORE + ZONO_TV_KEYSTORE_PASSWORD (never in git).
# Usage: tools/release-tv.sh "notes in markdown"
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=scoutr2019/zono
VERSION=$(grep -o 'VERSION = "[^"]*"' webos/js/app.js | cut -d'"' -f2)
NOTES=${1:-"Zono for TV $VERSION"}
OUT=$(mktemp -d)

rm -rf webos/dist && (cd webos && ares-package . -o dist >/dev/null)
cp webos/dist/*_"$VERSION"_all.ipk "$OUT/Zono-TV.ipk"
(cd android && ./gradlew --no-daemon -q assembleRelease)
cp android/app/build/outputs/apk/release/app-release.apk "$OUT/Zono-TV.apk"

BODY=$(printf '%s\n\n**Android TV:** type `zono.be/apk` in the Downloader app.  \n**LG:** install `Zono-TV.ipk` with webOS Dev Manager.  \nStep by step: https://zono.be/apps/' "$NOTES")
ID=$(gh api "repos/$REPO/releases/tags/tv" --jq .id 2>/dev/null || true)
if [ -z "$ID" ]; then
  ID=$(gh api "repos/$REPO/releases" -f tag_name=tv -f target_commitish="$(git rev-parse HEAD)" \
       -f name="Zono TV $VERSION" -f body="$BODY" -F prerelease=false -f make_latest=false --jq .id)
else
  git tag -f tv && git push -f origin tv >/dev/null 2>&1
  gh api -X PATCH "repos/$REPO/releases/$ID" -f name="Zono TV $VERSION" -f body="$BODY" -f make_latest=false >/dev/null
fi
for f in Zono-TV.apk Zono-TV.ipk; do
  OLD=$(gh api "repos/$REPO/releases/$ID/assets" --jq ".[] | select(.name==\"$f\") | .id")
  [ -n "$OLD" ] && gh api -X DELETE "repos/$REPO/releases/assets/$OLD"
  case $f in *.apk) T=application/vnd.android.package-archive;; *) T=application/octet-stream;; esac
  gh api -X POST "https://uploads.github.com/repos/$REPO/releases/$ID/assets?name=$f" -H "Content-Type: $T" --input "$OUT/$f" --jq .browser_download_url
done
echo "Zono TV $VERSION published."
