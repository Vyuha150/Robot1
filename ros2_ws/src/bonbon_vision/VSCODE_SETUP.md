# VS Code Setup for bonbon_vision Tests

## Quick Setup (5 minutes)

### Step 1: Install Python Extension
1. Open VS Code
2. Press `Ctrl+Shift+X` to open Extensions
3. Search for "Python" (by Microsoft)
4. Click **Install**

### Step 2: Open the Project Folder
1. Press `Ctrl+K Ctrl+O` (or File → Open Folder)
2. Navigate to: `C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_vision`
3. Click **Select Folder**

### Step 3: Select Python Interpreter
1. Press `Ctrl+Shift+P` to open Command Palette
2. Type "Python: Select Interpreter"
3. Choose: `C:\Users\venka\AppData\Roaming\uv\python\cpython-3.14.3-windows-x86_64-none\python.exe`
4. **Verify** at the bottom-right of VS Code — it should show the Python version

### Step 4: Install Test Dependencies
Open a terminal in VS Code (`Ctrl+``):

```powershell
C:\Users\venka\AppData\Roaming\uv\python\cpython-3.14.3-windows-x86_64-none\python.exe -m pip install pytest pytest-mock numpy --break-system-packages
```

### Step 5: Configure Pytest in VS Code
1. Press `Ctrl+Shift+P` and search: "Python: Configure Tests"
2. Select **pytest**
3. Select **`.`** as the root directory
4. VS Code will auto-detect the `tests/` folder

### Step 6: Run Tests
1. Click the **flask/beaker icon** in the left sidebar (Testing)
2. Click **▶ Run All Tests**
3. Watch the output panel show test results in real-time

---

## What Each Test Covers

| Test File | Purpose |
|-----------|---------|
| `test_detector.py` | Base detector, mock detector, degraded mode, timeouts |
| `test_frame_processor.py` | Frame quality, brightness detection, resizing, depth handling |
| `test_frame_throttler.py` | Frame rate limiting and timing |
| `test_model_manager.py` | Model lifecycle, loading, unloading |
| `test_privacy_guard.py` | Face detection and blurring |
| `test_vision_node.py` | ROS2 node integration, messaging |

---

## Expected Output

When all tests pass, you'll see:
```
✅ test_detector.py::TestMockDetector::test_normal_detection PASSED
✅ test_frame_processor.py::TestFrameProcessor::test_ok_frame_path PASSED
...
======================== 50+ passed in 2.3s ==========================
```

## Troubleshooting

### "Module not found: bonbon_vision"
- Verify pytest.ini exists in the root with `pythonpath = .`
- Check the folder is opened correctly

### "No module named pytest"
- Run: `python -m pip install pytest pytest-mock --break-system-packages`

### "Tests not discovered"
- Press `Ctrl+Shift+P` → "Python: Discover Tests"
- Reload the window: `Ctrl+R`

---

## Next: Demo Webcam (After Tests Pass)

Once all tests pass, you can try the live demo:

```powershell
$env:PYTHONPATH = "C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_vision"
cd "C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_vision"
C:\Users\venka\AppData\Roaming\uv\python\cpython-3.14.3-windows-x86_64-none\python.exe demo_webcam.py
```

**Demo Controls:**
- `D` — Degrade detector (boxes disappear)
- `R` — Recover detector (boxes return)
- `S` — Save screenshot
- `Q` — Quit
