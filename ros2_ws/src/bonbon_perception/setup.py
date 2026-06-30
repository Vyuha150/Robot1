from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_perception"

# QUARANTINED (see README.md): this package is an orphaned duplicate of
# bonbon_vision's detection + face pipeline. Zero dependents anywhere in the
# repo, not part of bonbon_bringup. Its launch file was renamed to
# perception.launch.py.disabled (excluded from the glob below) and its
# console_scripts entry points are removed so neither `ros2 launch` nor
# `ros2 run` can start it. Source kept for reference only — do not wire this
# back in without first deleting bonbon_vision's equivalent functionality.
setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/config", glob("bonbon_perception/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="QUARANTINED — orphaned duplicate of bonbon_vision. See README.md. Not built/launched.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [],
    },
)
