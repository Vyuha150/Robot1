from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_object_intelligence"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", glob("bonbon_object_intelligence/config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Object permanence, calibration, OCR hook, depth association",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "object_intelligence_node = bonbon_object_intelligence.nodes.object_intelligence_node:main",
        ],
    },
)
