# Legacy dev shell (non-flake): nix-shell
{ pkgs ? import <nixpkgs> { } }:
let
  weasyprintNativeLibs = with pkgs; [
    pango cairo gdk-pixbuf harfbuzz fontconfig glib
    libffi zlib libjpeg openjpeg freetype libxml2 libxslt shared-mime-info
  ];
  pdfFonts = [ pkgs.dejavu_fonts pkgs.liberation_ttf ];
in
pkgs.mkShell {
  packages = [ pkgs.python312 pkgs.uv pkgs.ruff pkgs.python312Packages.pytest pkgs.python312Packages.pytest-qt ];
  buildInputs = [
    pkgs.python312Packages.pyside6
    pkgs.python312Packages.sqlalchemy
    pkgs.python312Packages.alembic
    pkgs.python312Packages.jinja2
    pkgs.python312Packages.weasyprint
    pkgs.python312Packages.argon2-cffi
    pkgs.python312Packages.cryptography
    pkgs.qt6.qtwayland
    pkgs.qt6.qtsvg
  ] ++ weasyprintNativeLibs ++ pdfFonts;
  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath (weasyprintNativeLibs ++ pdfFonts)}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt6.qtwayland.bin}/lib/qt-6/plugins/platforms:${pkgs.qt6.qtbase.bin}/lib/qt-6/plugins/platforms"
    export FONTCONFIG_PATH="${pkgs.fontconfig.out}/etc/fonts"
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
    echo "Firmabok Desktop dev shell (no pip needed — all deps from nixpkgs):"
    echo "  python3 -m firmabok.ui.main                 # run the app"
    echo "  QT_QPA_PLATFORM=offscreen pytest tests/     # tests (pytest-qt from nixpkgs? add below)"
    echo "  ruff check src tests                        # lint"
  '';
}
