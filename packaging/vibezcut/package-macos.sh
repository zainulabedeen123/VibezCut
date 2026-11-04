#!/usr/bin/env bash
# Build and package VibezCut for macOS. Run on a Mac (Xcode command line tools, Rust, pwsh for the
# caption fonts). Produces in dist/vibezcut/:
#
#   VibezCut-<version>-macos-<arch>.dmg          VibezCut.app on a drag-to-Applications disk image
#   VibezCut-<version>-macos-<arch>.dmg.sha256
#
# Layout of VibezCut.app/Contents:
#   MacOS/VibezCut, MacOS/vibezcut-cli            the editor and its command line (MCP server)
#   Resources/studio/                             Python pipeline + filmcraft-studio MCP server
#   Resources/fonts/                              caption fonts (OFL / Apache 2.0, licence per family)
#   Resources/docs/, Resources/claude-skill/      STUDIO.md, WORKFLOW.md, INSTALL.md; the Claude skills
#   Resources/LICENSE-*, NOTICE, ATTRIBUTION.md, VERSION.txt
#
# Usage: packaging/vibezcut/package-macos.sh [--version X.Y.Z] [--arch universal|aarch64|x86_64]
#                                            [--skip-build] [--skip-fonts]
#
# Signing (env), the same as FilmCraft's packaging/macos/package.sh:
#   MACOS_SIGN_IDENTITY   codesign identity. Default "-" = ad-hoc: the app runs, but on another Mac
#                         Gatekeeper asks the user to allow it (System Settings > Privacy & Security >
#                         Open Anyway, or right-click > Open). packaging/macos/import-cert.sh sets it in CI.
#   MACOS_KEYCHAIN        keychain holding the identity (optional)
# Notarization (env; all three, and a real identity): APPLE_ID, APPLE_PASSWORD (app-specific), APPLE_TEAM_ID
set -euo pipefail
# shellcheck source=../env.sh
. "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
HERE="$ROOT/packaging/vibezcut"

VZ_VERSION="${VIBEZCUT_VERSION:-}"
ARCH=universal
SKIP_BUILD=0
SKIP_FONTS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VZ_VERSION="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-fonts) SKIP_FONTS=1; shift ;;
    -h | --help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
VZ_VERSION="${VZ_VERSION:-0.1.0-dev}"
VZ_VERSION="${VZ_VERSION#v}"
# baked into the binaries (filmcraft_engine::vibezcut::VERSION)
export VIBEZCUT_VERSION="$VZ_VERSION"
case "$ARCH" in
  universal) TARGETS=(aarch64-apple-darwin x86_64-apple-darwin) ;;
  aarch64) TARGETS=(aarch64-apple-darwin) ;;
  x86_64) TARGETS=(x86_64-apple-darwin) ;;
  *) echo "unknown --arch $ARCH" >&2; exit 2 ;;
esac

# Keep in sync with LSMinimumSystemVersion in macos/Info.plist.in.
export MACOSX_DEPLOYMENT_TARGET=11.0
IDENTITY="${MACOS_SIGN_IDENTITY:--}"
# CFBundleShortVersionString must be numeric X.Y.Z
SHORT_VERSION="${VZ_VERSION%%-*}"
[[ "$SHORT_VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || SHORT_VERSION=0.0.0
OUT="$ROOT/dist/vibezcut"
WORK="$CARGO_TARGET_DIR/vibezcut-macos"
APP="$WORK/VibezCut.app"
NAME="VibezCut-$VZ_VERSION-macos-$ARCH"
DMG="$OUT/$NAME.dmg"
mkdir -p "$OUT"

NOTARIZE=0
if [[ "$IDENTITY" = "-" ]]; then
  warn "macOS: ad-hoc signing (no MACOS_SIGN_IDENTITY); the DMG is not notarized"
elif [[ -n "${APPLE_ID:-}" ]] && [[ -n "${APPLE_PASSWORD:-}" ]] && [[ -n "${APPLE_TEAM_ID:-}" ]]; then
  NOTARIZE=1
else
  warn "macOS: APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID incomplete; signed but not notarized"
fi
echo "==> VibezCut $VZ_VERSION for macOS ($ARCH), identity: $IDENTITY, notarize: $NOTARIZE"

# ---- build -------------------------------------------------------------------------------------
if [[ "$SKIP_BUILD" = 0 ]]; then
  args=()
  for t in "${TARGETS[@]}"; do args+=(--target "$t"); done
  (cd "$ROOT" && cargo build --release --locked -p filmcraft -p filmcraft-cli "${args[@]}")
fi

rm -rf "$WORK"
mkdir -p "$WORK/bin"
for bin in filmcraft filmcraft-cli; do
  inputs=()
  for t in "${TARGETS[@]}"; do inputs+=("$CARGO_TARGET_DIR/$t/release/$bin"); done
  lipo -create -output "$WORK/bin/$bin" "${inputs[@]}"
  lipo -info "$WORK/bin/$bin"
done

# ---- signing helpers ---------------------------------------------------------------------------
sign() {
  # Hardened runtime + secure timestamp for a real identity; ad-hoc can't be timestamped.
  local ts=(--timestamp)
  [[ "$IDENTITY" = "-" ]] && ts=(--timestamp=none)
  local kc=()
  [[ -n "${MACOS_KEYCHAIN:-}" ]] && kc=(--keychain "$MACOS_KEYCHAIN")
  codesign --force --sign "$IDENTITY" ${kc[@]+"${kc[@]}"} "${ts[@]}" "$@"
}

notarize() {
  local file="$1" out id status
  echo "==> notarizing $(basename "$file") (this can take a few minutes)"
  out="$(xcrun notarytool submit "$file" --apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" --wait --timeout 1h --output-format json)" || true
  echo "$out"
  id="$(printf '%s' "$out" | plutil -extract id raw -o - - 2>/dev/null || true)"
  status="$(printf '%s' "$out" | plutil -extract status raw -o - - 2>/dev/null || true)"
  if [[ "$status" != "Accepted" ]]; then
    if [[ -n "$id" ]]; then
      xcrun notarytool log "$id" --apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" --team-id "$APPLE_TEAM_ID" || true
    fi
    echo "error: notarization of $(basename "$file") failed (status: ${status:-unknown})" >&2
    exit 1
  fi
}

# ---- icon --------------------------------------------------------------------------------------
# Built from the macOS-style PNG (tile inside Apple's margin); not committed.
ICONSET="$WORK/VibezCut.iconset"
mkdir -p "$ICONSET"
SRC_ICON="$ROOT/assets/app-icon/vibezcut-macos-512.png"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$SRC_ICON" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  if [[ "$d" -le 512 ]]; then sips -z "$d" "$d" "$SRC_ICON" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null; fi
done
iconutil -c icns "$ICONSET" -o "$WORK/VibezCut.icns"

# ---- VibezCut.app ------------------------------------------------------------------------------
echo "==> assembling $APP"
RES="$APP/Contents/Resources"
mkdir -p "$APP/Contents/MacOS" "$RES"
# The executable carries the display name (CFBundleExecutable); the CLI sits next to it so the
# Studio finds both (studio/studio/config.py looks in Contents/MacOS).
cp "$WORK/bin/filmcraft" "$APP/Contents/MacOS/VibezCut"
cp "$WORK/bin/filmcraft-cli" "$APP/Contents/MacOS/vibezcut-cli"
cp "$WORK/VibezCut.icns" "$RES/VibezCut.icns"
sed -e "s/@VERSION@/$VZ_VERSION/g" -e "s/@SHORT_VERSION@/$SHORT_VERSION/g" \
  -e "s/@BUILD_SHA@/${FILMCRAFT_BUILD_SHA:-unknown}/g" \
  "$HERE/macos/Info.plist.in" >"$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"
printf 'APPL????' >"$APP/Contents/PkgInfo"

# Studio layer (no per-machine settings, no caches)
mkdir -p "$RES/studio"
cp "$ROOT/studio/run_server.py" "$ROOT/studio/requirements.txt" "$RES/studio/"
cp -R "$ROOT/studio/studio" "$ROOT/studio/assets" "$RES/studio/"
find "$RES/studio" \( -name '__pycache__' -o -name 'studio.json' -o -name '.DS_Store' \) -prune -exec rm -rf {} +

mkdir -p "$RES/docs" "$RES/claude-skill"
cp "$ROOT"/docs/vibezcut/*.md "$RES/docs/"
for skill in filmcraft-edit pack-for-editor; do cp -R "$ROOT/.claude/skills/$skill" "$RES/claude-skill/"; done

# caption fonts, loaded at startup from Contents/Resources/fonts (filmcraft_engine::load_bundled_fonts)
if [[ "$SKIP_FONTS" = 0 ]]; then
  pwsh -NoProfile -File "$HERE/bundle-fonts.ps1" -Dest "$RES/fonts"
  # Inter is compiled into VibezCut; the caption tools also need the files to measure text
  mkdir -p "$RES/fonts/Inter"
  cp "$ROOT"/assets/fonts/Inter-*.ttf "$RES/fonts/Inter/"
  cp "$ROOT/assets/fonts/OFL-Inter.txt" "$RES/fonts/Inter/OFL.txt"
fi

for f in LICENSE-MIT LICENSE-APACHE NOTICE ATTRIBUTION.md; do cp "$ROOT/$f" "$RES/"; done
copy_font_licences "$RES"
printf 'VibezCut %s\nbased on FilmCraft %s\ncommit %s\n' "$VZ_VERSION" "$VERSION" \
  "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)" >"$RES/VERSION.txt"
xattr -cr "$APP"

# Sign inside-out: nested code first, then the bundle itself (no --deep on the final signature).
sign --options runtime --entitlements "$ROOT/packaging/macos/entitlements.plist" "$APP/Contents/MacOS/vibezcut-cli"
sign --options runtime --entitlements "$ROOT/packaging/macos/entitlements.plist" "$APP/Contents/MacOS/VibezCut"
sign --options runtime --entitlements "$ROOT/packaging/macos/entitlements.plist" "$APP"
codesign --verify --strict --deep --verbose=2 "$APP"

if [[ "$NOTARIZE" = 1 ]]; then
  ditto -c -k --keepParent "$APP" "$WORK/VibezCut-notarize.zip"
  notarize "$WORK/VibezCut-notarize.zip"
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  spctl --assess --type execute -vvv "$APP"
fi

# ---- DMG ---------------------------------------------------------------------------------------
echo "==> building $DMG"
STAGE="$WORK/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/VibezCut.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG" "$WORK/raw.dmg"
# makehybrid + convert builds the image without attaching a device (`create -srcfolder` is flaky
# on CI runners).
hdiutil makehybrid -hfs -hfs-volume-name "VibezCut $VZ_VERSION" -hfs-openfolder "$STAGE" -o "$WORK/raw.dmg" "$STAGE"
hdiutil convert "$WORK/raw.dmg" -format UDZO -imagekey zlib-level=9 -o "$DMG"
rm -f "$WORK/raw.dmg"
sign "$DMG"
codesign --verify --strict --verbose=2 "$DMG"
if [[ "$NOTARIZE" = 1 ]]; then
  notarize "$DMG"
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
fi
printf '%s  %s\n' "$(sha256 "$DMG")" "$(basename "$DMG")" >"$DMG.sha256"

"$APP/Contents/MacOS/vibezcut-cli" --version
echo "==> done"
ls -lh "$DMG"
cat "$DMG.sha256"
