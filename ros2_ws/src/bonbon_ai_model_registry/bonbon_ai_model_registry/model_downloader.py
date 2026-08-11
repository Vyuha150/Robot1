"""ModelDownloader — the only place in this codebase that is allowed to
actually fetch model weights/packages. Every call goes through
LicenseChecker first; a rejected license decision means the download
never runs, no matter what the caller asked for. Defaults to dry_run=True
so importing/using this module can never accidentally trigger a real
network operation -- the caller must explicitly opt into execution.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from bonbon_ai_model_registry.model_license_checker import LicenseChecker
from bonbon_ai_model_registry.model_registry import ModelEntry, ModelRegistry

_DISPATCHABLE_TYPES = {"ollama", "pip", "git", "wget"}


@dataclass
class DownloadResult:
    model_id: str
    attempted: bool
    succeeded: bool
    message: str


def print_download_plan(entry: ModelEntry) -> str:
    """Phase 4 requirement: before any download, print model name, size,
    license, purpose, storage needed, target board, command. Returns the
    printed text (also returned, not just printed, so callers building a
    dashboard/API response can reuse it verbatim)."""
    lines = [
        f"Model:      {entry.model_name} ({entry.model_id})",
        f"Capability: {entry.capability}",
        f"Purpose:    {entry.purpose}",
        f"Provider:   {entry.provider}, version {entry.version}",
        f"License:    {entry.license} (commercial_allowed={entry.commercial_allowed})",
        f"Storage:    ~{entry.expected_storage_mb} MB",
        f"RAM:        ~{entry.expected_ram_mb} MB once loaded",
        f"Target:     {entry.hardware_target} via {entry.runtime}",
        f"Command:    {entry.download_command}",
    ]
    text = "\n".join(lines)
    print(text)  # noqa: T201 -- this IS the user-facing precheck output the brief requires
    return text


class ModelDownloader:
    def __init__(self, license_checker: LicenseChecker, registry: ModelRegistry) -> None:
        self._license_checker = license_checker
        self._registry = registry

    def download(
        self,
        model_id: str,
        *,
        dry_run: bool = True,
        explicit_approval: bool = False,
        timeout_sec: float = 1800.0,
    ) -> DownloadResult:
        entry = self._registry.get(model_id)
        if entry is None:
            return DownloadResult(model_id, False, False, f"unknown model_id {model_id!r} -- not in the registry")

        print_download_plan(entry)

        decision = self._license_checker.check(entry, explicit_approval=explicit_approval)
        if not decision.allowed:
            return DownloadResult(model_id, False, False, f"blocked by license checker: {decision.reason}")

        if entry.download_type not in _DISPATCHABLE_TYPES:
            return DownloadResult(
                model_id, False, False,
                f"download_type={entry.download_type!r} is not auto-dispatchable (manual/api types require a human "
                f"or a dedicated adapter, e.g. bonbon_sarvam_adapter for 'api') -- command is printed above, not run",
            )

        if dry_run:
            return DownloadResult(model_id, True, True, "dry_run=True -- command validated and printed, not executed")

        try:
            args = shlex.split(entry.download_command)
        except ValueError as exc:
            return DownloadResult(model_id, True, False, f"could not parse download_command: {exc}")

        try:
            proc = subprocess.run(  # noqa: S603 -- command is registry-sourced, not user input; still validated by license_checker first
                args, capture_output=True, text=True, timeout=timeout_sec, check=False,
            )
        except FileNotFoundError as exc:
            return DownloadResult(model_id, True, False, f"download tool not found on this machine: {exc}")
        except subprocess.TimeoutExpired:
            return DownloadResult(model_id, True, False, f"download timed out after {timeout_sec}s")

        if proc.returncode != 0:
            return DownloadResult(model_id, True, False, f"command exited {proc.returncode}: {proc.stderr.strip()[:500]}")
        return DownloadResult(model_id, True, True, proc.stdout.strip()[:500] or "download completed")

    def download_plan(self, capability: str | None = None) -> list[dict]:
        """Read-only: what WOULD be downloaded, and why/why-not, without
        running anything. Powers GET /ai-models/download-plan."""
        entries = self._registry.by_capability(capability) if capability else self._registry.all()
        plan = []
        for entry in entries:
            decision = self._license_checker.check(entry)
            plan.append({
                "modelId": entry.model_id,
                "capability": entry.capability,
                "wouldDownload": decision.allowed,
                "reason": decision.reason,
                "storageMb": entry.expected_storage_mb,
                "downloadCommand": entry.download_command,
            })
        return plan
