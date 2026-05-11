{
  description = "virtme-ng tools";

  nixConfig = {
  };

  inputs = {
    flake-compat = {
      url = "github:NixOS/flake-compat";
      flake = false;
    };
    # Use https://status.nixos.org to pick a working nixpkgs commit, eg:
    # nix flake update nixpkgs --override-flake nixpkgs github:NixOS/nixpkgs/2c3e5ec5df46d3aeee2a1da0bfedd74e21f4bf3a --allow-dirty-locks
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
  };

  outputs =
    inputs:
    let
      inherit (inputs.nixpkgs) lib;
      foreachSystem =
        gen:
        lib.genAttrs lib.systems.flakeExposed (
          system:
          gen {
            inherit system;
            pkgs = inputs.nixpkgs.legacyPackages.${system};
          }
        );
    in
    {
      packages = foreachSystem (
        { system, pkgs, ... }:
        {
          default = pkgs.callPackage ./package.nix { };
        }
      );
    };
}
