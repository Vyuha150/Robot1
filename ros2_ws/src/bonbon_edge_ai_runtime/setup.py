from setuptools import find_packages, setup

package_name = "bonbon_edge_ai_runtime"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools", "pyyaml"],
    zip_safe=True,
    maintainer="BonBon Robotics",
    maintainer_email="venka@bonbon-robotics.local",
    description="Cross-capability edge AI task router, safety separation guard, and orchestration layer",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "edge_ai_runtime_node = bonbon_edge_ai_runtime.nodes.edge_ai_runtime_node:main",
        ],
    },
)
