{
  description = "Firmabok Desktop — local-first Qt6/PySide6 bookkeeping, VAT and invoicing for Swedish sole proprietorships (enskild firma)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;

      appPackage = pkgs: pkgs.callPackage ./packaging/app.nix { };

      # dev-shell-only helpers (the package itself wires these in
      # packaging/app.nix)
      weasyprintNativeLibs = pkgs: with pkgs; [
        pango cairo gdk-pixbuf harfbuzz fontconfig glib
        libffi zlib libjpeg openjpeg freetype libxml2 libxslt shared-mime-info
      ];
      pdfFonts = pkgs: [ pkgs.dejavu_fonts pkgs.liberation_ttf ];
    in
    {
      packages = forAllSystems (system: {
        default = appPackage nixpkgs.legacyPackages.${system};
      });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/firmabok-desktop";
        };
      });

      checks = forAllSystems (system: {
        default = self.packages.${system}.default.overrideAttrs (old: {
          doCheck = true;
        });
      });

      devShells.default = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.uv
            pkgs.ruff
          ];
          buildInputs = [
            pkgs.python312Packages.pyside6
            pkgs.qt6.qtwayland
            pkgs.qt6.qtsvg
          ] ++ (weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs);

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath ((weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs))}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt6.qtwayland.bin}/lib/qt-6/plugins/platforms:${pkgs.qt6.qtbase.bin}/lib/qt-6/plugins/platforms"
            export FONTCONFIG_PATH="${pkgs.fontconfig.out}/etc/fonts"
            export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            echo "──────────────────────────────────────────────────────────────"
            echo " Firmabok Desktop devShell"
            echo "   uv sync && uv run firmabok-desktop      # start app"
            echo "   QT_QPA_PLATFORM=offscreen uv run pytest # tests"
            echo "   uv run ruff check src tests             # lint"
            echo "──────────────────────────────────────────────────────────────"
          '';
        });
    };
}
