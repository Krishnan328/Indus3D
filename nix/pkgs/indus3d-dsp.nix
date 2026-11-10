{ lib, rustPlatform }:

rustPlatform.buildRustPackage {
  pname = "indus3d-dsp";
  version = "0.1.0";

  src = ../../backend/dsp;

  cargoLock = {
    lockFile = ../../backend/dsp/Cargo.lock;
  };

  meta = with lib; {
    description = "High-performance FFT and digital signal processing bridge for Indus3D";
    homepage = "https://github.com/Krishnan328/Indus3D";
    license = licenses.mit;
    maintainers = [ ];
    mainProgram = "indus3d-dsp";
  };
}
