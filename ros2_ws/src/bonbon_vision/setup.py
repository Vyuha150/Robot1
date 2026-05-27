import os
from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_vision"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        # ament index marker
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        # package manifest
        ("share/" + package_name, ["package.xml"]),
        # launch files
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        # default parameter YAML
        (os.path.join("share", package_name, "config"), glob("bonbon_vision/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Bonbon Robotics",
    maintainer_email="bonbon@example.com",
    description="Vision module: YOLO detection, face recognition, privacy guard.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "vision_node = bonbon_vision.nodes.vision_node:main",
        ],
    },
)
