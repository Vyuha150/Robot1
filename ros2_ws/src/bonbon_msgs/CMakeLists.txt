cmake_minimum_required(VERSION 3.8)
project(bonbon_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

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
  "msg/FaceEmotion.msg"
  "msg/VoiceEmotion.msg"
  "msg/TextEmotion.msg"
  "msg/HumanEmotionState.msg"
  "msg/GestureEvent.msg"
  "msg/SpatialEntity.msg"
  "msg/SpatialRelation.msg"
  "msg/SocialNavigationHint.msg"
  "msg/BehaviorProposal.msg"
  "msg/BehaviorDecision.msg"
  "msg/ActuationGesture.msg"
  "msg/ActuationStatus.msg"
  "msg/HumanStateEstimate.msg"
  DEPENDENCIES std_msgs geometry_msgs builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
