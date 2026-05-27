# Production Deployment Checklist

Before deployment:

- battery above threshold
- emergency stop available
- safety supervisor running
- current robot task paused
- no active navigation
- disk space sufficient
- rollback version available
- config validation passes
- service health check passes
- operator authorization confirmed

After deployment:

- all services started
- ROS2 graph healthy
- Safety Supervisor healthy
- sensor topics publishing
- dashboard reachable
- logs active
- metrics active
- no critical errors
- rollback not required
