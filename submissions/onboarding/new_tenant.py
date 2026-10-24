"""Register a new NBFC: tenant row + mapping files from the templates (+ optional placeholder bureau profiles).

Usage:  python -m submissions.onboarding.new_tenant --tenant nbfc_017 --name "Acme Finance" --schema nbfc_017
                                                   [--strategy stream|insert_select] [--placeholder-bureaus]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import Engine

from submissions.bureaus import BureauRepository
from submissions.bureaus.seed import placeholder_profiles
from submissions.enums import ExtractStrategy
from submissions.tenants import Tenant, TenantRepository

TEMPLATES = Path("clients/_template")             # one <type>.yaml per submission type


def register_tenant(engine: Engine, base_dir: Path, tenant_id: str, name: str, schema: str,
                    strategy: ExtractStrategy | str = ExtractStrategy.STREAM,
                    placeholder_bureaus: bool = False) -> tuple[Tenant, Path, bool]:
    """Create/update the tenant and create its mapping files (one per type, from the templates) if missing.
    Returns (tenant, client folder, whether any file was created)."""
    folder_rel = Path("clients") / tenant_id
    tenant = Tenant(tenant_id, name, schema, folder_rel.as_posix(), ExtractStrategy(strategy))  # validates ids
    folder = base_dir / folder_rel
    created = False
    for template in sorted((base_dir / TEMPLATES).glob("*.yaml")):
        target = folder / template.name
        if not target.exists():
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(template.read_text(encoding="utf-8").replace("<tenant_id>", tenant_id)
                              .replace("<schema>", schema), encoding="utf-8", newline="\n")
            created = True
    tenants = TenantRepository(engine)
    tenants.upsert(tenant)
    if placeholder_bureaus:
        repo = BureauRepository(engine)
        number = len(tenants.list(active_only=False))
        for profile in placeholder_profiles(tenant_id, number, name.upper()):
            repo.upsert(profile)
    return tenant, folder, created


def main(argv: list[str] | None = None) -> int:
    from submissions.config import Settings
    from submissions.db import make_engine

    ap = argparse.ArgumentParser(description="Register a new NBFC tenant")
    ap.add_argument("--tenant", required=True, help="tenant id, e.g. nbfc_017 (lowercase, digits, underscore)")
    ap.add_argument("--name", required=True, help="display name")
    ap.add_argument("--schema", required=True, help="the NBFC's schema in the LMS database")
    ap.add_argument("--strategy", default="stream", choices=[s.value for s in ExtractStrategy])
    ap.add_argument("--placeholder-bureaus", action="store_true",
                    help="add PLACEHOLDER bureau profiles (replace with the real member IDs before generating files)")
    args = ap.parse_args(argv)
    tenant, path, created = register_tenant(make_engine(Settings.from_env().database_url), Path.cwd(), args.tenant,
                                            args.name, args.schema, args.strategy, args.placeholder_bureaus)
    print(f"Tenant {tenant.tenant_id} registered (schema {tenant.source_schema}, {tenant.extract_strategy}).")
    print(f"Mapping files: {path} ({'created from templates' if created else 'already existed, left unchanged'})")
    print("Next: python -m submissions.onboarding.introspect --schema", tenant.source_schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
