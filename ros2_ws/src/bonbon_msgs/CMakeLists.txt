cmake_minimum_required(VERSION 3.8)
project(bonbon_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AudioChunk.msg"
  "msg/BumperState.msg"
  "msg/DetectedObject.msg"
  "msg/DetectedObjectArray.msg"
  "msg/HalFault.msg"
  "msg/ModuleHealth.msg"
  "msg/PersonState.msg"
  "msg/PersonStateArray.msg"
  "msg/SafetyEvent.msg"
  "msg/SafetyState.msg"
  "msg/ServoState.msg"
  "msg/ServoStateArray.msg"
  "msg/BehaviorRecommendation.msg"
  "msg/ContextEvent.msg"
  "msg/MemoryEntry.msg"
  "msg/RiskEvent.msg"
  "msg/SemanticScene.msg"
  "msg/SpeechCommand.msg"
  "msg/SpeechTranscription.msg"
  "msg/ThermalReadings.msg"
  "msg/UserIntent.msg"
  "msg/TTSRequest.msg"
  "msg/LLMResponse.msg"
  "msg/LLMLog.msg"
  DEPENDENCIES std_msgs geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
