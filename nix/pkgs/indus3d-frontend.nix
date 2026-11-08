{ buildNpmPackage }:

buildNpmPackage {
  pname = "indus3d-frontend";
  version = "2.0.0";
  src = ../../frontend;
  npmDepsHash = "sha256-liPyryAJ94mLCqhsCDerHqHZ97fx3KVZDY9VCW2/aiY=";
  npmBuildScript = "build";

  installPhase = ''
    runHook preInstall
    mkdir -p $out
    cp -r dist/* $out/
    runHook postInstall
  '';
}
