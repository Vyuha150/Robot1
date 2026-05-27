from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_safety"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        # ROS2 ament resource index registration
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        # Launch files
        (f"share/{package_name}/launch", glob("launch/*.py")),
        # Config files
        (f"share/{package_name}/config", glob("bonbon_safety/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Safety supervisor, e-stop, and watchdog for BonBon service robot",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "safety_supervisor_node = bonbon_safety.nodes.safety_supervisor_node:main",
            "watchdog_node          = bonbon_safety.nodes.watchdog_node:main",
            "estop_node             = bonbon_safety.nodes.estop_node:main",
            "safety_gate_node       = bonbon_safety.nodes.safety_gate_node:main",
        ],
    },
)
