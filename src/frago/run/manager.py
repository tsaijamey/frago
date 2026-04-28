"""Run Instance Manager

Phase 1 (run-as-domain-knowledge-base):
- Run instance is now a Domain (long-lived, theme-scoped knowledge base).
- Directory naming switches from ``YYYYMMDD-<slug>`` to ``<domain>``.
- Metadata file is ``_domain.json`` (legacy ``.metadata.json`` is still read
  as a fallback during the migration window).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import FileSystemError, InvalidRunIDError, RunNotFoundError
from .models import RunInstance, RunStatus
from .utils import (
    ensure_directory_exists,
    is_legacy_run_dir,
    is_valid_run_id,
    normalize_domain_name,
    parse_cross_domain,
)

# Filenames
DOMAIN_METADATA_FILENAME = "_domain.json"
LEGACY_METADATA_FILENAME = ".metadata.json"


class RunManager:
    """Run Instance Manager (Domain-aware)."""

    def __init__(self, projects_dir: Path):
        """Initialize manager

        Args:
            projects_dir: projects directory path
        """
        self.projects_dir = projects_dir
        ensure_directory_exists(projects_dir)

    # ------------------------------------------------------------------
    # Phase 1 primary API: domain ensure / deactivate
    # ------------------------------------------------------------------

    def ensure_domain(self, domain: str) -> RunInstance:
        """Ensure a domain directory exists and return its RunInstance.

        Idempotent: if the domain already exists, the existing metadata is
        loaded and ``last_accessed`` is refreshed (in-memory, not written back
        unless we created the directory in this call).

        Args:
            domain: raw domain name (will be normalized)

        Returns:
            RunInstance for the domain
        """
        domain_name = normalize_domain_name(domain)
        if not domain_name:
            raise InvalidRunIDError(domain, "domain name cannot be empty after normalization")
        if not is_valid_run_id(domain_name):
            raise InvalidRunIDError(domain_name, "format must be A-Z, a-z, 0-9, hyphens, length 1-100")

        run_dir = self.projects_dir / domain_name
        domain_metadata_file = run_dir / DOMAIN_METADATA_FILENAME
        legacy_metadata_file = run_dir / LEGACY_METADATA_FILENAME

        # Existing domain: load and return.
        if run_dir.exists() and (domain_metadata_file.exists() or legacy_metadata_file.exists()):
            return self._read_metadata_files(run_dir, domain_name)

        # Fresh domain: create directory tree + metadata.
        now = datetime.now()
        ensure_directory_exists(run_dir)
        ensure_directory_exists(run_dir / "logs")
        ensure_directory_exists(run_dir / "screenshots")
        ensure_directory_exists(run_dir / "scripts")
        ensure_directory_exists(run_dir / "outputs")

        components = parse_cross_domain(domain_name)
        is_cross = components is not None
        # Phase 3: populate alias cache from the def domain_dict if present.
        try:
            from .domain_dict import list_aliases

            cached_aliases = list_aliases(domain_name)
        except Exception:
            cached_aliases = []
        instance = RunInstance(
            run_id=domain_name,
            theme_description=domain_name,
            created_at=now,
            last_accessed=now,
            status=RunStatus.ACTIVE,
            domain=domain_name,
            aliases=cached_aliases,
            is_cross_domain=is_cross,
            component_domains=components or [],
            session_count=0,
            insight_count=0,
        )
        self._write_metadata(run_dir, instance)
        return instance

    def deactivate_domain(self, domain: str) -> RunInstance:
        """Mark a domain as INACTIVE.

        Args:
            domain: raw domain name (will be normalized)

        Returns:
            Updated RunInstance.
        """
        domain_name = normalize_domain_name(domain)
        instance = self.find_run(domain_name)
        instance.status = RunStatus.INACTIVE
        instance.last_accessed = datetime.now()
        run_dir = self.projects_dir / domain_name
        self._write_metadata(run_dir, instance)
        return instance

    # ------------------------------------------------------------------
    # Domain resolution for sessions
    # ------------------------------------------------------------------

    def resolve_domain_for_session(self, session_id: str, project_path: str) -> str:
        """Resolve which domain a session should be attached to.

        Phase 1 logic (def-dictionary lookup is added in Phase 3):
        1. ``FRAGO_DOMAIN`` env var (normalized) wins.
        2. Otherwise, fall back to the current run context (``~/.frago/current_run``).
        3. Otherwise, use ``"misc"``.

        Args:
            session_id: Claude session id
            project_path: absolute project path (currently unused, reserved
                for Phase 3 def-dict matching)

        Returns:
            Normalized domain name.
        """
        env_domain = os.environ.get("FRAGO_DOMAIN")
        if env_domain:
            normalized = normalize_domain_name(env_domain)
            if normalized:
                return normalized

        # Try current_run context.
        try:
            from .context import ContextManager  # local import to avoid cycles
            ctx_mgr = ContextManager(self.projects_dir.parent, self.projects_dir)
            ctx = ctx_mgr.get_current_run()
            if ctx and ctx.run_id:
                return ctx.run_id
        except Exception:
            pass

        return "misc"

    # ------------------------------------------------------------------
    # Legacy create_run / archive_run preserved as thin wrappers
    # ------------------------------------------------------------------

    def resolve_domain_from_description(self, description: str) -> Optional[str]:
        """Lookup a description in the def ``domain_dict`` (Phase 3).

        Returns the canonical domain name on a hit, or ``None`` when no
        alias matches. Multiple distinct canonical hits collapse to a
        ``CROSS-<a>-<b>...`` synthetic name.
        """
        from .domain_dict import lookup_domain

        return lookup_domain(description)

    def create_run(self, theme_description: str, run_id: Optional[str] = None) -> RunInstance:
        """Create new run instance (legacy API).

        Phase 1+: thin wrapper around :meth:`ensure_domain`. The old
        ``YYYYMMDD-<slug>`` naming is gone.

        Phase 3: when ``run_id`` is not provided we first try the def
        ``domain_dict`` lookup. A hit reuses the canonical domain (e.g.
        ``"我想看看 推特 上的热点"`` → ``"twitter"``); a miss falls back to
        the slugified description (Phase 1 behavior).

        Args:
            theme_description: task description / domain seed
            run_id: optional explicit domain id (skips dict lookup)

        Returns:
            RunInstance instance
        """
        if run_id:
            seed = run_id
        else:
            canonical = self.resolve_domain_from_description(theme_description)
            seed = canonical or theme_description
        instance = self.ensure_domain(seed)
        # Preserve theme_description metadata when caller provided one
        # different from the (normalized) domain name.
        if theme_description and theme_description != instance.theme_description:
            instance.theme_description = theme_description
            run_dir = self.projects_dir / instance.run_id
            self._write_metadata(run_dir, instance)
        return instance

    def archive_run(self, run_id: str) -> RunInstance:
        """Archive run instance (legacy alias for :meth:`deactivate_domain`)."""
        return self.deactivate_domain(run_id)

    # ------------------------------------------------------------------
    # Find / list
    # ------------------------------------------------------------------

    def find_run(self, run_id: str) -> RunInstance:
        """Find a run instance / domain by id.

        Reads ``_domain.json`` first, falling back to ``.metadata.json``.
        """
        run_dir = self.projects_dir / run_id
        if not run_dir.exists() or not run_dir.is_dir():
            raise RunNotFoundError(run_id)

        return self._read_metadata_files(run_dir, run_id)

    def list_runs(self, status: Optional[RunStatus] = None) -> List[Dict]:
        """List all run instances / domains.

        Args:
            status: filter status (None = all)

        Returns:
            list of dicts with summary info
        """
        if not self.projects_dir.exists():
            return []

        runs = []
        for run_dir in self.projects_dir.iterdir():
            if not run_dir.is_dir():
                continue
            # Skip helper directories (e.g. _legacy/, _migrating/).
            if run_dir.name.startswith("_"):
                continue

            domain_metadata_file = run_dir / DOMAIN_METADATA_FILENAME
            legacy_metadata_file = run_dir / LEGACY_METADATA_FILENAME
            if not domain_metadata_file.exists() and not legacy_metadata_file.exists():
                continue

            try:
                instance = self._read_metadata_files(run_dir, run_dir.name)
            except Exception:
                continue  # skip corrupted

            if status and instance.status != status:
                continue

            try:
                from .logger import RunLogger

                logger = RunLogger(run_dir)
                log_count = logger.count_logs()
            except Exception:
                log_count = 0

            screenshots_dir = run_dir / "screenshots"
            screenshot_count = (
                len(list(screenshots_dir.glob("*.png"))) if screenshots_dir.is_dir() else 0
            )

            runs.append(
                {
                    "run_id": instance.run_id,
                    "status": instance.status.value,
                    "created_at": instance.created_at.isoformat(),
                    "last_accessed": instance.last_accessed.isoformat(),
                    "theme_description": instance.theme_description,
                    "domain": instance.domain,
                    "is_cross_domain": instance.is_cross_domain,
                    "component_domains": instance.component_domains,
                    "session_count": instance.session_count,
                    "insight_count": instance.insight_count,
                    "log_count": log_count,
                    "screenshot_count": screenshot_count,
                    "is_legacy": is_legacy_run_dir(run_dir.name),
                }
            )

        runs.sort(key=lambda r: str(r["last_accessed"]), reverse=True)
        return runs

    # ------------------------------------------------------------------
    # Phase 2 — domain peek / counters / patch
    # ------------------------------------------------------------------

    def bump_insight_count(self, domain: str, delta: int = 1) -> RunInstance:
        """Increment ``insight_count`` for a domain and refresh ``last_accessed``.

        Args:
            domain: raw domain name (will be normalized)
            delta: amount to bump (default +1; pass negative to decrement)

        Returns:
            Updated RunInstance.
        """
        domain_name = normalize_domain_name(domain)
        instance = self.find_run(domain_name)
        instance.insight_count = max(0, instance.insight_count + delta)
        instance.last_accessed = datetime.now()
        run_dir = self.projects_dir / domain_name
        self._write_metadata(run_dir, instance)
        return instance

    def update_run(self, domain: str, **fields) -> RunInstance:
        """Patch RunInstance fields and persist.

        Only writable scalar / list fields are accepted; unknown keys are
        ignored to keep the API tolerant.
        """
        domain_name = normalize_domain_name(domain)
        instance = self.find_run(domain_name)

        allowed = {
            "theme_description",
            "status",
            "domain",
            "aliases",
            "is_cross_domain",
            "component_domains",
            "session_count",
            "insight_count",
        }
        for key, value in fields.items():
            if key in allowed:
                if key == "status" and isinstance(value, str):
                    value = RunStatus(value)
                setattr(instance, key, value)
        instance.last_accessed = datetime.now()
        run_dir = self.projects_dir / domain_name
        self._write_metadata(run_dir, instance)
        return instance

    def peek_domain(
        self,
        domain: str,
        *,
        n_sessions: int = 3,
        n_insights: int = 5,
    ) -> Dict:
        """Return a compact prior-knowledge summary for ``domain``.

        Designed for sub-agent bootstrap injection: keep payload small (target
        <4KB) and focused on the most recent activity + top insights.
        """
        domain_name = normalize_domain_name(domain)
        instance = self.find_run(domain_name)
        run_dir = self.projects_dir / domain_name

        # Recent sessions: each session lives under a subdir with metadata.json
        sessions: List[Dict] = []
        if run_dir.is_dir():
            session_dirs = [
                p for p in run_dir.iterdir()
                if p.is_dir() and not p.name.startswith("_") and p.name not in ("logs", "screenshots", "scripts", "outputs")
            ]
            session_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for session_dir in session_dirs[:n_sessions]:
                meta_file = session_dir / "metadata.json"
                summary_md = session_dir / "summary.md"
                entry: Dict = {"session_id": session_dir.name}
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        entry["status"] = meta.get("status")
                        entry["last_activity"] = meta.get("last_activity")
                    except Exception:
                        pass
                if summary_md.exists():
                    try:
                        head = summary_md.read_text(encoding="utf-8").splitlines()[:3]
                        entry["summary_head"] = "\n".join(head)
                    except Exception:
                        pass
                sessions.append(entry)

        # Recent insights: import lazily to avoid cycles.
        try:
            from .insights import list_insights

            insights = list_insights(self.projects_dir, domain_name, limit=n_insights)
            insight_payload = [
                {
                    "id": i.id,
                    "type": i.type.value,
                    "payload": i.payload,
                    "confidence": i.confidence,
                    "updated_at": i.updated_at.isoformat(),
                }
                for i in insights
            ]
        except Exception:
            insight_payload = []

        return {
            "domain": instance.run_id,
            "status": instance.status.value,
            "is_cross_domain": instance.is_cross_domain,
            "component_domains": instance.component_domains,
            "session_count": instance.session_count,
            "insight_count": instance.insight_count,
            "last_accessed": instance.last_accessed.isoformat(),
            "recent_sessions": sessions,
            "top_insights": insight_payload,
        }

    def get_run_statistics(self, run_id: str) -> Dict:
        """Get run instance statistics."""
        instance = self.find_run(run_id)
        run_dir = self.projects_dir / run_id

        from .logger import RunLogger

        logger = RunLogger(run_dir)

        screenshots_dir = run_dir / "screenshots"
        screenshot_count = (
            len(list(screenshots_dir.glob("*.png"))) if screenshots_dir.is_dir() else 0
        )
        scripts_dir = run_dir / "scripts"
        script_count = (
            sum(
                1
                for p in scripts_dir.iterdir()
                if p.is_file() and p.suffix in [".py", ".js", ".sh"]
            )
            if scripts_dir.is_dir()
            else 0
        )

        disk_usage = sum(f.stat().st_size for f in run_dir.rglob("*") if f.is_file())

        return {
            "log_entries": logger.count_logs(),
            "screenshots": screenshot_count,
            "scripts": script_count,
            "disk_usage_bytes": disk_usage,
            "session_count": instance.session_count,
            "insight_count": instance.insight_count,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_metadata_files(self, run_dir: Path, run_id: str) -> RunInstance:
        """Read ``_domain.json`` first, then fall back to ``.metadata.json``."""
        domain_metadata_file = run_dir / DOMAIN_METADATA_FILENAME
        legacy_metadata_file = run_dir / LEGACY_METADATA_FILENAME

        target: Optional[Path] = None
        if domain_metadata_file.exists():
            target = domain_metadata_file
        elif legacy_metadata_file.exists():
            target = legacy_metadata_file
        else:
            raise FileSystemError(
                "read",
                str(domain_metadata_file),
                "Metadata file not found (looked for _domain.json and .metadata.json)",
            )

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return RunInstance.from_dict(data)
        except Exception as e:
            raise FileSystemError("read", str(target), str(e)) from e

    def _write_metadata(self, run_dir: Path, instance: RunInstance) -> None:
        """Write ``_domain.json`` (Phase 1 canonical metadata file)."""
        metadata_file = run_dir / DOMAIN_METADATA_FILENAME
        try:
            metadata_file.write_text(
                json.dumps(instance.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            raise FileSystemError("write", str(metadata_file), str(e)) from e
