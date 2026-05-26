from setuptools import setup, find_packages
import os
from glob import glob

package_name = "bonbon_tts"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"),
         glob("launch/*.py")),
        (os.path.join("share", package_name, "config"),
         glob("config/*.yaml")),
        (os.path.join("share", package_name, "assets", "filler_audio"),
         glob("assets/filler_audio/*.wav")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Bonbon Robotics",
    maintainer_email="bonbon@example.com",
    description="Speech synthesis: Piper TTS, filler audio, priority queue, health reporting.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "tts_node = bonbon_tts.nodes.tts_node:main",
        ],
    },
)
