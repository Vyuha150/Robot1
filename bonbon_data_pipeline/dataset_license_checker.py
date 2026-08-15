"""DatasetLicenseChecker -- the gate every training/fine-tuning run and
every dataset_downloader.py call must pass through first. Encodes the
brief's critical rules 1, 2, and 5:

  1. Do not use random unlicensed datasets.
  2. Every dataset must have license status.
  5. Do not train safety decisions from unverified AI data.

Makes no network calls and touches no disk beyond reading the registry --
a pure decision function, deliberately easy to unit-test without any
hardware. Mirrors bonbon_ai_model_registry.model_license_checker's
fail-closed shape (unknown/unset always blocks; nothing defaults to
"allowed") applied to source datasets instead of model artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_data_pipeline.dataset_registry import DatasetEntry

# Capabilities whose training data feeds a decision with physical-safety
# consequences if wrong -- currently just navigation (obstacle/path
# judgment). Training data for these MUST be explicitly, humanly
# safety-verified (rule 5); a dataset merely being APPROVED on ordinary
# license/privacy grounds is not sufficient for this category.
_SAFETY_RELEVANT_CAPABILITIES = frozenset({"navigation"})

_UNKNOWN_LICENSE_STRINGS = frozenset({"", "unknown", "none", "n/a"})


@dataclass
class DatasetLicenseDecision:
    dataset_id: str
    allowed: bool
    reason: str


class DatasetLicenseChecker:
    def check(
        self,
        entry: DatasetEntry,
        *,
        production_training: bool = False,
        explicit_approval: bool = False,
        privacy_cleared: bool = False,
        safety_verified: bool = False,
    ) -> DatasetLicenseDecision:
        if entry.status == "BLOCKED":
            return DatasetLicenseDecision(entry.dataset_id, False, "registry status is BLOCKED")

        # Rule 1/2: an unknown or unset license always blocks, regardless
        # of what the registry's `status` field claims -- status alone is
        # not proof the license was actually checked.
        if entry.license.strip().lower() in _UNKNOWN_LICENSE_STRINGS:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                "license is unknown/unset -- rule 1 forbids using an unlicensed dataset",
            )

        if entry.status == "NEEDS_REVIEW" and not explicit_approval:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                "registry status is NEEDS_REVIEW -- human review has not confirmed this dataset yet",
            )

        # Rule 2 (commercial use gate): production training is the case
        # where an unclear commercial license actually matters -- research/
        # evaluation use of a commercial_allowed=unknown dataset is lower
        # stakes but still requires explicit_approval to avoid silent use.
        if entry.commercial_allowed == "unknown" and not explicit_approval:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                "commercial_allowed is unknown -- must be verified (or explicitly approved) before any use",
            )
        if entry.commercial_allowed == "false" and production_training and not explicit_approval:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                "license does not permit commercial use; production training is blocked without explicit approval",
            )

        # Privacy: any dataset carrying raw biometric media must be
        # cleared by privacy_guard.py before it may be used at all --
        # this checker never grants that clearance itself, only checks
        # that the caller obtained it (fail closed if the caller didn't).
        if entry.privacy_risk not in ("none", "low") and not privacy_cleared:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                f"privacy_risk={entry.privacy_risk!r} requires privacy_guard clearance, which was not provided",
            )

        # Rule 5: safety-relevant capabilities need an explicit human
        # safety-verification flag, on top of ordinary license/status
        # checks -- an AI-only or unverified label is not sufficient
        # provenance for a dataset that trains navigation/obstacle judgment.
        if entry.capability in _SAFETY_RELEVANT_CAPABILITIES and production_training and not safety_verified:
            return DatasetLicenseDecision(
                entry.dataset_id, False,
                f"capability {entry.capability!r} is safety-relevant -- rule 5 requires explicit human "
                "safety verification before this dataset may train a production model",
            )

        return DatasetLicenseDecision(
            entry.dataset_id, True,
            "license known and permits this use, status is APPROVED (or explicitly approved), "
            "privacy clearance satisfied, and safety verification satisfied where required",
        )

    def check_many(
        self, entries: list[DatasetEntry], *, production_training: bool = False
    ) -> list[DatasetLicenseDecision]:
        return [self.check(e, production_training=production_training) for e in entries]
