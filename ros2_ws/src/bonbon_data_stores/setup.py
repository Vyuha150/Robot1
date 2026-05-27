from setuptools import find_packages, setup

package_name = "bonbon_data_stores"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", ["config/data_store_params.yaml"]),
        (f"share/{package_name}/launch", ["launch/data_stores.launch.py"]),
        (f"share/{package_name}/scripts", ["scripts/backup.py", "scripts/restore.py"]),
    ],
    install_requires=[
        "setuptools",
        "pydantic>=2.0",
    ],
    extras_require={
        "vector": ["faiss-cpu", "numpy", "sentence-transformers"],
        "rag": ["chromadb"],
        "full": ["faiss-cpu", "numpy", "sentence-transformers", "chromadb"],
    },
    zip_safe=True,
    maintainer="BonBon Robot",
    maintainer_email="bonbon@robot.local",
    description="BonBon data stores: SQLite memory, FAISS vectors, ChromaDB RAG",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "data_store_node = bonbon_data_stores.nodes.data_store_node:main",
        ],
    },
)
