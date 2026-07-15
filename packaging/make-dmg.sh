#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
#
# Build the macOS disk image, laid out so it explains itself.
#
# A plain `hdiutil create` gives you a window with two icons in it and no hint of what to do.
# The first person to open one ran the app straight from the disk image, which is the thing a
# disk image exists to stop you doing: the app is not installed, macOS asks about the download
# every single time, and deleting the image takes the app with it.
#
# So we lay the window out: the app on the left, the Applications folder on the right, and the
# arrow between them that everyone has seen a hundred times. Finder stores that layout in a
# .DS_Store inside the image, which is why the image has to be writable first and compressed
# afterwards.
#
#   make-dmg.sh <path to .app> <output .dmg>
set -euo pipefail

APP="$1"
OUT="$2"
VOLUME="Foxentry Data Cleaner"
STAGE="$(mktemp -d)"
TEMP_DMG="$(mktemp -u).dmg"

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$STAGE/.background"
cp packaging/dmg-background.png "$STAGE/.background/background.png"

# Writable, so Finder can save the layout into it.
hdiutil create -volname "$VOLUME" -srcfolder "$STAGE" -ov -fs HFS+ -format UDRW "$TEMP_DMG" >/dev/null
DEVICE=$(hdiutil attach -readwrite -noverify -noautoopen "$TEMP_DMG" | grep '^/dev/' | head -1 | awk '{print $1}')
MOUNT="/Volumes/$VOLUME"
sleep 2

osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "$VOLUME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 800, 520}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 128
    set background picture of opts to file ".background:background.png"
    set position of item "Foxentry Data Cleaner.app" of container window to {150, 200}
    set position of item "Applications" of container window to {450, 200}
    close
    open
    update without registering applications
    delay 2
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$DEVICE" >/dev/null
hdiutil convert "$TEMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$OUT" -ov >/dev/null
rm -rf "$STAGE" "$TEMP_DMG"
echo "Built $OUT"
