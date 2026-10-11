"""ChargePlus — Phase 5 Model Registry / Artifact Lifecycle.

Phase: 5/6 (Data Mining, Forecasting & Recommendations)
Steps: 5.5–5.6 (Artifact Management, Promotion & Rollback)

File-based approved-model registry operating on the sidecar metadata written
by MLTrainingPipeline. Works offline (no database required); optional
ml.* warehouse recording is handled by training.record_to_db().

Lifecycle rules (fail-closed):
  - Only checksum-verified, schema-compatible artifacts can be approved.
  - Synthetic test artifacts are NEVER promotable unless the registry was
    explicitly constructed with allow_synthetic_promotion=True (test seam;
    production registries always refuse).
  - A model that does not beat its baseline needs an explicit recorded
    override reason to be approved.
  - Exactly one active model pointer; rollback re-points to the previously
    approved version from the append-only audit log.
  - Artifact paths are always resolved inside artifact_dir. Request-supplied
    absolute paths or path traversal (..) are rejected.

CURRENT STATE (2026-10):
  Production has no approved model (COLD maturity, zero real observations).
  get_active() returns None and inference answers NO_MODEL until a genuine
  training run on sufficient real evidence is approved here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.ml.training import FEATURE_NAMES, FEATURE_SCHEMA_VERSION

logger = logging.getLogger("chargeplus.ml.registry")

ACTIVE_POINTER_FILENAME = "active_model.json"
REGISTRY_LOG_FILENAME = "registry_log.jsonl"
ARTIFACT_SUFFIX = ".pkl"
METADATA_SUFFIX = ".json"


class RegistryError(RuntimeError):
    """Raised when a registry operation violates lifecycle rules."""
    pass


@dataclass
class VerificationResult:
    """Outcome of verifying one model artifact."""
    ok: bool
    model_version: str
    errors: list[str] = field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelRegistry:
    """Versioned, checksummed, auditable model artifact registry.

    Usage:
        registry = ModelRegistry(artifact_dir="backend/ml/artifacts")
        registry.approve("v1-20260101-000000", approver="operator@example.com")
        active = registry.get_active()  # None until something is approved
    """

    def __init__(
        self,
        artifact_dir: str = "backend/ml/artifacts",
        *,
        allow_synthetic_promotion: bool = False,
    ) -> None:
        self._artifact_dir = Path(artifact_dir)
        self._allow_synthetic = allow_synthetic_promotion

    # ------------------------------------------------------------------
    # Path containment (never load operator-external or user paths)
    # ------------------------------------------------------------------

    def _resolve_artifact(self, model_version: str) -> Path:
        """Resolves model_version to its .pkl path, contained in artifact_dir."""
        if not model_version or not isinstance(model_version, str):
            raise RegistryError("model_version must be a non-empty string")
        # Reject traversal and absolute/subdirectory games outright.
        if (
            "/" in model_version
            or "\\" in model_version
            or ".." in model_version
            or model_version.startswith(".")
        ):
            raise RegistryError(
                f"Refusing to resolve suspicious model_version {model_version!r}: "
                "only plain version names inside the artifact directory are allowed"
            )
        candidate = (self._artifact_dir / f"model_{model_version}{ARTIFACT_SUFFIX}").resolve()
        root = self._artifact_dir.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RegistryError(
                f"Refusing to resolve {model_version!r} outside the artifact directory"
            ) from exc
        return candidate

    def _metadata_path(self, model_version: str) -> Path:
        return self._resolve_artifact(model_version).with_suffix(METADATA_SUFFIX)

    # ------------------------------------------------------------------
    # Listing & verification
    # ------------------------------------------------------------------

    def list_versions(self) -> list[dict[str, Any]]:
        """Lists every artifact metadata sidecar in the directory."""
        if not self._artifact_dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for meta_path in sorted(self._artifact_dir.glob(f"model_*{METADATA_SUFFIX}")):
            if meta_path.name in (ACTIVE_POINTER_FILENAME,):
                continue
            try:
                out.append(json.loads(meta_path.read_text()))
            except (OSError, ValueError) as exc:
                logger.warning("Unreadable artifact metadata %s: %s", meta_path, exc)
        return out

    def verify(self, model_version: str) -> VerificationResult:
        """Verifies metadata presence, checksum, and schema compatibility."""
        errors: list[str] = []
        try:
            artifact_path = self._resolve_artifact(model_version)
        except RegistryError as exc:
            return VerificationResult(ok=False, model_version=model_version, errors=[str(exc)])

        meta_path = artifact_path.with_suffix(METADATA_SUFFIX)
        try:
            metadata = json.loads(meta_path.read_text())
        except FileNotFoundError:
            return VerificationResult(
                ok=False, model_version=model_version,
                errors=[f"Artifact metadata missing: {meta_path.name}"],
            )
        except ValueError as exc:
            return VerificationResult(
                ok=False, model_version=model_version,
                errors=[f"Artifact metadata is not valid JSON: {exc}"],
            )

        if not artifact_path.is_file():
            errors.append(f"Artifact bytes missing: {artifact_path.name}")

        # Schema compatibility: inference only serves the locked schema.
        if metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            errors.append(
                f"Feature schema mismatch: artifact={metadata.get('feature_schema_version')!r} "
                f"expected={FEATURE_SCHEMA_VERSION!r}"
            )
        if list(metadata.get("feature_names") or []) != list(FEATURE_NAMES):
            errors.append(
                f"Feature list mismatch: artifact={metadata.get('feature_names')!r} "
                f"expected={FEATURE_NAMES!r}"
            )

        # Integrity: recompute checksum over the stored bytes.
        expected = metadata.get("artifact_checksum")
        if not expected:
            errors.append("Artifact metadata has no checksum; cannot verify integrity")
        elif artifact_path.is_file():
            try:
                actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"Cannot read artifact bytes: {exc}")
            else:
                if actual != expected:
                    errors.append(
                        "Artifact checksum mismatch: bytes differ from recorded "
                        "sha256 (tampered or partially written artifact)"
                    )

        if errors:
            logger.warning("Artifact %s FAILED verification: %s", model_version, errors)
            return VerificationResult(ok=False, model_version=model_version, errors=errors, metadata=metadata)
        return VerificationResult(ok=True, model_version=model_version, metadata=metadata)

    # ------------------------------------------------------------------
    # Approval / promotion
    # ------------------------------------------------------------------

    def approve(
        self,
        model_version: str,
        *,
        approver: str,
        allow_non_baseline_beating: bool = False,
        override_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Promotes a verified artifact to the active model.

        Rules:
          - Artifact must verify (checksum + schema).
          - Synthetic test artifacts are refused unless this registry was
            constructed with allow_synthetic_promotion=True.
          - Model must beat its baseline, unless allow_non_baseline_beating
            is set together with a non-empty override_reason (recorded).
        """
        if not approver or not approver.strip():
            raise RegistryError("approver must be a non-empty identifier")
        verification = self.verify(model_version)
        if not verification.ok:
            raise RegistryError(
                f"Cannot approve {model_version!r}: " + "; ".join(verification.errors)
            )
        metadata = verification.metadata or {}

        if metadata.get("is_synthetic_test") and not self._allow_synthetic:
            raise RegistryError(
                f"Cannot approve {model_version!r}: artifact is marked synthetic "
                "(test-only). Synthetic artifacts NEVER qualify for production inference."
            )

        beats = metadata.get("model_beats_baseline")
        if beats is not True and not allow_non_baseline_beating:
            raise RegistryError(
                f"Cannot approve {model_version!r}: model does not beat its baseline "
                "(MAE comparison on the validation split). Re-run with an explicit "
                "override reason if promotion is still justified."
            )
        if beats is not True and not (override_reason and override_reason.strip()):
            raise RegistryError(
                f"Cannot approve {model_version!r} without a recorded override_reason: "
                "non-baseline-beating promotions must be justified in the audit log."
            )

        # Persist approval into the sidecar (atomic rewrite).
        metadata["approved"] = True
        metadata["approved_at"] = _utcnow().isoformat()
        metadata["approved_by"] = approver.strip()
        if override_reason:
            metadata["approval_override_reason"] = override_reason.strip()
        self._write_json_atomic(self._metadata_path(model_version), metadata)

        self._append_log({
            "event": "approve",
            "model_version": model_version,
            "approver": approver.strip(),
            "override_reason": (override_reason or "").strip() or None,
            "at": _utcnow().isoformat(),
        })
        self._write_json_atomic(
            self._artifact_dir / ACTIVE_POINTER_FILENAME,
            {"model_version": model_version, "updated_at": _utcnow().isoformat()},
        )
        logger.info("Model %s approved by %s (active)", model_version, approver)
        return metadata

    # ------------------------------------------------------------------
    # Active model & rollback
    # ------------------------------------------------------------------

    def get_active(self) -> Optional[dict[str, Any]]:
        """Returns verified metadata of the active approved model, else None."""
        pointer = self._artifact_dir / ACTIVE_POINTER_FILENAME
        if not pointer.is_file():
            return None
        try:
            data = json.loads(pointer.read_text())
            version = data.get("model_version")
        except (OSError, ValueError):
            logger.warning("Active-model pointer unreadable; treating as NO_MODEL")
            return None
        if not version:
            return None
        verification = self.verify(version)
        if not verification.ok or not (verification.metadata or {}).get("approved"):
            logger.warning(
                "Active-model pointer is stale (artifact missing/invalid/unapproved); "
                "treating as NO_MODEL"
            )
            return None
        return verification.metadata

    def rollback(self, *, approver: str) -> dict[str, Any]:
        """Re-points the active model to the previously approved version."""
        if not approver or not approver.strip():
            raise RegistryError("approver must be a non-empty identifier")
        current = self.get_active()
        current_version = (current or {}).get("model_version")
        # Walk the audit log backwards for the latest approved version that is
        # not current and still verifies.
        for entry in reversed(self._read_log()):
            if entry.get("event") != "approve":
                continue
            version = entry.get("model_version")
            if not version or version == current_version:
                continue
            verification = self.verify(version)
            if verification.ok and (verification.metadata or {}).get("approved"):
                self._append_log({
                    "event": "rollback",
                    "model_version": version,
                    "from_version": current_version,
                    "approver": approver.strip(),
                    "at": _utcnow().isoformat(),
                })
                self._write_json_atomic(
                    self._artifact_dir / ACTIVE_POINTER_FILENAME,
                    {"model_version": version, "updated_at": _utcnow().isoformat()},
                )
                logger.info("Rolled back active model %s -> %s", current_version, version)
                return verification.metadata or {}
        raise RegistryError("No previously approved model available for rollback")

    # ------------------------------------------------------------------
    # Loading (verified bytes only, contained paths only)
    # ------------------------------------------------------------------

    def load_model_bundle(self, model_version: str) -> dict[str, Any]:
        """Verifies then unpickles the artifact bundle.

        Unpickling is safe here ONLY because: the path is contained in
        artifact_dir (no user-controlled paths), and the bytes must match the
        recorded sha256 BEFORE deserialization. Verification failure refuses
        to load — never fall back to unverified bytes.
        """
        verification = self.verify(model_version)
        if not verification.ok:
            raise RegistryError(
                f"Refusing to load unverified artifact {model_version!r}: "
                + "; ".join(verification.errors)
            )
        import pickle

        try:
            return pickle.loads(self._resolve_artifact(model_version).read_bytes())
        except Exception as exc:
            raise RegistryError(
                f"Artifact {model_version!r} failed to deserialize: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _append_log(self, entry: dict[str, Any]) -> None:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._artifact_dir / REGISTRY_LOG_FILENAME
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def _read_log(self) -> list[dict[str, Any]]:
        log_path = self._artifact_dir / REGISTRY_LOG_FILENAME
        if not log_path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries
