from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_hal"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", glob("bonbon_hal/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Hardware Abstraction Layer for BonBon service robot",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "camera_node      = bonbon_hal.nodes.camera_node:main",
            "lidar_node       = bonbon_hal.nodes.lidar_node:main",
            "imu_node         = bonbon_hal.nodes.imu_node:main",
            "servo_node       = bonbon_hal.nodes.servo_node:main",
            "battery_node     = bonbon_hal.nodes.battery_node:main",
            "mic_node         = bonbon_hal.nodes.microphone_node:main",
            "speaker_node     = bonbon_hal.nodes.speaker_node:main",
            "estop_hal_node   = bonbon_hal.nodes.estop_hal_node:main",
        ],
    },
)
