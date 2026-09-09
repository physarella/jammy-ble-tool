{
  description = "Jammy G Bluetooth LE tooling (BlueZ + bleak)";

  # Pinned to a known-good release, not "unstable" -- python 3.14 + whatever
  # bleak version unstable happens to carry right now is an untested combo.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          # python + bleak (talks to BlueZ over D-Bus); bluez gives bluetoothctl;
          # networkmanager + curl are shelled out to for the auto-join/probe step
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.bleak ]))
            pkgs.bluez
            pkgs.networkmanager
            pkgs.curl
          ];
          shellHook = ''
            echo "Jammy BLE shell. Bluetooth must be on:  systemctl status bluetooth"
            echo "  python jammy_ble.py scan      # find guitar + dump its services (safe)"
            echo "  python jammy_ble.py wifi      # turn on the guitar's wifi, print login"
          '';
        };
      });
    };
}
