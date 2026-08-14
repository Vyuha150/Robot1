from setuptools import find_packages, setup

package_name = "bonbon_hardware_telemetry"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools", "pyyaml"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Real hardware metrics (base/arm/head/battery/per-Pi) and threshold triggers",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "hardware_telemetry_node = bonbon_hardware_telemetry.nodes.hardware_telemetry_node:main",
        ],
    },
)
