import os
from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_llm"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="LLM + Response Generation Module: Ollama, LangChain, RAG, safety filtering.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "llm_orchestrator_node = bonbon_llm.nodes.llm_orchestrator_node:main",
        ],
    },
)
