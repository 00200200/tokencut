#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Optional artwork build tools: librsvg, FFmpeg and ImageMagick. Reuses the unmodified pet.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
rsvg-convert assets/readme-hero.svg -o "$work/background.png"
ffmpeg -hide_banner -loglevel error -y -loop 1 -t 4 -i "$work/background.png" -loop 1 -t 4 -i assets/pet-3d.png \
  -filter_complex "[1:v]scale=340:340[pet];[0:v][pet]overlay=x=675:y='8+6*sin(2*PI*t/4)',fps=10,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -t 4 -loop 0 "$work/animation.gif"
magick "$work/animation.gif" -coalesce -layers Optimize assets/readme-hero.gif
ffmpeg -hide_banner -loglevel error -y -i assets/readme-hero.gif -frames:v 1 assets/readme-hero.png
printf 'README animation and reduced-motion poster generated.\n'
