"""HailoDeviceDetector — is a Hailo AI HAT present and is the HailoRT runtime
usable?

Two independent checks, both side-effect-free and fully mockable so tests
run on a machine with no Hailo:

  * device_present()   — is the Hailo silicon on the PCIe bus? (lspci, or
                         hailortcli scan)
  * runtime_available()— is the `hailort` Python package importable?

Both must be true to actually run on the HAT. Injectable command-runner and
import-probe make this deterministic in tests.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class HailoDetection:
    device_present: bool
    runtime_available: bool
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.device_present and self.runtime_available


# Injection seams (overridden in tests):
#   _runner(cmd: list[str]) -> (returncode, stdout) | None   (None = command absent)
CommandRunner = Callable[[list[str]], "tuple[int, str] | None"]
ImportProbe = Callable[[str], bool]


def _default_runner(cmd: list[str]) -> tuple[int, str] | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return out.returncode, (out.stdout or "") + (out.stderr or "")
    except (subprocess.SubprocessError, OSError):
        return None


def _default_import_probe(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


class HailoDeviceDetector:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        import_probe: ImportProbe | None = None,
    ) -> None:
        self._run = runner or _default_runner
        self._probe = import_probe or _default_import_probe

    def device_present(self) -> bool:
        # Prefer hailortcli scan (authoritative); fall back to lspci.
        scan = self._run(["hailortcli", "scan"])
        if scan is not None and scan[0] == 0 and "hailo" in scan[1].lower():
            return True
        lspci = self._run(["lspci"])
        if lspci is not None and "hailo" in lspci[1].lower():
            return True
        return False

    def runtime_available(self) -> bool:
        return self._probe("hailort")

    def detect(self) -> HailoDetection:
        present = self.device_present()
        runtime = self.runtime_available()
        if present and runtime:
            detail = "Hailo device present and HailoRT available"
        elif present and not runtime:
            detail = "Hailo device present but HailoRT (python `hailort`) not installed"
        elif not present and runtime:
            detail = "HailoRT installed but no Hailo device detected on PCIe"
        else:
            detail = "no Hailo device and no HailoRT runtime"
        return HailoDetection(present, runtime, detail)
