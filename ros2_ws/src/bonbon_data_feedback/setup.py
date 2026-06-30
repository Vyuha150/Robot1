from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_data_feedback"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", glob(f"{package_name}/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Failure-case logging, hard negatives, dataset export, privacy-safe retention",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "data_feedback_node = bonbon_data_feedback.nodes.data_feedback_node:main",
        ],
    },
)
