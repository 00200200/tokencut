#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# Local, ad-hoc signed build. No public installer or notarization is implied.
output="${USAGETRIM_APP_OUTPUT:-$PWD/build/UsageTrim.app}"
executable="${USAGETRIM_EXECUTABLE:-}"
swift build -c release
mkdir -p "$output/Contents/MacOS" "$output/Contents/Resources"
cp .build/release/UsageTrimMenu "$output/Contents/MacOS/UsageTrimMenu"
cp Sources/UsageTrimMenu/Resources/pet-3d.png "$output/Contents/Resources/pet-3d.png"
/usr/bin/python3 - "$output/Contents/Info.plist" "$executable" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as file:
    info = {
        'CFBundleName': 'UsageTrim', 'CFBundleDisplayName': 'UsageTrim',
        'CFBundleIdentifier': 'com.usagetrim.menu', 'CFBundleVersion': '1',
        'CFBundleShortVersionString': '0.4.0', 'CFBundlePackageType': 'APPL',
        'CFBundleExecutable': 'UsageTrimMenu', 'LSUIElement': True,
        'CFBundleDevelopmentRegion': 'en', 'CFBundleLocalizations': ['en'],
        'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
    }
    # Resolve the default backend in the running user's home, not the builder's.
    if sys.argv[2]:
        info['UsageTrimExecutable'] = sys.argv[2]
    plistlib.dump(info, file)
PY
codesign --force --sign - "$output"
printf '%s\n' "$output"
