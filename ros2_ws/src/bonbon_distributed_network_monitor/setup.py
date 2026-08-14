from setuptools import find_packages, setup

package_name = "bonbon_distributed_network_monitor"

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
    description="Chrony clock-offset monitoring and alerting across the three-Pi deployment",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "network_monitor_node = bonbon_distributed_network_monitor.nodes.network_monitor_node:main",
        ],
    },
)
