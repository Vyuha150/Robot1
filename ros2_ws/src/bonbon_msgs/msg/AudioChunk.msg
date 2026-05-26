std_msgs/Header header
int32 sample_rate        # Hz — 16000 typical for ASR
int32 channels           # 1 = mono, 4 = ReSpeaker array
int32 bit_depth          # 16 typical
float32[] data           # PCM samples normalised to [-1.0, 1.0]
float32 doa_angle_deg    # direction of arrival; -1.0 = unknown
string device_id         # "respeaker" | "mock" | etc.
