# Legacy (non-flake) entry point:
#   nix-build            -> ./result/bin/firmabok-desktop
#   nix run is unavailable without flakes; use the binary directly.
{ pkgs ? import <nixpkgs> { } }:
pkgs.callPackage ./packaging/app.nix { }
