from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'bonbon_affective_ai'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='BonBon Team',
    maintainer_email='bonbon@robot.local',
    description='BonBon affective AI module',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'affective_ai_node = bonbon_affective_ai.nodes.affective_ai_node:main',
        ],
    },
)
