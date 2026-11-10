import math

def calc_pressure_advance(q_current: float, q_base: float, pa_base: float, k_pa: float = 0.005, alpha: float = 0.8) -> float:
    """
    Calculates dynamic Pressure Advance based on Volumetric Flow.
    Models the shear-thinning behavior of non-Newtonian polymers.
    """
    if q_current <= q_base:
        return pa_base
    return pa_base + k_pa * math.pow((q_current - q_base), alpha)

def calc_dynamic_temp(q_current: float, q_calibrated: float, t_base: float, c_melt: float = 0.8) -> float:
    """
    Calculates feedforward hotend temperature to maintain melt viscosity at high flows.
    """
    if q_current <= q_calibrated:
        return t_base
    return t_base + c_melt * (q_current - q_calibrated)

def calc_dynamic_cooling(layer_time: float, min_layer_time: float = 15.0, fan_base: float = 128.0) -> int:
    """
    Calculates cooling fan speed based on layer print time (inversely proportional).
    Returns 0-255 PWM value.
    """
    if layer_time <= 0 or layer_time >= min_layer_time:
        return int(fan_base)
    new_fan = fan_base * (min_layer_time / layer_time)
    return max(0, min(255, int(new_fan)))

def calc_dynamic_accel(vib_actual: float, vib_target: float, accel_base: float, accel_min: float = 500.0, gamma: float = 0.5) -> float:
    """
    Calculates safe acceleration limits using closed-loop damping of structural resonance.
    """
    if vib_actual <= vib_target or vib_actual <= 0.001:
        return accel_base
    accel_new = accel_base * math.pow((vib_target / vib_actual), gamma)
    return max(accel_min, accel_new)

def calc_z_offset(delta_t_bed: float, delta_t_chamber: float, alpha_bed: float = 0.01, alpha_frame: float = 0.005) -> float:
    """
    Calculates thermal expansion Z-offset correction.
    """
    return (alpha_bed * delta_t_bed) + (alpha_frame * delta_t_chamber)

def calc_dynamic_velocity(v_base: float, q_max: float, bead_area: float, z_height: float, k_z: float = 0.002) -> float:
    """
    Calculates dynamic max velocity bounded by volumetric flow limit and Z-height wobble.
    """
    if bead_area <= 0:
        return v_base
    v_flow_limit = q_max / bead_area
    v_stability = v_base * math.exp(-k_z * z_height)
    return max(10.0, min(v_base, v_flow_limit, v_stability))

def calc_dynamic_jerk(vib_actual: float, vib_target: float, scv_base: float = 5.0, scv_min: float = 1.0, beta: float = 0.8) -> float:
    """
    Calculates Klipper Square Corner Velocity (Jerk) based on resonance feedback.
    """
    if vib_actual <= vib_target or vib_actual <= 0.001:
        return scv_base
    scv_new = scv_base * math.pow((vib_target / vib_actual), beta)
    return max(scv_min, scv_new)

# ── Area 1: Extrusion & Pressure Advance (Curved Toolpaths) ───────────────
def calc_curved_toolpath_flow(h: float, d: float, theta: float, a: float = 1.0) -> float:
    """
    Calculates the instantaneous feed rate scalar required for a curved path 
    to prevent over-extrusion on the inner radius.
    theta: tangent trajectory angle (curvature proxy)
    a: curve transfer coefficient
    Returns a scalar multiplier for flow rate.
    """
    if d <= 0 or theta <= 0:
        return 1.0
    # Base linear area: h * w. On a curve, it shifts by cos(theta).
    # This simplifies to a scalar reduction factor based on curvature angle.
    # Math derivation: E = int_0^L [ (h*a*cos(theta)) / (pi/4 * D^2) ] dL
    # Simplified multiplier:
    multiplier = a * math.cos(theta)
    return max(0.5, min(1.0, multiplier))

# ── Area 2: Thermal Dynamics & Cooling ────────────────────────────────────
def calc_thermal_lag(current_temp: float, target_temp: float, dt: float, tau: float = 2.5) -> float:
    """
    First-Order Thermal Lag Dynamic Model.
    tau: thermal time constant of the heater block.
    Returns the expected actual temperature after dt.
    """
    return target_temp + (current_temp - target_temp) * math.exp(-dt / tau)

def calc_droplet_coalescence_rate(temp: float, t_glass: float = 60.0, k_c: float = 0.05) -> float:
    """
    Frenkel-Bellehumeur Droplet Coalescence Rate.
    Models how fast two beads sinter together. If rate is too low, bonding fails.
    """
    if temp <= t_glass:
        return 0.0
    # Simplified Arrhenius-like temperature dependence for viscosity/sintering
    return k_c * math.exp((temp - t_glass) / 10.0)

# ── Kinematic Models (Speed & Toolpath Optimization) ──────────────────────
def calc_thin_wall_feed_rate(v_nom: float, wall_thickness: float, threshold: float = 2.0, k_w: float = 1.5) -> float:
    """
    Analytical Feed Rate Equation for Thin Walls.
    Reduces feed rate when printing thin-walled structures to prevent overheating and deformation.
    wall_thickness: current width of the wall being printed (mm)
    threshold: thickness below which wall is considered "thin"
    """
    if wall_thickness >= threshold or wall_thickness <= 0:
        return v_nom
    
    # Exponential decay of max feed rate as wall gets thinner
    # Simulates the loss of heat-sinking thermal mass in thin sections
    scaling = 1.0 - math.exp(-k_w * wall_thickness)
    return v_nom * max(0.2, scaling)

def calc_distance_speed_scaling(distance: float, v_max: float, accel: float) -> float:
    """
    Distance-to-Speed Scaling Function.
    Calculates the realistic top speed achievable over a short segment distance 
    given the kinematic acceleration limits.
    Prevents the planner from requesting unattainable speeds on micro-segments.
    """
    if distance <= 0 or accel <= 0:
        return v_max
        
    # From basic kinematics: v^2 = u^2 + 2as. Assuming start/end speed ~0 for safety
    # The max velocity reached at midpoint is sqrt(accel * distance)
    v_reachable = math.sqrt(accel * distance)
    return min(v_max, v_reachable)


# ── Group A: Bead Geometry & Extrusion Volume ─────────────────────────────

def calc_filament_cross_section(d0: float) -> float:
    """
    Raw Filament Cross-Sectional Area.
    A0 = π * d0² / 4
    Gives the precise input area of the feedstock filament from its measured diameter.
    """
    return math.pi * d0 * d0 / 4.0


def calc_nozzle_exit_velocity(v0: float, d0: float, d1: float) -> float:
    """
    Nozzle Exit Velocity (Incompressible Flow Conservation).
    v1 = v0 * (d0/d1)²
    Calculates the polymer exit velocity at the nozzle tip from feed velocity and diameter ratio.
    Used as the physically-correct input to the Pressure Advance model.
    """
    if d1 <= 0:
        return v0
    return v0 * (d0 / d1) ** 2


def calc_bead_cross_section(w: float, h: float) -> float:
    """
    Deposited Bead Cross-Sectional Area — Stadium (pill) shape model.
    A2 = (w - h) * h + π * h² / 4
    Models the real FFF bead geometry: a rectangle with two semicircular endcaps.
    More accurate than the simple rectangular approximation.
    """
    if w <= h or h <= 0:
        return w * h  # Fallback: pure rectangle for degenerate cases
    return (w - h) * h + (math.pi * h * h / 4.0)


def calc_analytical_bead_width(d0: float, h: float, v0: float, v2: float) -> float:
    """
    Analytical Deposited Bead Width from mass conservation.
    w = (π*d0²/4) * (1/h * v0/v2 - 1) + h
    Predicts the deposited bead width from filament diameter, layer height, and speed ratio.
    Replaces the hardcoded wall_thickness=1.2 placeholder.
    """
    if h <= 0 or v2 <= 0:
        return d0  # Fallback
    A0 = calc_filament_cross_section(d0)
    return A0 * ((v0 / (h * v2)) - 1.0) + h


def calc_volumetric_compensation(q_measured: float, q_programmed: float,
                                  rho_eff: float = 1.0) -> float:
    """
    Volumetric Deposition Compensation Factor (WIRELY model).
    C_vol = ρ_eff * Q_measured / Q_programmed
    Computes how much the actual deposition differs from the programmed amount.
    Returns a multiplier: 1.0 = perfect, <1.0 = under, >1.0 = over.
    """
    if q_programmed <= 0:
        return 1.0
    return rho_eff * q_measured / q_programmed


# ── Group B: Toolpath Segment Kinematics ─────────────────────────────────

def calc_segment_distance(x1: float, y1: float, x0: float, y0: float) -> float:
    """
    Nominal Toolpath Segment Euclidean Distance.
    D_i = sqrt((X_i - X_{i-1})² + (Y_i - Y_{i-1})²)
    Calculates the planar distance between two G-code waypoints.
    Replaces the segment_distance = 10.0 placeholder.
    """
    return math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)


def calc_segment_time(distance: float, feed_rate_mm_s: float) -> float:
    """
    Segment Traversal Time Interval.
    t_i = D_i / F_i
    Computes the time to traverse a segment at a given feed rate.
    Replaces the layer_time_est = 30.0 placeholder in fan speed control.
    """
    if feed_rate_mm_s <= 0:
        return 0.0
    return distance / feed_rate_mm_s


def calc_filament_feed_velocity(e_delta: float, segment_time: float) -> float:
    """
    Filament Extrusion Feed Velocity.
    F_{f,i} = (E_i - E_{i-1}) / t_i
    Estimates filament feed speed from G-code E-coordinate deltas over the segment time.
    First-principles alternative to the heuristic flow estimator.
    """
    if segment_time <= 0:
        return 0.0
    return e_delta / segment_time


# ── Group C: Sinusoidal Motion Profile (Anti-Vibration/Zero-Jerk) ─────────

def calc_sinusoidal_velocity(d: float, total_distance: float, v_max: float) -> float:
    """
    Sinusoidal Velocity Profile — Zero-Jerk Motion Shaping.
    S(d) = A * sin(d / B * π)
    where A = v_max, B = total_distance.
    Shapes the velocity as a smooth half-sine over the full move distance,
    eliminating jerk discontinuities that cause ringing on short infill moves.
    Returns the instantaneous target velocity at distance d into the segment.
    """
    if total_distance <= 0:
        return v_max
    phase = (d / total_distance) * math.pi
    return v_max * math.sin(phase)

def calc_interlayer_cooling(t_surface_initial: float, t_bed: float, t_chamber: float, 
                            layer_time: float, tau_cooling: float = 20.0) -> float:
    """
    Lumped-Capacitance Thermal Cooling Model.
    Predicts the surface temperature of the *previous* layer bead when the new layer arrives.
    t_surface_initial: Temperature when the bead was deposited (usually close to melt temp).
    t_bed: Heated bed temperature (acts as lower bound heat sink).
    t_chamber: Ambient chamber temperature.
    layer_time: Time elapsed since the bead was deposited.
    tau_cooling: Thermal time constant (depends on material, part geometry, and fan speed).
    
    Returns the estimated interface temperature of the previous layer.
    """
    if layer_time <= 0:
        return t_surface_initial
        
    # Ambient effective temperature is a weighted average of chamber and bed
    t_ambient_eff = (t_bed * 0.3) + (t_chamber * 0.7)
    
    # Exponential decay towards ambient effective temperature
    t_interface = t_ambient_eff + (t_surface_initial - t_ambient_eff) * math.exp(-layer_time / tau_cooling)
    return t_interface

# Import extra models
from .control_models_extra import (
    calc_continuous_extruder_state_derivative,
    calc_discrete_extruder_next_state,
    A_CONT, B_CONT, A_DISC, B_DISC
)

# ── Group F: Physical-to-Virtual Coordinate Mapping ──────────────────────

def calc_virtual_coordinate(coord_p: float, min_p: float, max_p: float, min_v: float, max_v: float) -> float:
    """
    Physical-to-Virtual Coordinate Linear Mapping.
    coord_v = min_v + ((coord_p - min_p) * (max_v - min_v)) / (max_p - min_p)
    Maps a continuous 3D physical position within physical bounds into the normalized 
    virtual space of the 3D engine/simulator.
    """
    if max_p == min_p:
        return min_v
    return min_v + ((coord_p - min_p) * (max_v - min_v)) / (max_p - min_p)


# ── Side-Channel Emissions Models (Vibrations & Acoustics) ────────────────

def calc_structural_dynamics(q_ddot: float, q_dot: float, m_q: float, c_q: float, g_q: float, f_ext: float) -> float:
    """
    3D Printer Structural Dynamic Equation.
    M(q) q.. + C(q, q.) q. + g(q) + f = tau
    Calculates the required motor torque (tau) given the trajectory and system dynamics.
    
    q_ddot: joint acceleration
    q_dot: joint velocity
    m_q: mass matrix term (inertia)
    c_q: Coriolis and centrifugal term (damping)
    g_q: gravity/stiffness term
    f_ext: external forces (friction, etc.)
    
    Returns required torque (tau).
    """
    return (m_q * q_ddot) + (c_q * q_dot) + g_q + f_ext

def calc_stepper_torque(p: int, phi_m: float, i_a: float, i_b: float, theta: float, lambda_angle: float) -> float:
    """
    Stepper Motor Electromagnetic Torque.
    tau = -p * Phi_m * i_A * sin(p * theta) - p * Phi_m * i_B * sin(p * (theta - lambda))
    Calculates the torque generated by a two-phase stepper motor.
    
    p: number of pole pairs
    phi_m: maximum magnetic flux linkage
    i_a: current in phase A
    i_b: current in phase B
    theta: mechanical/electrical angle (rotor position)
    lambda_angle: phase shift between winding A and B
    
    Returns generated electromagnetic torque.
    """
    term_a = i_a * math.sin(p * theta)
    term_b = i_b * math.sin(p * (theta - lambda_angle))
    return -p * phi_m * (term_a + term_b)

def calc_sound_pressure(h_transfer: list[float], f_force: list[float]) -> float:
    """
    Transfer Path Sound Pressure Spectrum.
    P_i(omega) = sum(H * F)
    Calculates the acoustic sound pressure at a specific frequency point using Transfer Path Analysis.
    
    h_transfer: list of vibro-acoustic transfer functions (H) for each path
    f_force: list of excitation forces (F) for each path
    
    Returns the total sound pressure (P_i).
    """
    if len(h_transfer) != len(f_force):
        raise ValueError("Transfer functions and forces arrays must have the same length.")
    
    return sum(h * f for h, f in zip(h_transfer, f_force))
# ── Group G: Dynamic Firmware Retraction (Ooze Compensation) ─────────────

def calc_dynamic_retraction(current_temp: float, base_temp: float, q_current: float, base_retract: float = 1.0, k_t: float = 0.015, k_q: float = 0.05) -> float:
    """
    Dynamic Ooze Compensation (Retraction Length).
    L_retract = L_base + k_T * max(0, T - T_base) + k_Q * Q_avg
    
    As temperature increases, polymer viscosity drops exponentially, leading to increased oozing. 
    High average volumetric flow (Q_avg) also means higher residual nozzle pressure.
    This model dynamically increases the retraction length to pull the melt zone back further 
    when conditions favor oozing.
    """
    temp_diff = max(0.0, current_temp - base_temp)
    new_length = base_retract + (k_t * temp_diff) + (k_q * q_current)
    
    # Clamp to a safe maximum to avoid pulling molten plastic into the cold zone (which causes clogs)
    return round(min(new_length, base_retract * 2.5), 3)


# ── Group H: Predictive Clog Detection ────────────────────────────────────

def calc_extrusion_pressure(q_current: float, current_temp: float, melt_temp: float = 200.0, k_visc: float = 0.05) -> float:
    """
    Calculates the theoretical backpressure (in arbitrary units) required to push 
    the filament at the given volumetric flow rate (q_current) and temperature.
    Since viscosity drops exponentially with temperature, pushing fast at low temps
    creates massive pressure.
    """
    if q_current <= 0:
        return 0.0
    
    # Viscosity increases exponentially as temperature drops below optimal melt temp
    temp_deficit = max(0.0, melt_temp - current_temp)
    viscosity_factor = math.exp(k_visc * temp_deficit)
    
    return q_current * viscosity_factor


# ── Group I: Non-Newtonian Polymer Melt Rheology & Dynamic Backpressure ────
# Source Literature:
#   - Paper 2.1.27 (Tlegenov et al., Eq. 6-9, Eq. 16-23)
#   - Paper 2.1.72 (Comminal et al., Eq. 6-7)
#   - Paper 2.1.31 (Zhen Li et al., Eq. 2-5)

def calc_non_newtonian_melt_pressure(
    q_current_mm3_s: float,
    current_temp_c: float,
    nozzle_dia_mm: float = 0.4,
    barrel_dia_mm: float = 1.75,
    barrel_len_mm: float = 15.5,
    orifice_len_mm: float = 0.8,
    cone_angle_deg: float = 60.0,
    n_flow_index: float = 0.35,
    k0_consistency: float = 8500.0,
    t0_ref_c: float = 210.0,
    ea_over_r: float = 3800.0,
) -> float:
    """
    Calculates the true multi-zone non-Newtonian pressure drop (in Pa) across the liquefier.
    Governed by Weissenberg-Rabinowitsch wall shear rate blunting and Cross-Arrhenius shear-thinning.
    
    ΔP_total = ΔP_barrel + ΔP_contraction + ΔP_capillary
    """
    if q_current_mm3_s <= 0.0:
        return 0.0

    # Convert mm -> meters, mm³/s -> m³/s
    q_m3_s = q_current_mm3_s * 1e-9
    r1 = (barrel_dia_mm / 2.0) * 1e-3
    r2 = (nozzle_dia_mm / 2.0) * 1e-3
    l1 = barrel_len_mm * 1e-3
    l3 = orifice_len_mm * 1e-3
    alpha_rad = math.radians(cone_angle_deg)

    # Temperature-dependent consistency index K(T) via Arrhenius law
    tk = max(273.15 + 50.0, current_temp_c + 273.15)
    t0k = t0_ref_c + 273.15
    kt = k0_consistency * math.exp(ea_over_r * ((1.0 / tk) - (1.0 / t0k)))

    n = max(0.1, min(1.0, n_flow_index))
    # Pre-factor: ((3n + 1) / n)^n * (Q / pi)^n * K(T)
    geom_factor = math.pow((3.0 * n + 1.0) / n, n) * math.pow(q_m3_s / math.pi, n) * kt

    # 1. Barrel pressure drop ΔP1
    dp1 = 2.0 * l1 * geom_factor * (1.0 / math.pow(r1, 3.0 * n + 1.0))

    # 2. Conical transition pressure drop ΔP2
    tan_half_alpha = max(0.01, math.tan(alpha_rad / 2.0))
    dp2 = (2.0 * geom_factor / (3.0 * n * tan_half_alpha)) * (
        (1.0 / math.pow(r2, 3.0 * n)) - (1.0 / math.pow(r1, 3.0 * n))
    )

    # 3. Capillary orifice pressure drop ΔP3
    dp3 = 2.0 * l3 * geom_factor * (1.0 / math.pow(r2, 3.0 * n + 1.0))

    dp_total = dp1 + dp2 + dp3
    return float(max(0.0, dp_total))


def calc_extruder_motor_current(
    delta_p_pa: float,
    r_hobbed_gear_mm: float = 4.0,
    k_torque_nm_per_a: float = 0.075,
    gear_ratio: float = 3.0,
    filament_dia_mm: float = 1.75,
    f_friction_n: float = 2.5,
) -> float:
    """
    Calculates the theoretical stepper motor phase current (in Amperes) required
    to push against the melt backpressure force F_BP and mechanical friction.
    References Paper 2.1.27 (Tlegenov et al., Eq. 15-18).
    
    F_drive = F_BP + F_friction = (ΔP * A_fil) + F_friction
    τ_motor = F_drive * r_gear / gear_ratio
    I = τ_motor / K_t
    """
    if delta_p_pa <= 0.0:
        f_drive = f_friction_n
    else:
        r_fil_m = (filament_dia_mm / 2.0) * 1e-3
        a_fil_m2 = math.pi * (r_fil_m ** 2)
        f_bp = delta_p_pa * a_fil_m2
        f_drive = f_bp + f_friction_n

    r_gear_m = r_hobbed_gear_mm * 1e-3
    torque_extr = (f_drive * r_gear_m) / max(0.1, gear_ratio)
    i_pred = torque_extr / max(0.001, k_torque_nm_per_a)
    return round(float(i_pred), 3)


def detect_nozzle_clog_or_strip(
    i_measured_a: float,
    i_predicted_a: float,
    threshold_clog_ratio: float = 1.35,
    threshold_strip_ratio: float = 0.60,
) -> tuple[str, float]:
    """
    Evaluates measured vs predicted motor current to detect partial clogging or filament stripping.
    Returns:
      (status: 'NORMAL' | 'CLOG_WARNING' | 'STRIPPING_WARNING', ratio: float)
    """
    if i_predicted_a <= 0.05 or i_measured_a <= 0.0:
        return "NORMAL", 1.0

    ratio = i_measured_a / i_predicted_a
    if ratio >= threshold_clog_ratio:
        return "CLOG_WARNING", round(ratio, 2)
    elif ratio <= threshold_strip_ratio:
        return "STRIPPING_WARNING", round(ratio, 2)
    return "NORMAL", round(ratio, 2)


# ── Group J: Inter-Filament Sintering & Adhesion Healing Kinetics ──────────
# Source Literature:
#   - Paper 2.1.69 (Costa, Duarte, Covas, Eq. 4-12)
#   - Paper 2.1.70 (Bellehumeur et al., Eq. 6-8)
#   - Paper 2.1.71 (Rodriguez et al.)

def calc_sintering_healing_degree(
    t_bead_initial_c: float,
    t_substrate_c: float,
    t_ambient_c: float,
    actual_layer_time_s: float,
    fan_pwm: int = 128,
    bead_width_mm: float = 0.45,
    layer_height_mm: float = 0.2,
    rho_kg_m3: float = 1240.0,
    cp_j_kg_k: float = 1800.0,
    t_glass_c: float = 60.0,
    q_diffusion_j_mol: float = 220000.0,
    a_weld_s: float = 1.0e-25,
) -> tuple[float, float, float]:
    """
    Calculates inter-filament neck growth and molecular healing degree D_h.
    Uses Costa's analytical cooling solution and Yang-Pitchumani / Sun diffusion integral.
    
    Returns:
      (t_freeze_s, healing_degree_Dh, weld_strength_ratio)
      where weld_strength_ratio = min(1.0, D_h)
    """
    if t_bead_initial_c <= t_glass_c:
        return 0.0, 0.0, 0.0

    # Geometric properties (cross-section area and perimeter in meters)
    w_m = bead_width_mm * 1e-3
    h_m = layer_height_mm * 1e-3
    area_m2 = w_m * h_m
    perim_m = 2.0 * (w_m + h_m) - 2.0 * h_m * (1.0 - math.pi / 4.0)

    # Convective heat transfer coefficient driven by cooling fan
    fan_norm = max(0.0, min(1.0, fan_pwm / 255.0))
    h_conv = 15.0 + 75.0 * math.pow(fan_norm, 0.8)
    h_contact = 250.0   # Interfacial contact conductance (W/(m²·K))
    alpha_contact = 0.30 # Perimeter fraction touching substrate

    # Equivalent decay coefficient b and asymptotic temp Q_inf
    b = h_conv * (1.0 - alpha_contact) + h_contact * alpha_contact
    q_inf = (h_conv * (1.0 - alpha_contact) * t_ambient_c + h_contact * alpha_contact * t_substrate_c) / b

    m_decay = (perim_m * b) / (rho_kg_m3 * cp_j_kg_k * area_m2)

    # Analytical time-to-freeze above glass transition Tg
    if t_glass_c <= q_inf:
        # Temperature stays above Tg indefinitely (e.g. heated chamber)
        t_freeze = min(30.0, actual_layer_time_s)
    else:
        temp_ratio = (t_glass_c - q_inf) / max(0.1, (t_bead_initial_c - q_inf))
        if temp_ratio <= 0.0 or temp_ratio >= 1.0:
            t_freeze = 0.0
        else:
            t_freeze = -math.log(temp_ratio) / m_decay
            t_freeze = max(0.0, min(t_freeze, actual_layer_time_s))

    if t_freeze <= 0.001:
        return 0.0, 0.0, 0.0

    # 5-point Gauss-Legendre Quadrature for welding integral
    # Gauss points x_i and weights w_i on [-1, 1]
    gauss_pts = [
        (-0.9061798459, 0.2369268850),
        (-0.5384693101, 0.4786286705),
        ( 0.0000000000, 0.5688888889),
        ( 0.5384693101, 0.4786286705),
        ( 0.9061798459, 0.2369268850),
    ]

    r_gas = 8.314  # J/(mol·K)
    integral_sum = 0.0
    for xi, wi in gauss_pts:
        tau = (t_freeze / 2.0) * (xi + 1.0)
        # Transient temperature at tau
        t_tau = (t_bead_initial_c - q_inf) * math.exp(-m_decay * tau) + q_inf
        t_tau_k = max(273.15, t_tau + 273.15)
        # Relaxation welding time t_w(T)
        # The cap only guards against float overflow (exp(700) ~ 1e304). It must
        # stay far above any physical exponent: a low cap (the old 60) made the
        # welding time stop growing below ~168 degC and overstated healing.
        tw = a_weld_s * math.exp(min(600.0, q_diffusion_j_mol / (r_gas * t_tau_k)))
        if tw > 1e-12:
            integral_sum += wi * (1.0 / tw)

    integral_val = (t_freeze / 2.0) * integral_sum
    d_h = math.pow(max(0.0, integral_val), 0.25)
    strength_ratio = min(1.0, d_h)

    return round(t_freeze, 3), round(d_h, 3), round(strength_ratio, 3)


# ── Group K: Graetz Number Undercooling & Melt Deficit Observer ────────────
# Source Literature:
#   - Paper 2.1.26 (Perez et al., 2022)

def calc_graetz_undercooling(
    q_current_mm3_s: float,
    filament_dia_mm: float = 1.75,
    melt_length_mm: float = 15.5,
    thermal_diffusivity_mm2_s: float = 0.085,
    k_gz: float = 7.25,
    max_undercooling_c: float = 16.0,
) -> tuple[float, float]:
    """
    Calculates the Graetz number (Gz) and the nozzle exit core undercooling deficit ΔT (°C).
    At Gz > 1.0, thermal advection dominates conduction, causing the polymer core
    exiting the nozzle to lag behind the heater block setpoint.
    
    Returns:
      (gz_number, delta_t_undercooling_c)
    """
    if q_current_mm3_s <= 0.0:
        return 0.0, 0.0

    r_fil = filament_dia_mm / 2.0
    a_fil = math.pi * (r_fil ** 2)
    v_fil = q_current_mm3_s / a_fil  # linear mm/s

    # Gz = (v_fil * d_fil²) / (4 * α * L)
    denom = 4.0 * thermal_diffusivity_mm2_s * melt_length_mm
    gz = (v_fil * (filament_dia_mm ** 2)) / max(0.001, denom)

    if gz <= 1.0:
        delta_t = 0.0
    else:
        delta_t = min(max_undercooling_c, k_gz * math.log(gz))

    return round(gz, 2), round(delta_t, 2)


# ── Group L: Repulsive Force Part Warpage & Compliance Observer ───────────
# Source Literature:
#   - Paper 2.1.28 (Armillotta et al., 2022)

def calc_repulsive_force_warpage(
    f_z_measured_n: float,
    nominal_layer_height_mm: float = 0.2,
    machine_stiffness_n_mm: float = 50.0,
    part_stiffness_n_mm: float = 15.0,
    warpage_warning_threshold_mm: float = 0.35,
) -> tuple[float, bool]:
    """
    Reconstructs upward part warpage height Δh_warpage (in mm) from repulsive reaction force F_z.
    Equivalent compliance: 1/k_eq = 1/k_m + 1/k_p
    
    Returns:
      (warpage_height_mm, is_warning_triggered)
    """
    if f_z_measured_n <= 0.05:
        return 0.0, False

    k_eq = (machine_stiffness_n_mm * part_stiffness_n_mm) / (machine_stiffness_n_mm + part_stiffness_n_mm)
    delta_h_plunge = f_z_measured_n / max(0.1, k_eq)
    warpage_height = nominal_layer_height_mm + delta_h_plunge

    warning = warpage_height >= warpage_warning_threshold_mm
    return round(warpage_height, 3), warning


# ── Group M: Mass-Adaptive Online Input Shaping (TVIST) ───────────────────
# Source Literature:
#   - Paper 2.1.64 (Ebbesen, Thomsen, Søe-Knudsen, 2019)

def calc_mass_adaptive_shaper_frequency(
    f_baseline_hz: float,
    bed_mass_g: float,
    part_mass_g: float,
    zeta_baseline: float = 0.08,
    damping_growth_factor: float = 0.02,
) -> tuple[float, float, float]:
    """
    Calculates continuous natural resonance frequency shift f_d(z) as printed part mass accumulates.
    
    Returns:
      (f_d_new_hz, zeta_new, delta_2_delay_s)
    """
    if f_baseline_hz <= 0.0 or bed_mass_g <= 0.0:
        return f_baseline_hz, zeta_baseline, 0.0

    m_total = bed_mass_g + max(0.0, part_mass_g)

    # Viscoelastic structural damping ratio shift
    zeta = min(0.30, zeta_baseline * (1.0 + damping_growth_factor * (part_mass_g / bed_mass_g)))

    # Natural frequency scales inversely with sqrt(m_total)
    f_undamped = f_baseline_hz / math.sqrt(max(0.01, 1.0 - (zeta_baseline ** 2)))
    f_n_new = f_undamped * math.sqrt(bed_mass_g / m_total)
    f_d_new = f_n_new * math.sqrt(max(0.01, 1.0 - (zeta ** 2)))

    # ZV shaper impulse delay Δ2 = 0.5 / f_d
    delta_2 = 0.5 / f_d_new if f_d_new > 0.0 else 0.0

    return round(f_d_new, 2), round(zeta, 4), round(delta_2, 5)


# ── Group N: Surface Roughness Minimization & Closed-Loop Perimeter Tuning ─
# Source Literature:
#   - Paper 2.1.15 (Zhang et al., 2025)

def calc_surface_roughness_ra(
    layer_height_mm: float,
    wall_speed_mm_s: float,
    nozzle_temp_c: float,
    surface_angle_deg: float = 0.0,
) -> float:
    """
    Calculates estimated arithmetic surface roughness Ra (in micrometers, µm)
    combining kinematic scallop geometry with the empirical response surface.
    """
    rad = math.radians(min(80.0, abs(surface_angle_deg)))
    # Flat-wall baseline (~10.7 µm for a 0.2 mm layer), scaled by the scallop
    # stretch 1/cos(angle). Continuous in the angle: the old code switched to
    # h/(4cos) for any non-zero angle, a ~5x discontinuity at ~0.06 degrees.
    ra_kinematic = (0.0537 * layer_height_mm) * 1000.0 / math.cos(rad)  # to µm

    speed_factor = 1.0 + 0.008 * max(0.0, wall_speed_mm_s - 40.0)
    temp_factor = 1.0 - 0.005 * (nozzle_temp_c - 200.0)

    ra_total = ra_kinematic * speed_factor * max(0.6, temp_factor)
    return round(max(0.5, ra_total), 2)


def calc_optimal_perimeter_parameters(
    layer_height_mm: float,
    target_ra_um: float = 12.0,
    t_nominal_c: float = 210.0,
    v_nominal_mm_s: float = 60.0,
    v_min_mm_s: float = 25.0,
    v_max_mm_s: float = 100.0,
    t_min_c: float = 195.0,
    t_max_c: float = 230.0,
) -> tuple[float, float, float]:
    """
    Closed-loop optimization finding perimeter speed v* and temperature T*
    that achieve the target Ra with minimum print time penalty.
    
    Returns:
      (optimal_speed_mm_s, optimal_temp_c, predicted_ra_um)
    """
    current_ra = calc_surface_roughness_ra(layer_height_mm, v_nominal_mm_s, t_nominal_c)
    if current_ra <= target_ra_um:
        return v_nominal_mm_s, t_nominal_c, current_ra

    ra_ratio = current_ra / target_ra_um
    v_opt = max(v_min_mm_s, min(v_max_mm_s, v_nominal_mm_s / math.sqrt(ra_ratio)))
    t_opt = max(t_min_c, min(t_max_c, t_nominal_c + 2.5 * math.log(ra_ratio)))

    final_ra = calc_surface_roughness_ra(layer_height_mm, v_opt, t_opt)
    return round(v_opt, 1), round(t_opt, 1), round(final_ra, 2)


# ── Group O: Thermodynamic PWM Mass-Flow Clog Observer ───────────────────────
# Source Literature:
#   - WatchingWatches/clog_detection_ml (Moonraker heater-duty-cycle approach)
#   - Energy balance: Q_in = Q_heater - Q_loss = m_dot * (c_p * ΔT + Δh_fusion)
#   Reference: Clog Detection via Heater PWM (2024)

def calc_thermodynamic_mass_flow(
    extruder_power_frac: float,
    heater_rated_w: float,
    t_nozzle_c: float,
    t_ambient_c: float,
    volumetric_flow_cmd_mm3_s: float,
    filament_density_kg_m3: float = 1240.0,
    filament_cp_j_kg_k: float = 1800.0,
    filament_latent_j_kg: float = 100_000.0,
    clog_ratio_threshold: float = 0.45,
    min_flow_cmd_mm3_s: float = 3.0,
) -> tuple:
    """
    Estimates actual mass flow rate from heater PWM duty cycle and nozzle
    temperature using an energy balance observer.

    Physics (clog_detection_ml energy balance):
        Q_heater  = extruder_power_frac × heater_rated_w   [W]
        Q_loss    ≈ h_loss × (T_nozzle − T_ambient)         [W]  (empirical: h_loss ≈ 0.5 W/°C)
        Q_melt    = Q_heater − Q_loss                        [W]
        m_dot     = Q_melt / (c_p × ΔT + Δh_fusion)         [kg/s]

    Clog suspected when:
        - Commanded volumetric flow  >  min_flow_cmd_mm3_s  (actually trying to extrude)
        - Thermal mass-flow estimate << commanded mass-flow   (heater can't keep up)
        - ratio = m_dot_thermal / m_dot_commanded  <  clog_ratio_threshold

    Args:
        extruder_power_frac:       Moonraker extruder.power, range 0.0–1.0
        heater_rated_w:            Nozzle heater block rated wattage (e.g. 40 W)
        t_nozzle_c:                Current nozzle temperature [°C]
        t_ambient_c:               Ambient temperature [°C]
        volumetric_flow_cmd_mm3_s: Commanded volumetric flow [mm³/s]
        filament_density_kg_m3:    Filament density (PLA ≈ 1240 kg/m³)
        filament_cp_j_kg_k:        Specific heat capacity [J/(kg·K)]
        filament_latent_j_kg:      Latent heat of fusion [J/kg]
        clog_ratio_threshold:      Thermal/commanded ratio below which clog is flagged
        min_flow_cmd_mm3_s:        Minimum commanded flow to enable clog check [mm³/s]

    Returns:
        (m_dot_thermal_kg_s: float, clog_suspected: bool, thermal_ratio: float)
        - m_dot_thermal_kg_s: Thermally estimated mass flow rate [kg/s]
        - clog_suspected:     True if thermal evidence suggests a clog
        - thermal_ratio:      m_dot_thermal / m_dot_commanded  (1.0 = healthy)
    """
    if heater_rated_w <= 0.0 or t_nozzle_c <= t_ambient_c:
        return 0.0, False, 1.0

    # Empirical convective loss coefficient (≈ 0.05 W/°C for standard insulated E3D-style block)
    H_LOSS_W_PER_C = 0.05
    delta_t = t_nozzle_c - t_ambient_c

    q_heater = max(0.0, extruder_power_frac) * heater_rated_w
    q_loss   = H_LOSS_W_PER_C * delta_t
    q_melt   = max(0.0, q_heater - q_loss)

    # Enthalpy per kg to melt filament from ambient to nozzle temp
    enthalpy_j_kg = filament_cp_j_kg_k * delta_t + filament_latent_j_kg
    m_dot_thermal = q_melt / enthalpy_j_kg if enthalpy_j_kg > 0.0 else 0.0

    # Commanded mass flow (mm³/s → m³/s → kg/s)
    m_dot_cmd = (volumetric_flow_cmd_mm3_s * 1e-9) * filament_density_kg_m3

    clog_suspected = False
    thermal_ratio  = 1.0

    if m_dot_cmd > (min_flow_cmd_mm3_s * 1e-9 * filament_density_kg_m3) and m_dot_cmd > 0.0:
        thermal_ratio = min(2.0, m_dot_thermal / m_dot_cmd)
        clog_suspected = thermal_ratio < clog_ratio_threshold

    return round(m_dot_thermal, 9), clog_suspected, round(thermal_ratio, 3)



