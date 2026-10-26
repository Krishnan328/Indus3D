# Indus3D roadmap

This is a direction-of-travel document, not a release promise. Work is prioritised by printer safety, evidence from real hardware, and usefulness to Klipper users.

## Now

- Stabilise the dashboard, simulator, and Flask/Moonraker boundary
- Document validated versus experimental quality-control behaviour
- Improve printer-profile handling, empty states, and real-printer diagnostics
- Add focused frontend and backend regression coverage

## Next

- Guided calibration workflow for bed levelling, PID, flow, and input shaping
- Better post-print reports from the SQLite audit trail (Done via Spoolman Cost & Gamification Dashboard)
- More test shapes and simulator fault scenarios
- Community-contributed printer profiles and compatibility reports
- Better camera-stream configuration and diagnostics (Done via Incident Replay)


## Recently Added Epic Capabilities
- **Fleet Command:** Multi-printer hub view with mobile-first quick look.
- **Incident Playback:** Automatic 10s video/G-code replay upon print failure.
- **Maintenance Lifecycle:** Real Odometry tracking with resetting capabilities.
- **Extensibility:** Backend plugins architecture to safely load community routes.
- **Bed Safety System:** OrcaSlicer-profile-aware collision detection with G-code clamping.

## Research-Driven Mathematical Models (v2.0)

Six physics-based control modules derived from 100+ research papers are now integrated into the live quality control loop. All are $O(1)$ scalar arithmetic — safe for Raspberry Pi.

### ✅ Group I–H: Non-Newtonian Backpressure & Nozzle Health
*Papers 2.1.27 (Tlegenov et al.)*

Replaces the legacy linear pressure model with the full Cross-Arrhenius shear-thinning pipeline:

$$\Delta P_\text{total} = \Delta P_\text{barrel} + \Delta P_\text{contraction} + \Delta P_\text{capillary}$$

$$\dot\gamma_\text{wall} = \frac{(3n+1)}{n} \cdot \frac{Q}{\pi r^3}, \quad K(T) = K_0 \exp\!\left[E_a/R \left(\frac{1}{T} - \frac{1}{T_0}\right)\right]$$

Predicted motor current from backpressure torque is compared to TMC StallGuard telemetry. A `CLOG_WARNING` is raised when `I_meas / I_pred > 1.35`; `STRIPPING_WARNING` when `< 0.60`.

**New metrics:** `nozzle_status`, `pressure` (kPa)

### ✅ Group J: Inter-Filament Sintering & Adhesion Healing
*Papers 2.1.69–71 (Costa, Bellehumeur, Rodriguez)*

Analytically models bead cooling and molecular diffusion using Costa's lumped-capacitance solution and a 5-point Gauss-Legendre integral over the welding time distribution:

$$T(t) = (T_\text{bead} - T_\infty)\,e^{-\beta t} + T_\infty$$

$$D_h = \left[\int_0^{t_f} \frac{1}{t_w(T(\tau))}\,d\tau\right]^{1/4}, \quad t_w = A\,e^{Q_d / R T(\tau)}$$

When $D_h < 0.95$, the fan is reduced by up to 30% to extend the above-$T_g$ healing window.

**New metric:** `adhesion_score` (D_h, 0–1)

### ✅ Group K: Graetz Number Undercooling
*Paper 2.1.26 (Perez et al., 2022)*

Quantifies the thermal deficit at the nozzle exit when advection outpaces conduction at high flow rates:

$$\text{Gz} = \frac{v_\text{fil} \cdot d^2}{4\alpha L}, \quad \Delta T = k_\text{Gz} \ln(\text{Gz}) \text{ for Gz} > 1$$

The undercooling $\Delta T$ is added as a feedforward boost to the nozzle setpoint (capped at +10°C).

**New metric:** `undercooling_c` (°C)

### ✅ Group L: Repulsive Force Warpage Observer
*Paper 2.1.28 (Armillotta et al., 2022)*

Reconstructs warpage height from Z-axis ADXL stress via compliance observer:

$$\frac{1}{k_\text{eq}} = \frac{1}{k_m} + \frac{1}{k_p}, \quad \Delta h_\text{warp} = \frac{F_z}{k_\text{eq}} + h_\text{layer}$$

A Z-hop babystep is issued when $\Delta h_\text{warp} > 0.35\,\text{mm}$.

**New metric:** `warpage_mm` (mm)

### ✅ Group M: Mass-Adaptive Input Shaping (TVIST)
*Paper 2.1.64 (Ebbesen et al., 2019)*

Upgraded from the legacy $f \propto 1/\sqrt{m}$ formula to the full TVIST model tracking both frequency shift and viscoelastic damping growth:

$$\zeta(t) = \zeta_0\!\left(1 + k_\zeta \frac{m_\text{part}}{m_\text{bed}}\right), \quad f_d(t) = f_n(t)\sqrt{1-\zeta(t)^2}$$

**New metric:** `zeta` (structural damping ratio)

### ✅ Group N: Surface Roughness Minimization
*Paper 2.1.15 (Zhang et al., 2025)*

Predicts $R_a$ from layer height and perimeter speed using a combined kinematic scallop + empirical response surface:

$$R_a = \frac{h}{4\cos\theta} \cdot (1 + 0.008(v - 40)) \cdot (1 - 0.005(T - 200))$$

When $R_a > R_a^\text{target}$ (default 12 µm), the optimal speed is found and applied via M220.

**New metric:** `ra_predicted_um` (µm)

---

## Research and hardware validation

- Validate vibration-informed fault detection with ADXL-equipped toolheads
- Integrate camera/YOLO inspection only after hardware and dataset validation
- Measure whether variable input shaping and flow adjustments improve print quality on repeatable test prints
- Validate sintering D_h thresholds against peel-strength coupon tests
- Validate Graetz undercooling boost against actual melt temperature measurements

## Good first issues

Good first contributions should be scoped so that they can be tested in simulation. Useful examples include:

- Responsive and accessible dashboard improvements
- Clearer error/empty/loading states
- Unit tests for model calculations and API responses
- Additional simulator geometry and fixture data
- Documentation for supported Klipper/Moonraker setups
- Importable printer-profile examples with secrets removed

When proposing work, describe how it can be tested without risking a real printer.
