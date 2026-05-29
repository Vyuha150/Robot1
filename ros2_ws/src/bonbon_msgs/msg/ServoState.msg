# ServoState.msg — state of a single Dynamixel servo
uint8 servo_id              # Dynamixel motor ID
float32 position_rad        # present position in radians
float32 velocity_rads       # present velocity (rad/s)
float32 load_percent        # present load as % of max torque (0-100)
float32 temperature_c       # internal temperature
float32 voltage_v           # supply voltage
uint8   error_code          # Dynamixel hardware error byte (0 = no error)
bool    torque_enabled      # whether torque is on
