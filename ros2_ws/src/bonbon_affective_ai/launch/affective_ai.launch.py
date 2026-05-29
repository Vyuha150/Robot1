"""Launch file for bonbon_affective_ai lifecycle node."""

from launch import LaunchDescription
from launch_ros.actions import LifecycleNode
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description() -> LaunchDescription:
    """Generate the launch description for the affective AI node.

    Returns:
        LaunchDescription: The complete launch description with the lifecycle node.
    """
    pkg = get_package_share_directory('bonbon_affective_ai')
    config = os.path.join(pkg, 'config', 'affective_ai.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'face_backend',
            default_value='deepface',
            description='Face emotion backend: deepface or mock',
        ),
        DeclareLaunchArgument(
            'voice_backend',
            default_value='speechbrain',
            description='Voice emotion backend: speechbrain or mock',
        ),
        DeclareLaunchArgument(
            'text_backend',
            default_value='rules',
            description='Text emotion backend: rules, transformer, or mock',
        ),
        DeclareLaunchArgument(
            'privacy_level',
            default_value='none',
            description='Privacy level: none, face_only, or suppressed',
        ),
        LifecycleNode(
            package='bonbon_affective_ai',
            executable='affective_ai_node',
            name='affective_ai_node',
            namespace='bonbon',
            parameters=[
                config,
                {
                    'face_backend': LaunchConfiguration('face_backend'),
                    'voice_backend': LaunchConfiguration('voice_backend'),
                    'text_backend': LaunchConfiguration('text_backend'),
                    'privacy_level': LaunchConfiguration('privacy_level'),
                },
            ],
            output='screen',
        ),
    ])
