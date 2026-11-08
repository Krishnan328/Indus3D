{
  description = "Indus3D: Digital Twin & Quality Controller for FDM 3D Printing";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
    in
    flake-utils.lib.eachSystem supportedSystems (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      rec {
        packages = rec {
          indus3d-dsp = pkgs.callPackage ./nix/pkgs/indus3d-dsp.nix { };
          indus3d-frontend = pkgs.callPackage ./nix/pkgs/indus3d-frontend.nix { };
          indus3d = pkgs.callPackage ./nix/pkgs/indus3d.nix {
            inherit indus3d-dsp;
            frontend = indus3d-frontend;
          };
          default = indus3d;
        };

        apps = rec {
          indus3d = flake-utils.lib.mkApp { drv = packages.indus3d; };
          check = flake-utils.lib.mkApp {
            drv = pkgs.writeShellScriptBin "indus3d-stability-check" ''
              ${pkgs.python3}/bin/python ${./scripts/check_system_stability.py} "$@"
            '';
          };
          default = indus3d;
        };

        checks = {
          package = packages.indus3d;
          frontend = packages.indus3d-frontend;
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          nixos-module =
            let
              host = nixpkgs.lib.nixosSystem {
                inherit system;
                modules = [ self.nixosModules.indus3d ./nix/tests/module-configuration.nix ];
              };
              failures = builtins.filter (item: !item.assertion) host.config.assertions;
            in
            assert pkgs.lib.assertMsg (failures == [])
              (pkgs.lib.concatMapStringsSep "\n" (item: item.message) failures);
            pkgs.runCommand "indus3d-nixos-module-check" {
              service = host.config.systemd.services.indus3d.serviceConfig.ExecStart;
            } ''
              test -n "$service"
              touch $out
            '';
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3
            python3Packages.flask
            python3Packages.flask-cors
            python3Packages.flask-sock
            python3Packages.requests
            python3Packages.python-dotenv
            python3Packages.pyserial
            python3Packages.flasgger
            python3Packages.pytest
            python3Packages.numpy
            python3Packages.opencv4
            cargo
            rustc
            rustfmt
            ffmpeg
          ];
        };
      }
    ) // {
      nixosModules = {
        indus3d = import ./nix/modules/indus3d.nix;
        default = self.nixosModules.indus3d;
      };
    };
}
