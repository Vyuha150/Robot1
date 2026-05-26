# ThermalReadings.msg — system-wide thermal monitoring
# Publisher: bonbon_diagnostics/thermal_node
# Sources: CPU (sysfs), thermistors × 4 on DAQ board

std_msgs/Header header
float32 cpu_temp_c          # Jetson Orin Nano SoC temperature
float32 motor_temp_c        # max across all motor thermistor channels
float32 battery_temp_c      # battery pack thermistor
float32 board_temp_c        # DAQ board ambient temperature
float32[] channel_temps_c   # raw thermistor channel readings (4 channels)
