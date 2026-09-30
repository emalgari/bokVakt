# Package expression for Firmabok Desktop — shared by flake.nix,
# default.nix (nix-build) and CI. No flakes required to use this file.
{ pkgs ? import <nixpkgs> { } }:

let
  weasyprintNativeLibs = with pkgs; [
    pango cairo gdk-pixbuf harfbuzz fontconfig glib
    libffi zlib libjpeg openjpeg freetype libxml2 libxslt shared-mime-info
  ];
  pdfFonts = [ pkgs.dejavu_fonts pkgs.liberation_ttf ];
in
pkgs.python312Packages.buildPythonApplication {
  pname = "firmabok-desktop";
  version = "1.0.0";
  src = builtins.path { path = ./..; name = "firmabok-desktop-src"; };
  format = "pyproject";

  nativeBuildInputs = [
    pkgs.qt6.wrapQtAppsHook # Qt plugins: platforms, styles, imageformats
    pkgs.python312Packages.setuptools
  ];
  propagatedBuildInputs = [
    pkgs.python312Packages.pyside6
    pkgs.python312Packages.sqlalchemy
    pkgs.python312Packages.alembic
    pkgs.python312Packages.jinja2
    pkgs.python312Packages.weasyprint
    pkgs.python312Packages.argon2-cffi
    pkgs.python312Packages.cryptography
    pkgs.qt6.qtwayland # Wayland + X11 platform plugins
    pkgs.qt6.qtsvg
  ];
  buildInputs = weasyprintNativeLibs ++ pdfFonts;

  # WeasyPrint (cffi dlopen) + fonts at runtime
  postFixup = ''
    wrapProgram $out/bin/firmabok-desktop \
      --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath weasyprintNativeLibs}" \
      --set FONTCONFIG_PATH "${pkgs.fontconfig.out}/etc/fonts"
  '';

  nativeCheckInputs = [
    pkgs.python312Packages.pytest
    pkgs.python312Packages.pytest-qt
  ];
  checkPhase = ''
    export HOME=$TMPDIR
    export QT_QPA_PLATFORM=offscreen
    export FIRMABOK_CONFIG_DIR=$TMPDIR/config
    export FIRMABOK_DATA_DIR=$TMPDIR/data
    export FIRMABOK_STATE_DIR=$TMPDIR/state
    pytest tests/
  '';
  doCheck = false; # enabled in flake checks.default / CI

  postInstall = ''
    mkdir -p $out/share/applications $out/share/icons/hicolor/scalable/apps
    cp packaging/firmabok.desktop $out/share/applications/
    cp packaging/firmabok.svg $out/share/icons/hicolor/scalable/apps/
  '';

  meta = with pkgs.lib; {
    description = "Local-first bookkeeping, VAT and invoicing for Swedish enskild firma (Qt6/PySide6)";
    license = licenses.mit;
    mainProgram = "firmabok-desktop";
    platforms = platforms.linux;
  };
}
