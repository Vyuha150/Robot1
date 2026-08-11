from glob import glob

from setuptools import find_packages, setup

package_name = "bonbon_patient_kiosk_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BonBon Robot",
    maintainer_email="bonbon@robot.local",
    description="Patient kiosk screen bringup -- composes bonbon_patient_kiosk's own launch file",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={"console_scripts": []},
)
