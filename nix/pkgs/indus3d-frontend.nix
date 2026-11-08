{ buildNpmPackage }:

buildNpmPackage {
  pname = "indus3d-frontend";
  version = "2.0.0";
  src = ../../frontend;
  npmDepsHash = "sha256-O/AvrdBQXkKTmAfRLtxweJYx/O1SpDVt2hZL+9viLiQ=";
  npmBuildScript = "build";

  installPhase = ''
    runHook preInstall
    mkdir -p $out
    cp -r dist/* $out/
    runHook postInstall
  '';
}
