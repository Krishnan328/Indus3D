{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.indus3d;
  format = pkgs.formats.ini {
    listToValue =
      l:
      if builtins.length l == 1 then
        lib.generators.mkValueStringDefault { } (lib.head l)
      else
        lib.concatMapStrings (s: "\n  ${lib.generators.mkValueStringDefault { } s}") l;
    mkKeyValue =
      key: value:
      lib.generators.mkKeyValueDefault { } " = " key (
        if builtins.isString value && lib.hasInfix "\n" value then
          "\n  ${lib.replaceString "\n" "\n  " value}"
        else
          value
      );
  };
in
{
  ##### interface
  options = {
    services.indus3d = {
      enable = lib.mkEnableOption "Indus3D Digital Twin and Quality Controller for Fused Filament Fabrication 3D printing";

      frontendPackage = lib.mkOption {
        type = lib.types.package;
        description = "Built Indus3D frontend assets.";
        defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/indus3d-frontend.nix { }";
        default = pkgs.callPackage ../pkgs/indus3d-frontend.nix { };
      };

      package = lib.mkOption {
        type = lib.types.package;
        description = "Indus3D backend package including frontend and DSP.";
        defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/indus3d.nix { indus3d-dsp = cfg.dspPackage; frontend = cfg.frontendPackage; }";
        default = pkgs.callPackage ../pkgs/indus3d.nix {
          indus3d-dsp = cfg.dspPackage;
          frontend = cfg.frontendPackage;
        };
      };

      dspPackage = lib.mkOption {
        type = lib.types.package;
        description = "Indus3D Rust DSP package.";
        defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/indus3d-dsp.nix { }";
        default = pkgs.callPackage ../pkgs/indus3d-dsp.nix { };
      };

      address = lib.mkOption {
        type = lib.types.str;
        default = "0.0.0.0";
        example = "127.0.0.1";
        description = "The IP or host address Indus3D listens on.";
      };

      port = lib.mkOption {
        type = lib.types.port;
        default = 5001;
        description = "The HTTP/WebSocket port Indus3D listens on.";
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Whether to open the firewall port for Indus3D.";
      };

      stateDir = lib.mkOption {
        type = lib.types.path;
        default = "/var/lib/indus3d";
        description = "The directory containing the Indus3D flight record database and runtime data.";
      };

      configDir = lib.mkOption {
        type = lib.types.path;
        default = "${cfg.stateDir}/config";
        description = "The directory containing the active Indus3D overrides configuration.";
      };

      configFile = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = "Path to custom static indus_overrides.cfg file.";
      };

      mutableConfig = lib.mkOption {
        type = lib.types.bool;
        default = false;
        example = true;
        description = ''
          Whether to manage the Indus3D overrides configuration outside of NixOS.

          When enabled, changes made via the Indus3D dashboard or calibration wizards
          will persist across reboots and system rebuilds.
        '';
      };

      deviceTier = lib.mkOption {
        type = lib.types.enum [ 0 1 2 3 ];
        default = 1;
        description = ''
          Vision & physics compute tier:
            - 0: Pi 3 / Zero 2W (Thermodynamic PWM Clog + OpenCV Hu Moments contour matching)
            - 1: Pi 4B (CAXTON ONNX 4-head Residual Attention classifier at layer change)
            - 2: Pi 5 (Few-shot ProtoNet with ShuffleNetV2 backbone)
            - 3: Desktop / Server (Real-time YOLOv8s defect detection)
        '';
      };

      disableUsbAutosuspend = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Disable Linux USB selective autosuspend (usbcore.autosuspend=-1) and configure udev rules
          to keep 3D printer MCUs, toolhead boards, probes, and sensors powered and awake continuously.
        '';
      };

      klipperIntegration = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Automatically configure services.klipper with required Indus3D G-code macros
          (PAUSE_INDUS3D, CANCEL_INDUS3D) and notify Klipper of Indus3D events.
        '';
      };

      moonrakerIntegration = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Automatically configure services.moonraker with CORS whitelisting and
          trusted client authorization for the Indus3D API.
        '';
      };

      moonrakerHost = lib.mkOption {
        type = lib.types.str;
        default = if config.services.moonraker.enable then config.services.moonraker.address else "127.0.0.1";
        defaultText = lib.literalExpression "config.services.moonraker.address";
        description = "The host or IP address of the Moonraker API server.";
      };

      moonrakerPort = lib.mkOption {
        type = lib.types.port;
        default = if config.services.moonraker.enable then config.services.moonraker.port else 7125;
        defaultText = lib.literalExpression "config.services.moonraker.port";
        description = "The port of the Moonraker API server.";
      };

      pzemSerialPort = lib.mkOption {
        type = lib.types.str;
        default = "";
        example = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0";
        description = "Serial device path to PZEM-004T power monitor (FTDI adapter).";
      };

      environmentFile = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "/run/secrets/indus3d.env";
        description = ''
          Optional systemd EnvironmentFile containing runtime secrets, such as
          INDUS3D_PASSWORD and FLASK_SECRET_KEY. Keep this file outside the
          Nix store with mode 0600; never put passwords in the Nix config.
        '';
      };

      user = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = ''
          User account under which Indus3D runs.

          If null is specified (default), a dynamic system user will be created by systemd.
        '';
      };

      group = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = ''
          Group account under which Indus3D runs.

          If null is specified (default), a dynamic system group will be created by systemd.
        '';
      };

      settings = lib.mkOption {
        type = lib.types.nullOr format.type;
        default = {
          indus3d = {
            lag_magnitude_warn_mm = 0.8;
            stress_score_warn = 0.5;
            ext_heat_cycles_warn = 500;
            bed_heat_cycles_warn = 500;
            thermal_runaway_delta_c = 15.0;
            thermal_runaway_window_s = 5.0;

            layer_height_mm = 0.2;
            line_width_mm = 0.4;
            linear_advance_k = 0.04;
            max_volumetric_flow_mm3s = 12.0;

            y_resonance_hz = 0.0;
            bed_mass_g = 0.0;
            y_shaper_type = "mzv";

            power_cutoff_enabled = false;
            power_cutoff_device = "";

            filament_t_glass_c = 60.0;
            filament_q_diffusion_j_mol = 220000.0;
            melt_length_mm = 15.5;
            thermal_diffusivity_mm2_s = 0.085;
            target_ra_um = 12.0;
            estimated_layer_time_s = 30.0;

            heater_rated_w = 40.0;
            t_ambient_c = 25.0;
          };
        };
        description = ''
          Declarative settings for indus_overrides.cfg.
        '';
      };

      extraSettings = lib.mkOption {
        type = lib.types.lines;
        default = "";
        description = "Extra lines to append to the generated indus_overrides.cfg configuration.";
      };
    };
  };

  ##### implementation
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.klipperIntegration -> config.services.klipper.enable;
        message = "Option services.indus3d.klipperIntegration requires Klipper to be enabled on this system (services.klipper.enable = true).";
      }
      {
        assertion = cfg.moonrakerIntegration -> config.services.moonraker.enable;
        message = "Option services.indus3d.moonrakerIntegration requires Moonraker to be enabled on this system (services.moonraker.enable = true).";
      }
      {
        assertion = cfg.user != null -> cfg.group != null;
        message = "Option services.indus3d.group is not set when services.indus3d.user is specified.";
      }
      {
        assertion = (cfg.configFile != null) != (cfg.settings != null);
        message = "You need to either specify services.indus3d.settings or services.indus3d.configFile.";
      }
      {
        assertion = (cfg.configFile != null) -> (cfg.extraSettings == "");
        message = "You can't use services.indus3d.extraSettings with services.indus3d.configFile.";
      }
    ];

    # Automatically add Indus3D G-code macros to Klipper if enabled and using declarative config
    services.klipper = lib.mkIf (cfg.klipperIntegration && !config.services.klipper.mutableConfig) {
      settings = {
        "gcode_macro PAUSE_INDUS3D" = {
          description = "Pause the print (Indus3D wrapper)";
          gcode = "PAUSE";
        };
        "gcode_macro CANCEL_INDUS3D" = {
          description = "Cancel the print (Indus3D wrapper)";
          gcode = "CANCEL_PRINT";
        };
      };
    };

    # Automatically configure Moonraker authorization CORS and trusted clients
    services.moonraker = lib.mkIf cfg.moonrakerIntegration {
      settings = {
        authorization = {
          cors_domains = [
            "http://127.0.0.1:${toString cfg.port}"
            "http://localhost:${toString cfg.port}"
            "http://*.local:${toString cfg.port}"
          ];
          trusted_clients = [
            "127.0.0.1"
          ];
        };
      };
    };

    # Open firewall port if requested
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];

    # Prevent Linux USB selective autosuspend from dropping MCU and sensor serial connections
    boot.kernelParams = lib.mkIf cfg.disableUsbAutosuspend [ "usbcore.autosuspend=-1" ];

    # Keep 3D printer MCUs, toolhead boards, probes, and sensors awake continuously
    services.udev.extraRules = lib.mkIf cfg.disableUsbAutosuspend (lib.mkAfter ''
      ACTION=="add", SUBSYSTEM=="usb", ATTR{power/control}="on"
      ACTION=="add", SUBSYSTEM=="usb", ATTR{power/autosuspend}="-1"
    '');

    systemd.services.indus3d =
      let
        indusConfig =
          if cfg.settings != null then
            builtins.toFile "indus_overrides.cfg" ((format.generate "" cfg.settings).text + cfg.extraSettings)
          else
            cfg.configFile;
      in
      {
        description = "Indus3D Digital Twin and Quality Controller";
        wantedBy = [ "multi-user.target" ];
        after = [ "network.target" ]
          ++ lib.optional config.services.moonraker.enable "moonraker.service"
          ++ lib.optional config.services.klipper.enable "klipper.service";
        wants = [ "network-online.target" ];

        environment = {
          FLASK_HOST = cfg.address;
          FLASK_PORT = toString cfg.port;
          MOONRAKER_HOST = cfg.moonrakerHost;
          MOONRAKER_PORT = toString cfg.moonrakerPort;
          INDUS3D_DEVICE_TIER = toString cfg.deviceTier;
          INDUS3D_CONFIG_PATH = "${cfg.configDir}/indus_overrides.cfg";
          DB_PATH = "${cfg.stateDir}/db/flight_record.db";
          TIMELAPSE_DIR = "${cfg.stateDir}/timelapse";
          PZEM_SERIAL_PORT = cfg.pzemSerialPort;
          HOME = cfg.stateDir;
        };

        preStart = ''
          mkdir -p ${cfg.configDir} ${cfg.stateDir}/db ${cfg.stateDir}/timelapse
          pushd ${cfg.configDir}
          if [ -e indus_overrides.cfg ]; then
            ${
              if cfg.mutableConfig then
                ":"
              else
                ''
                  old_config="indus_overrides-$(date +"%Y%m%d_%H%M%S").cfg"
                  mv indus_overrides.cfg "$old_config"
                  cat ${indusConfig} > indus_overrides.cfg
                  ${pkgs.diffutils}/bin/cmp indus_overrides.cfg "$old_config" && rm "$old_config"
                ''
            }
          else
            cat ${indusConfig} > indus_overrides.cfg
          fi
          popd
        '';

        restartTriggers = lib.optionals (!cfg.mutableConfig) [ indusConfig ];

        serviceConfig = {
          ExecStart = "${cfg.package}/bin/indus3d";
          RuntimeDirectory = "indus3d";
          StateDirectory = "indus3d";
          SupplementaryGroups = [ "dialout" ];
          WorkingDirectory = cfg.stateDir;
          Restart = "always";
          RestartSec = 5;
          UMask = "0077";

          # The service only needs network access, its runtime state and (if
          # configured) a serial device through the dialout group. These
          # restrictions keep a dashboard compromise from becoming host-wide.
          NoNewPrivileges = true;
          ProtectSystem = "strict";
          ProtectHome = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          ProtectClock = true;
          ProtectHostname = true;
          LockPersonality = true;
          RestrictSUIDSGID = true;
          RestrictRealtime = true;
          RestrictNamespaces = true;
          SystemCallArchitectures = "native";
          RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
          CapabilityBoundingSet = "";
          RemoveIPC = true;
          ReadWritePaths = [ cfg.stateDir ];
        }
        // lib.optionalAttrs (cfg.environmentFile != null) {
          EnvironmentFile = cfg.environmentFile;
        }
        // (
          if cfg.user != null then
            {
              Group = cfg.group;
              User = cfg.user;
            }
          else
            {
              DynamicUser = true;
              User = "indus3d";
            }
        );
      };

    environment.systemPackages = [
      cfg.package
      cfg.dspPackage
    ];
  };

  meta.maintainers = [
    lib.maintainers.krishnanh or "Krishnan H"
  ];
}
