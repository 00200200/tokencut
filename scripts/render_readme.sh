#!/usr/bin/env bash
# Build sharp README hero poster, social preview, companion card, and optional GIF.
# The static PNG is composited from SVG + pet artwork — never extracted from the GIF.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need rsvg-convert
need magick

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# --- High-quality static hero (2x render → Lanczos downscale) ---
rsvg-convert -w 2560 -h 1280 assets/readme-hero.svg -o "$work/hero-bg.png"

magick assets/pet-3d.png -resize 780x780 "$work/pet.png"

# Pet sits in the reserved right glow zone of the SVG
magick "$work/hero-bg.png" \
  "$work/pet.png" -geometry +1680+200 -compose over -composite \
  -filter Lanczos -resize 1280x640 \
  -unsharp 0x0.55+0.55+0.02 \
  -strip \
  -depth 8 \
  assets/readme-hero.png

magick assets/readme-hero.png -strip assets/social-preview.png

# --- macOS companion card (replaces the old 310×170 JPEG) ---
rsvg-convert -w 860 -h 400 assets/macos-pet-card.svg -o "$work/card.png"
magick assets/pet-3d.png -resize 400x400 "$work/pet-sm.png"
magick -size 1280x560 xc:'#050b10' \
  "$work/pet-sm.png" -geometry +40+70 -compose over -composite \
  "$work/card.png" -geometry +400+80 -compose over -composite \
  -unsharp 0x0.45+0.45+0.02 \
  -strip \
  -depth 8 \
  assets/macos-pet.png

# --- Animated hero: subtle mint glow pulse (poster stays independent) ---
magick assets/readme-hero.png -write mpr:base +delete \
  \( mpr:base \) \
  \( mpr:base -fill '#2ec79b' -colorize 6% \) \
  \( mpr:base \) \
  \( mpr:base -fill '#2ec79b' -colorize 3% \) \
  -set delay 14 -loop 0 "$work/pulse.gif"
magick "$work/pulse.gif" -coalesce -layers OptimizeFrame assets/readme-hero.gif

printf 'Generated:\n  assets/readme-hero.png (%s)\n  assets/readme-hero.gif (%s)\n  assets/social-preview.png (%s)\n  assets/macos-pet.png (%s)\n' \
  "$(magick identify -format '%wx%h' assets/readme-hero.png)" \
  "$(magick identify -format '%wx%h' assets/readme-hero.gif)" \
  "$(magick identify -format '%wx%h' assets/social-preview.png)" \
  "$(magick identify -format '%wx%h' assets/macos-pet.png)"
