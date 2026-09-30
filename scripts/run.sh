#!/usr/bin/env bash
# Starta Firmabok med garanterad WeasyPrint-miljö på NixOS — oavsett skal.
# Fungerar både i och utanför nix-shell: beräknar LD_LIBRARY_PATH direkt
# från nixpkgs om den saknas, aktiverar .venv om sådan finns.
#
#   scripts/run.sh                # uvicorn --reload på 127.0.0.1:8000
#   scripts/run.sh --port 8001    # valfri port
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -d /nix/store ]; then
  # --raw finns inte i äldre Nix: --eval citerar strängen, så vi strippar citattecken
  LIBS="$(nix-instantiate --eval -E 'with import <nixpkgs> {}; lib.makeLibraryPath [pango cairo gdk-pixbuf harfbuzz fontconfig glib libffi zlib libjpeg openjpeg freetype libxml2 libxslt shared-mime-info]' 2>/dev/null | tr -d '"' || true)"
  if [ -n "$LIBS" ]; then
    export LD_LIBRARY_PATH="$LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
  FCP="$(nix-instantiate --eval -E 'with import <nixpkgs> {}; fontconfig.out + "/etc/fonts"' 2>/dev/null | tr -d '"' || true)"
  if [ -n "$FCP" ]; then export FONTCONFIG_PATH="$FCP"; fi
fi

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f .venv/bin/activate ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

exec uvicorn app.main:app --reload "$@"
