import os
from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_perception_ai"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("bonbon_perception_ai/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Bonbon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Perception + AI: semantic scene understanding, intent, memory.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "perception_ai_node = bonbon_perception_ai.nodes.perception_node:main",
        ],
    },
)
