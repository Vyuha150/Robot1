from setuptools import find_packages, setup

package_name = "bonbon_ai_runtime"

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
    description="Pluggable vision-model inference runtime (CPU/ONNX, TensorRT, Hailo, mock)",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # Benchmark/diagnose the selected runtime on the target device.
            "ai_runtime_bench = bonbon_ai_runtime.cli:main",
        ],
    },
)
