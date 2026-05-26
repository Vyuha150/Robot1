# BumperState.msg — physical contact bumper strips
# Publisher: bonbon_spatial/bumper_node
# QoS: RELIABLE/depth-1

std_msgs/Header header
bool front          # front bumper strip contact
bool rear           # rear bumper strip contact
bool left           # left bumper strip (if fitted)
bool right          # right bumper strip (if fitted)
