{
  description = "Firmabok — local-first bookkeeping, VAT (moms) and invoicing for Swedish enskild firma";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;

      # Native libraries WeasyPrint needs at runtime (loaded via cffi/ctypes).
      # Without these, PDF invoice generation fails.
      weasyprintNativeLibs = pkgs: with pkgs; [
        pango
        cairo
        gdk-pixbuf
        harfbuzz
        fontconfig
        glib
        libffi
        zlib
        libjpeg
        openjpeg
        freetype
        libxml2
        libxslt
        shared-mime-info
      ];

      # Fonts used by the invoice/report PDF templates (DejaVu + Liberation
      # cover the full Swedish character set: å ä ö).
      pdfFonts = pkgs: [ pkgs.dejavu_fonts pkgs.liberation_ttf ];

    in
    {
      # ---------------------------------------------------------------- devShell
      devShells.default = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.python312Packages.pip   # fallback if uv is unavailable
            pkgs.uv
            pkgs.git
          ];
          # Native deps for pip/uv-installed weasyprint inside the shell
          buildInputs = (weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs);

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath ((weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs))}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            export FONTCONFIG_PATH="${pkgs.fontconfig.out}/etc/fonts"
            export FIRMA_DATA_DIR="''${FIRMA_DATA_DIR:-$PWD/data}"
            echo "────────────────────────────────────────────────────────"
            echo " Firmabok devShell  (Python ''$(python3 --version 2>&1 | cut -d' ' -f2), uv ''$(uv --version | cut -d' ' -f2))"
            echo ""
            echo "   uv sync                                        # install deps"
            echo "   uv run uvicorn app.main:app --reload           # run app on http://127.0.0.1:8000"
            echo "   uv run python -m app.seed                      # sample data"
            echo "   uv run pytest                                  # tests"
            echo "   uv run python -m app.backup backup             # backup DB + uploads"
            echo "────────────────────────────────────────────────────────"
          '';
        });

      # ------------------------------------------------------------------ package
      # Fully offline runtime package: Python + all dependencies come from
      # nixpkgs (no network needed at build or run time).
      packages.default = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonEnv = pkgs.python312.withPackages (ps: [
            ps.fastapi
            ps.uvicorn
            ps.sqlalchemy
            ps.alembic
            ps.jinja2
            ps.pydantic
            ps.python-multipart
            ps.weasyprint
          ]);
        in pkgs.stdenv.mkDerivation {
          pname = "firmabok";
          version = "1.0.0";
          src = self;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = (weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs);

          dontBuild = true;
          doCheck = false;

          installPhase = ''
            runHook preInstall
            mkdir -p $out/share/firmabok $out/bin
            cp -r app migrations alembic.ini pyproject.toml requirements.txt $out/share/firmabok/

            makeWrapper ${pythonEnv}/bin/python $out/bin/firmabok \
              --set PYTHONPATH $out/share/firmabok \
              --set FIRMA_DATA_DIR ''${FIRMA_DATA_DIR:-$HOME/.local/share/firmabok} \
              --set FONTCONFIG_PATH "${pkgs.fontconfig.out}/etc/fonts" \
              --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath ((weasyprintNativeLibs pkgs) ++ (pdfFonts pkgs))}" \
              --add-flags "-m app.cli"

            # convenience: firmabok-serve (starts the web app)
            makeWrapper $out/bin/firmabok $out/bin/firmabok-serve --add-flags "serve"
            runHook postInstall
          '';
        });
    };
}
