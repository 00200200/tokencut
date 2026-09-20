#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# Local, ad-hoc signed build. No public installer or notarization is implied.
output="${TOKENCUT_APP_OUTPUT:-$PWD/build/TokenCut.app}"
executable="${TOKENCUT_EXECUTABLE:-$HOME/.local/bin/tokencut}"
swift build -c release
mkdir -p "$output/Contents/MacOS" "$output/Contents/Resources"
cp .build/release/TokenCutMenu "$output/Contents/MacOS/TokenCutMenu"
/usr/bin/python3 - "$output/Contents/Info.plist" "$executable" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as file:
    plistlib.dump({
        'CFBundleName': 'TokenCut', 'CFBundleDisplayName': 'TokenCut',
        'CFBundleIdentifier': 'com.tokencut.menu', 'CFBundleVersion': '1',
        'CFBundleShortVersionString': '0.1.0', 'CFBundlePackageType': 'APPL',
        'CFBundleExecutable': 'TokenCutMenu', 'LSUIElement': True,
        'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
        'TokenCutExecutable': sys.argv[2],
    }, file)
PY
codesign --force --sign - "$output"
printf '%s\n' "$output"
