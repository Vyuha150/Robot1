"""DatasetDownloader -- the only place in this package allowed to actually
fetch dataset files. Every call passes through DatasetLicenseChecker first;
a rejected decision means the download never runs.

Rule 7 ("use Pi for inference/logging, not heavy training") applies here at
the data layer: this downloader refuses to run on a detected ARM/Pi target
unless the caller passes allow_on_edge_device=True, because a dataset
download is, by construction, training-pipeline input -- there is no
legitimate reason for a production Pi to be pulling training corpora.
Defaults to dry_run=True, matching bonbon_ai_model_registry.model_downloader's
"importing this module can never accidentally trigger a network operation"
contract.
"""

from __future__ import annotations

import platform
import shlex
import subprocess
from dataclasses import dataclass

from bonbon_data_pipeline.dataset_license_checker import DatasetLicenseChecker
from bonbon_data_pipeline.dataset_registry import DatasetEntry, DatasetRegistry

_KNOWN_EDGE_ARCHITECTURES = frozenset({"aarch64", "armv7l", "armv6l"})


def is_edge_device(machine: str | None = None) -> bool:
    """True on the ARM architectures BonBon's Raspberry Pi boards report.
    Deliberately architecture-based, not a hostname/env-var guess -- the
    one signal that can't be spoofed by a mislabeled dev machine."""
    return (machine or platform.machine()).lower() in _KNOWN_EDGE_ARCHITECTURES


@dataclass
class DatasetDownloadResult:
    dataset_id: str
    attempted: bool
    succeeded: bool
    message: str


def print_download_plan(entry: DatasetEntry) -> str:
    lines = [
        f"Dataset:     {entry.name} ({entry.dataset_id})",
        f"Capability:  {entry.capability} / {entry.domain}",
        f"Source:      {entry.source_url}",
        f"License:     {entry.license} (commercial_allowed={entry.commercial_allowed})",
        f"Privacy:     {entry.privacy_risk}",
        f"Intended:    {entry.intended_use}",
        f"Prohibited:  {entry.prohibited_use}",
        f"Status:      {entry.status}",
    ]
    text = "\n".join(lines)
    print(text)  # noqa: T201 -- user-facing precheck output, same contract as model_downloader.print_download_plan
    return text


class DatasetDownloader:
    def __init__(self, registry: DatasetRegistry, license_checker: DatasetLicenseChecker | None = None) -> None:
        self._registry = registry
        self._license_checker = license_checker or DatasetLicenseChecker()

    def download(
        self,
        dataset_id: str,
        download_command: str,
        *,
        dry_run: bool = True,
        explicit_approval: bool = False,
        privacy_cleared: bool = False,
        allow_on_edge_device: bool = False,
        timeout_sec: float = 3600.0,
    ) -> DatasetDownloadResult:
        entry = self._registry.get(dataset_id)
        if entry is None:
            return DatasetDownloadResult(dataset_id, False, False, f"unknown dataset_id {dataset_id!r} -- not in the registry")

        print_download_plan(entry)

        if is_edge_device() and not allow_on_edge_device:
            return DatasetDownloadResult(
                dataset_id, False, False,
                "refusing to download training data on a detected edge (ARM/Pi) device -- "
                "rule 7: fine-tuning happens on a workstation/GPU, the Pi runs inference/logging only",
            )

        if not entry.download_allowed:
            return DatasetDownloadResult(dataset_id, False, False, "registry marks download_allowed=false")

        decision = self._license_checker.check(
            entry, explicit_approval=explicit_approval, privacy_cleared=privacy_cleared
        )
        if not decision.allowed:
            return DatasetDownloadResult(dataset_id, False, False, f"blocked by license checker: {decision.reason}")

        if dry_run:
            return DatasetDownloadResult(dataset_id, True, True, "dry_run=True -- command validated and printed, not executed")

        try:
            args = shlex.split(download_command)
        except ValueError as exc:
            return DatasetDownloadResult(dataset_id, True, False, f"could not parse download command: {exc}")

        try:
            proc = subprocess.run(  # noqa: S603 -- command is caller-supplied only after passing the license gate above
                args, capture_output=True, text=True, timeout=timeout_sec, check=False,
            )
        except FileNotFoundError as exc:
            return DatasetDownloadResult(dataset_id, True, False, f"download tool not found on this machine: {exc}")
        except subprocess.TimeoutExpired:
            return DatasetDownloadResult(dataset_id, True, False, f"download timed out after {timeout_sec}s")

        if proc.returncode != 0:
            return DatasetDownloadResult(dataset_id, True, False, f"command exited {proc.returncode}: {proc.stderr.strip()[:500]}")
        return DatasetDownloadResult(dataset_id, True, True, proc.stdout.strip()[:500] or "download completed")

    def download_plan(self, capability: str | None = None) -> list[dict]:
        """Read-only: what WOULD be downloaded, and why/why-not."""
        entries = self._registry.by_capability(capability) if capability else self._registry.all()
        plan = []
        for entry in entries:
            decision = self._license_checker.check(entry)
            plan.append({
                "datasetId": entry.dataset_id,
                "capability": entry.capability,
                "wouldDownload": decision.allowed and entry.download_allowed,
                "reason": decision.reason if not decision.allowed else (
                    "download_allowed=false in registry" if not entry.download_allowed else decision.reason
                ),
            })
        return plan
