from glob import glob
from setuptools import find_packages, setup

package_name = "bonbon_simulation"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/scenarios", glob("scenarios/*.yaml")),
        (f"share/{package_name}/worlds", glob("worlds/*.world")),
        (f"share/{package_name}/models/bonbon_robot/urdf", glob("models/bonbon_robot/urdf/*.xacro")),
        (f"share/{package_name}/models/bonbon_robot/config", glob("models/bonbon_robot/config/*.yaml")),
        (f"share/{package_name}/models/entities", glob("models/entities/*.sdf")),
        (f"share/{package_name}/docs", glob("docs/*.md")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Simulation suite for BonBon robot validation",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "scenario_runner = bonbon_simulation.core.runner:main",
        ],
    },
)
