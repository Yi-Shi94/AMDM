#!/usr/bin/env bash
# Download the T=16 LAFAN1 prior, the five controllers and the LAFAN1 BVH clips, verify them and unpack them into
# the project root (interactive_control/). Usage: bash scripts/download.sh [--no-lafan]   (run from anywhere)
set -euo pipefail
BASE="${AMDM_RELEASE_URL:-https://github.com/Yi-Shi94/AMDM/releases/download/interactive-v1.0}"
cd "$(dirname "$0")/.."
files=(amdm_lafan1_t16.zip amdm_interactive_controllers.zip lafan1_bvh.zip)
[ "${1:-}" = "--no-lafan" ] && files=(amdm_lafan1_t16.zip amdm_interactive_controllers.zip)
mkdir -p downloads
fetch() { if command -v curl >/dev/null; then curl -fL --progress-bar -o "$2" "$1"; else wget -q --show-progress -O "$2" "$1"; fi; }
fetch "$BASE/SHA256SUMS" downloads/SHA256SUMS
for f in "${files[@]}"; do
    [ -f "downloads/$f" ] || fetch "$BASE/$f" "downloads/$f"
    (cd downloads && grep " $f\$" SHA256SUMS | sha256sum -c -)
    unzip -q -o "downloads/$f" -d .
done
echo "Done: output/base/amdm_lafan1_t16, output/interactive/*$( [ ${#files[@]} -eq 3 ] && echo ', data/LAFAN1/*.bvh')"
