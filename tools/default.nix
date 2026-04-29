# Boilerplate to support traditional (non-Flake) Nix
let
  flake-lock = builtins.fromJSON (builtins.readFile ./flake.lock);
  flake-compat-node = flake-lock.nodes.root.inputs.flake-compat;
  flake-compat = builtins.fetchTarball {
    url =
      flake-lock.nodes.${flake-compat-node}.locked.url
        or "https://github.com/NixOS/flake-compat/archive/${
          flake-lock.nodes.${flake-compat-node}.locked.rev
        }.tar.gz";
    sha256 = flake-lock.nodes.${flake-compat-node}.locked.narHash;
  };
  flake = (
    import flake-compat {
      src = ./.;
    }
  );
in
flake.defaultNix // flake.outputs.packages.${builtins.currentSystem}
