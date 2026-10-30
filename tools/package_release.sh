#!/usr/bin/env bash
# Package each mod variant as an Eden-importable zip (zip root = "<Mod Name>/exefs/*.pchtxt",
# which Eden's "Import Mod from ZIP" detects via its exefs folder scan).
# Usage: tools/package_release.sh <version>   (e.g. v0.3.0-alpha)
set -euo pipefail
VER="${1:?usage: package_release.sh <version>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist/$VER"
rm -rf "$DIST"; mkdir -p "$DIST"
cd "$ROOT/mods"
zip -qr "$DIST/WildBattlesEXP-$VER.zip" "Wild Battles EXP"
zip -qr "$DIST/WildBattlesEXP-CatchVariant-$VER.zip" "Wild Battles EXP (Catch Variant)"
( cd "addon-only (needs base Wild Battles)" && zip -qr "$DIST/WildBattlesEXP-Addon-$VER.zip" "Wild Battles EXP Addon" )
for z in "$DIST"/*.zip; do echo "== $z"; unzip -l "$z" | sed -n '4,8p'; done
