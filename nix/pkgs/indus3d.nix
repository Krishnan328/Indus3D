{ lib
, python3
, ffmpeg
, indus3d-dsp
, makeWrapper
, stdenv
, frontend ? null
}:

let
  pythonEnv = python3.withPackages (ps: with ps; [
    flask
    flask-cors
    flask-sock
    requests
    python-dotenv
    pyserial
    flasgger
    pytest
    numpy
    opencv4
    pillow
    reportlab
  ]);
in
stdenv.mkDerivation {
  pname = "indus3d";
  version = "2.0.0";

  # Keep development artefacts and mutable state out of the Nix store.  Apart
  # from making rebuilds unnecessarily large, copying a local .env or Flask
  # session key here would expose a secret through a world-readable store path.
  src = lib.cleanSourceWith {
    src = ../../backend;
    filter = path: type:
      let
        name = lib.baseNameOf path;
      in
      lib.cleanSourceFilter path type
      && !(builtins.elem name [
        ".venv"
        "myenv"
        ".pytest_cache"
        "__pycache__"
        "target"
        "logs"
        ".flask_secret_key"
        ".env"
      ])
      && !(lib.hasSuffix ".pyc" name)
      && !(lib.hasSuffix ".pyo" name)
      && !(lib.hasSuffix ".db" name)
      && !(lib.hasPrefix "debug" name && lib.hasSuffix ".log" name);
  };

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    rm -rf myenv .venv .pytest_cache dsp/target myenv* *.pyc __pycache__

    mkdir -p $out/lib/indus3d
    cp -r * $out/lib/indus3d/

    # Ensure dsp binary target location is populated
    mkdir -p $out/lib/indus3d/dsp/target/release
    ln -sf ${indus3d-dsp}/bin/indus3d-dsp $out/lib/indus3d/dsp/target/release/indus3d-dsp

    ${lib.optionalString (frontend != null) ''
      mkdir -p $out/lib/indus3d/frontend/dist
      cp -r ${frontend}/* $out/lib/indus3d/frontend/dist/
    ''}

    mkdir -p $out/bin
    makeWrapper ${pythonEnv}/bin/python $out/bin/indus3d \
      --add-flags "$out/lib/indus3d/main.py" \
      --prefix PATH : ${lib.makeBinPath [ ffmpeg indus3d-dsp ]} \
      --set PYTHONPATH "$out/lib/indus3d" \
      --set INDUS3D_DSP_BIN "${indus3d-dsp}/bin/indus3d-dsp" \
      ${lib.optionalString (frontend != null) ''--set INDUS3D_FRONTEND_DIR "$out/lib/indus3d/frontend/dist"''}

    runHook postInstall
  '';

  meta = with lib; {
    description = "Edge-decoupled Digital Twin and Quality Controller for FDM 3D printing";
    homepage = "https://github.com/Krishnan328/Indus3D";
    license = licenses.mit;
    maintainers = [ ];
    mainProgram = "indus3d";
  };
}
