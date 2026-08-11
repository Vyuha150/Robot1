"""SarvamLicenseStatus — the license/access decision Sarvam usage must
pass before anything else in this package acts on it. Kept separate from
the capability detector so the "is Sarvam technically importable/
reachable" question (detector) and "are we ALLOWED to use it right now"
question (this module) can be reasoned about and tested independently --
a technically-reachable Sarvam API with cloud disabled must still refuse
to be used (rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SarvamLicenseStatus:
    edge_installed: bool
    api_key_present: bool
    cloud_enabled: bool
    allowed: bool
    mode: str  # "edge" | "api" | "unavailable"
    reason: str

    def to_dict(self) -> dict:
        return {
            "edgeInstalled": self.edge_installed,
            "apiKeyPresent": self.api_key_present,
            "cloudEnabled": self.cloud_enabled,
            "allowed": self.allowed,
            "mode": self.mode,
            "reason": self.reason,
        }


def evaluate(edge_installed: bool, api_key_present: bool, cloud_enabled: bool) -> SarvamLicenseStatus:
    """Decision table, evaluated in this exact priority order:

    1. Edge installed -> allowed, mode=edge. Edge access is a local
       package/model install with its own accepted EULA at install
       time -- no additional cloud-enable flag needed, since nothing
       leaves the device.
    2. API key present AND cloud explicitly enabled -> allowed, mode=api.
    3. API key present but cloud NOT enabled -> NOT allowed (rule 4: never
       use cloud API by default -- an API key existing in the environment
       is not the same as being told to use it).
    4. Neither -> NOT allowed, mode=unavailable.
    """
    if edge_installed:
        return SarvamLicenseStatus(True, api_key_present, cloud_enabled, True, "edge", "Sarvam Edge package is installed -- local, no cloud call needed")

    if api_key_present and cloud_enabled:
        return SarvamLicenseStatus(False, True, True, True, "api", "SARVAM_API_KEY is set and cloud access is explicitly enabled")

    if api_key_present and not cloud_enabled:
        return SarvamLicenseStatus(
            False, True, False, False, "unavailable",
            "SARVAM_API_KEY is present but BONBON_CLOUD_ENABLED is not true -- rule 4 forbids using a cloud API by default, even when a key exists",
        )

    return SarvamLicenseStatus(False, False, cloud_enabled, False, "unavailable", "no Sarvam Edge package installed and no SARVAM_API_KEY configured")
