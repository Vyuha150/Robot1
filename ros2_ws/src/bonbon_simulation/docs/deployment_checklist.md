# Real-World Deployment Checklist

Before real hardware deployment:

- all approved simulation scenarios pass
- collision count is zero in approved scenarios
- emergency stop reaction is below 300 ms
- lidar failure detection is below 1 second
- replanning latency is below 1 second
- blocked path recovery is below 10 seconds
- docking success is above 95 percent
- standard navigation success is above 95 percent
- repeatability is above 99 percent
- touched package pytest suites pass
- no `.env` or secret material is committed
- safety gate and command tests pass if safety paths changed
- scenario reports are reviewed and archived
