from setuptools import setup, find_packages
import os
from glob import glob

package_name = "bonbon_navigation"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages",
         [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        # Launch files
        (f"share/{package_name}/launch",
         glob("launch/*.py") + glob("launch/*.yaml")),
        # Config files
        (f"share/{package_name}/config",
         glob("config/*.yaml")),
        # Maps
        (f"share/{package_name}/maps",
         glob("maps/*")),
        # Simulation worlds
        (f"share/{package_name}/worlds",
         glob("worlds/*.world")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Autonomous Navigation Module for BonBon service robot",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "navigation_node = bonbon_navigation.nodes.navigation_node:main",
        ],
    },
)
