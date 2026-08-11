from setuptools import find_packages, setup

package_name = "bonbon_sarvam_adapter"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Honest Sarvam AI capability detection and client adapter, fails closed to open-source fallbacks",
    license="Proprietary",
    tests_require=["pytest"],
)
