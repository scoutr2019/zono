#!/bin/sh
# Builds the LG app file: dist/be.zono.tv_<version>_all.ipk  (needs: npm install -g @webos-tools/cli)
set -e
cd "$(dirname "$0")"
rm -rf dist/app && mkdir -p dist/app
cp -r appinfo.json index.html style.css js img dist/app/
ares-package dist/app -o dist
rm -rf dist/app
ls dist/*.ipk
