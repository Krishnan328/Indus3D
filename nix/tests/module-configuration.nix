{ ... }:
{
  # Evaluate the documented external-Moonraker deployment without hardware.
  boot.loader.grub.enable = false;
  fileSystems."/" = { device = "none"; fsType = "tmpfs"; };
  system.stateVersion = "26.05";
  services.indus3d = {
    enable = true;
    port = 5001;
    address = "0.0.0.0";
    openFirewall = true;
    klipperIntegration = false;
    moonrakerIntegration = false;
    moonrakerHost = "127.0.0.1";
    moonrakerPort = 7125;
  };
}
