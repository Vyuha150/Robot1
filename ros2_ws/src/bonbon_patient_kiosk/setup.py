from setuptools import find_packages, setup

package_name = "bonbon_patient_kiosk"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests", "tests.*", "frontend", "frontend.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", ["config/kiosk_api_params.yaml"]),
        (f"share/{package_name}/launch", ["launch/kiosk_api.launch.py"]),
    ],
    install_requires=[
        "setuptools",
        "fastapi>=0.100.0",
        "uvicorn[standard]>=0.23.0",
        "pydantic>=2.0",
        "PyJWT>=2.8.0",
        "passlib[bcrypt]>=1.7.4",
        "python-multipart>=0.0.6",
        "pycryptodome>=3.19.0",
    ],
    extras_require={
        "test": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21.0",
            "httpx>=0.24.0",
        ],
    },
    zip_safe=True,
    maintainer="BonBon Robot",
    maintainer_email="bonbon@robot.local",
    description="BonBon Patient Kiosk API — patient-facing intake/appointment/queue/wayfinding FastAPI + ROS2 bridge",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "kiosk_api_node = bonbon_patient_kiosk.nodes.kiosk_api_node:main",
            "kiosk_api_server = bonbon_patient_kiosk.main:run_server",
        ],
    },
)
