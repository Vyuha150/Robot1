# DetectedObjectArray.msg
# Published by bonbon_vision/vision_node on /bonbon/vision/objects at 10 Hz.

std_msgs/Header header

bonbon_msgs/DetectedObject[] objects

uint32  total_count           # number of objects in this frame
bool    is_degraded           # true = detector failed, outputs are empty / fallback
bool    privacy_mode_active   # true = faces blurred, identities suppressed
float32 inference_ms          # detector wall-clock time in milliseconds
string  detector_backend      # "yolo" | "hog" | "mock" | "degraded"
