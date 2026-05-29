import os
from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_gesture"

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
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Team",
    maintainer_email="bonbon@robot.local",
    description="BonBon gesture recognition — hand, body, head gestures with safety classification.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "gesture_node = bonbon_gesture.nodes.gesture_node:main",
        ],
    },
)
