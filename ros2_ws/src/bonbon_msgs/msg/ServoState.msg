# ServoState.msg — state of a single servo/stepper actuator.
# Reused across driver backends (Dynamixel smart servo, PCA9685 PWM servo,
# NEMA17 closed-loop stepper) rather than one message type per hardware
# family -- fields not measurable by a given backend are reported as
# float('nan') (servo: PCA9685 has no feedback sensor) or a fixed 0.0/false
# with the reason documented in that backend's driver, never fabricated.
uint8 servo_id               # actuator ID (meaning is backend-specific: Dynamixel
                              # motor ID, PCA9685 channel-mapped servo ID, or stepper ID)
float32 position_rad         # present/commanded position in radians
float32 velocity_rads        # present velocity (rad/s); NaN if not measurable
float32 load_percent         # present load as % of max torque (0-100); NaN if not measurable
float32 temperature_c        # internal temperature; NaN if not measurable
float32 voltage_v            # supply voltage; NaN if not measurable
uint8   error_code           # backend-specific hardware error byte (0 = no error;
                              # for NEMA17 closed-loop steppers: 1 = lost_sync/stall confirmed)
bool    torque_enabled       # whether holding torque/PWM drive is on
