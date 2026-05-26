# PersonStateArray.msg — all currently tracked persons
# Published by bonbon_perception/fusion_node at 10 Hz
std_msgs/Header header
bonbon_msgs/PersonState[] persons
uint8 total_count           # number of persons in scene (including out-of-frame)
