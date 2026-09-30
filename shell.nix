# shell.nix — non-flake entry point.
#
# Prefererar flakens devShell (nixos-unstable => modern uv som kan läsa
# projektets uv.lock). Gamla nixpkgs-kanaler (t.ex. nixos-24.05) skeppar en
# uv som är för gammal för lockformatet ("missing field `distribution`"),
# därför delegerar vi till flaket när flakes är tillgängliga.
#
#   nix-shell          <- denna fil
#   nix develop        <- flake.nix (rekommenderas)
#
# Om flakes inte är aktiverade faller skalmetoden tillbaka på ett standalone-
# skal UTAN uv: använd då pip-workflödet:
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt
#   uvicorn app.main:app --reload
let
  system = builtins.currentSystem;
  flakeShell = builtins.tryEval
    ((builtins.getFlake (toString ./.)).devShells.${system}.default);
in
if flakeShell.success then
  flakeShell.value
else
  let
    pkgs = import <nixpkgs> { };

    weasyprintNativeLibs = with pkgs; [
      pango cairo gdk-pixbuf harfbuzz fontconfig glib
      libffi zlib libjpeg openjpeg freetype libxml2 libxslt shared-mime-info
    ];
    pdfFonts = [ pkgs.dejavu_fonts pkgs.liberation_ttf ];
  in
  pkgs.mkShell {
    packages = [ pkgs.python312 pkgs.python312Packages.pip pkgs.git ];
    buildInputs = weasyprintNativeLibs ++ pdfFonts;

    shellHook = ''
      export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath (weasyprintNativeLibs ++ pdfFonts)}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      export FONTCONFIG_PATH="${pkgs.fontconfig.out}/etc/fonts"
      export FIRMA_DATA_DIR="''${FIRMA_DATA_DIR:-$PWD/data}"
      echo "──────────────────────────────────────────────────────────"
      echo " Firmabok fallback-shell (ingen uv här: din nixpkgs-kanals uv"
      echo " är för gammal för projektets uv.lock)."
      echo ""
      echo "   python3 -m venv .venv && source .venv/bin/activate"
      echo "   pip install -r requirements.txt"
      echo "   uvicorn app.main:app --reload        # http://127.0.0.1:8000"
      echo ""
      echo " Rekommenderat: nix develop (flaket ger modern uv + samma libs)"
      echo "──────────────────────────────────────────────────────────"
    '';
  }
