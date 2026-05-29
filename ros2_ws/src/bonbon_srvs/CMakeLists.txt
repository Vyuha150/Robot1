cmake_minimum_required(VERSION 3.8)
project(bonbon_srvs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(bonbon_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SafetyReset.srv"
  "srv/LLMQuery.srv"
  "srv/AnalyzeText.srv"
  "srv/GetWorldModel.srv"
  "srv/GetApproachPose.srv"
  "srv/AddRestrictedZone.srv"
  "srv/RemoveRestrictedZone.srv"
  "srv/SetPrivacyMode.srv"
  "srv/EvaluateCommand.srv"
  "srv/PerformGesture.srv"
  "srv/SetMode.srv"
  "srv/HealthCheck.srv"
  DEPENDENCIES std_msgs geometry_msgs bonbon_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
