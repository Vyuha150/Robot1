# Docker Usage

Runtime images:

- `Dockerfile.ros2`: core ROS2 runtime
- `Dockerfile.ai`: LLM and perception AI runtime
- `Dockerfile.navigation`: Nav2 and RTAB-Map runtime
- `Dockerfile.dashboard`: FastAPI dashboard API

Volume strategy:

- `/var/lib/bonbon`: data stores and runtime state
- `/opt/bonbon/models`: model artifacts, mounted read-only
- `/etc/bonbon`: config, mounted read-only
- `/var/log/bonbon`: logs
- `/opt/bonbon/maps`: maps, mounted read-only

Containers use least-privilege defaults and `no-new-privileges` where Compose supports it.
