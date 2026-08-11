"""bonbon_patient_kiosk — patient/customer-facing kiosk API for the BonBon
service robot's hospital reception deployment.

Separate from bonbon_operator_api (staff dashboard). Every navigation and
speech request goes through the same safety-gated ROS2 services the staff
dashboard uses — this package never talks to actuators/cmd_vel directly and
never writes to bonbon_navigation's named-location registry (the Facility
Map Editor is export-only for this deployment; see api/facility_map_api.py).
"""

__version__ = "0.1.0"
