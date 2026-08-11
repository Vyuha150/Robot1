from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_ai_model_registry"

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
    description="Capability-wide AI model registry, router, license guard, downloader, benchmark runner, and dashboard publisher",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "model_health_monitor_node = bonbon_ai_model_registry.model_health_monitor:main",
        ],
    },
)
