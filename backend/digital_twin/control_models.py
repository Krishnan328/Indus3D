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
import math
from typing import List

# Standard DC/Stepper drive placeholder matrices for Extruder State Space Model
# State x = [i, omega]^T where i is motor current, omega is angular velocity
# Input u = [V]^T where V is applied voltage

# Continuous-Time Matrices (dot{x} = A x + B u)
# Derived from generic motor parameters:
# R = 2.0 Ohms, L = 0.003 H, k_e = 0.05 V/(rad/s), k_t = 0.05 Nm/A, J = 5e-6 kg*m^2, b = 1e-4 Nm/(rad/s)
A_CONT = [
    [-666.67, -16.67],
    [10000.0, -20.0]
]

B_CONT = [
    [333.33],
    [0.0]
]

def calc_continuous_extruder_state_derivative(x: List[float], u: List[float], A: List[List[float]] = A_CONT, B: List[List[float]] = B_CONT) -> List[float]:
    """
    Continuous-Time Extruder State Equation: dot{x} = A x + B u.
    Returns the state derivative dot{x}.
    x: [current (A), angular_velocity (rad/s)]
    u: [voltage (V)]
    """
    if len(x) != 2 or len(u) != 1:
        raise ValueError("State vector must have 2 elements and input vector must have 1 element.")
        
    dot_x_0 = A[0][0] * x[0] + A[0][1] * x[1] + B[0][0] * u[0]
    dot_x_1 = A[1][0] * x[0] + A[1][1] * x[1] + B[1][0] * u[0]
    
    return [dot_x_0, dot_x_1]

# Discrete-Time Matrices (x(k+1) = A_e x(k) + B_e u(k))
# Approximated with Forward Euler and Ts = 0.001 s (1 ms)
# A_e ≈ I + A * Ts
# B_e ≈ B * Ts
A_DISC = [
    [0.33333, -0.01667],
    [10.0, 0.98]
]

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

