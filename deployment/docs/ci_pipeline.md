# CI Pipeline

The CI workflow includes:

1. checkout
2. dependency install
3. ruff lint
4. black formatting check
5. mypy type check
6. rosdep dependency check
7. colcon build
8. unit tests
9. integration tests
10. safety tests
11. simulation smoke test
12. security scan
13. documentation check
14. Docker image build
15. artifact upload
16. release tagging through the release workflow

The robot deployment path should only consume artifacts from successful CI runs.
