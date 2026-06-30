# Dataset License Checklist

Run through this checklist **before** any public or third-party dataset is
used for pretraining, validation, or fine-tuning a BonBon model. No
exceptions for "just a quick experiment" — a model trained even briefly on
unlicensed data can taint everything derived from it.

## The checklist

1. **License identified.** The dataset's license is explicitly stated (not inferred from "it's on a public research page"). Unknown license = treat as all-rights-reserved and do not use.
2. **Commercial use permitted.** Many research datasets (CC-BY-NC, academic-only EULAs) prohibit commercial use. BonBon is a commercial product — research-only licenses are disqualifying.
3. **Derivative model rights permitted.** A license can permit "use" of the raw data but restrict training models on it, or restrict redistributing a model trained on it. Check both clauses separately.
4. **Attribution requirements documented.** If attribution is required, it is recorded in `docs/THIRD_PARTY_DATASET_ATTRIBUTIONS.md` (create on first use) before the dataset is used, not after.
5. **No PII/biometric redistribution restriction violated.** Datasets containing real human faces/voices often have consent terms scoped to the original collector's use case — confirm BonBon's use (a commercial home/service robot) falls within the original consent scope, not just the technical license text.
6. **No copyrighted media without a clear data-mining/training exception.** Some jurisdictions provide a text-and-data-mining exception for research; this does not automatically extend to commercial model training. When in doubt, exclude.
7. **Dataset version/snapshot recorded.** Public datasets get silently updated or taken down. Record the exact version, download date, and a checksum so the provenance is reproducible.
8. **Approved by whoever owns legal/compliance sign-off for the project** before the first training run. This checklist is a pre-check, not a substitute for that sign-off.

## Outcome states

| State | Meaning | What happens next |
|---|---|---|
| **CLEARED** | All 8 items pass | Dataset ID + version recorded in `bonbon_field_learning.dataset_version_manager`-tracked history; usable for training. |
| **CLEARED WITH ATTRIBUTION** | All pass, item 4 requires action | Same as CLEARED, plus the attribution is filed before first use. |
| **BLOCKED** | Any item fails | Dataset is not used. Document why in the dataset's entry so the same source isn't re-evaluated from scratch later. |

## Where this is enforced

- `docs/ONLINE_DATASET_STRATEGY.md` lists, per capability, which dataset *categories* are appropriate — this checklist is the per-dataset gate before any specific one from those categories is actually pulled in.
- `bonbon_field_learning.dataset_version_manager.DatasetVersionManager` records the version history of BonBon's own merged training set (public + field data); each bump should reference the dataset(s) that passed this checklist for that release.
- The `/datasets/license-checklist` dashboard endpoint (Phase 8) surfaces the current CLEARED/BLOCKED state per known dataset source — never silently shows a dataset as usable without a recorded checklist pass.
