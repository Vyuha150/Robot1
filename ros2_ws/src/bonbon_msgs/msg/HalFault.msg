std_msgs/Header header
string  device           # "camera" | "lidar" | "imu" | "servo" | "battery" | "mic" | "speaker" | "estop"
string  driver_mode      # "real" | "mock"
uint8   severity         # 0=INFO 1=WARN 2=ERROR 3=FATAL
uint8   INFO  = 0
uint8   WARN  = 1
uint8   ERROR = 2
uint8   FATAL = 3
string  error_code       # driver-specific code, e.g. "USB_DISCONNECTED"
string  message          # human-readable description
bool    is_recovered     # true = fault has cleared, reporting recovery
int32   reconnect_attempt
