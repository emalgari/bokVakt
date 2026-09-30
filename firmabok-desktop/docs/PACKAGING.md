# Packaging (Nix)

- `flake.nix` outputs:
  - `packages.default` — `buildPythonApplication` (python312) with PySide6,
    SQLAlchemy, Alembic, Jinja2, WeasyPrint (+ native libs), qtwayland, qtsvg;
    `wrapQtAppsHook` wires Qt platform themes/styles/imageformats and
    `QT_QPA_PLATFORM_PLUGIN_PATH` for X11 + Wayland; postFixup adds
    WeasyPrint's native lib path + fontconfig.
  - `apps.default` — `nix run .` starts `firmabok-desktop`.
  - `checks.default` — the package with `doCheck=true` (pytest offscreen).
  - `devShells.default` — python312, uv, ruff, PySide6, native libs.
- Installs `packaging/firmabok.desktop` → `share/applications/` and
  `packaging/firmabok.svg` → `share/icons/hicolor/scalable/apps/`.
- CI: `.github/workflows/checks.yml` runs ruff + pytest (offscreen,
  system libs via apt) and `nix flake check` + `nix build` on
  x86_64-linux and aarch64-linux runners.
- Uninstall: `nix profile remove firmabok-desktop`; user data lives in XDG
  dirs and can be deleted separately.
