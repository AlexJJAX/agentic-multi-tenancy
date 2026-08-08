"""
Seed module for initializing demo data.

Seeds tenant records into SQLite and creates demo knowledge base
markdown files if they do not already exist.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select

from app.config import settings
from app.db import get_db_session
from app.models import Tenant

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Seed tenant definitions
# ──────────────────────────────────────────────

SEED_TENANTS = [
    {
        "tenant_id": "tenant-A",
        "tenant_name": "Tenant A - Acme Payments",
        "metadata_json": json.dumps({"theme": "blue", "tier": "demo"}),
    },
    {
        "tenant_id": "tenant-B",
        "tenant_name": "Tenant B - Beta Devices",
        "metadata_json": json.dumps({"theme": "green", "tier": "demo"}),
    },
]

# ──────────────────────────────────────────────
# Demo user definitions (local auth only)
#
# Each entry maps a username to its tenant and plaintext password.
# The auth service bcrypt-hashes the password on first load — these
# plaintexts are only used to compute the initial hash and never stored.
# ──────────────────────────────────────────────

DEMO_USERS = [
    {
        "username": "user-a",
        "password": "password-a",
        "tenant_id": "tenant-A",
        "role": "user",
    },
    {
        "username": "user-b",
        "password": "password-b",
        "tenant_id": "tenant-B",
        "role": "user",
    },
    {
        "username": "admin",
        "password": "admin-secret",
        "tenant_id": "tenant-A",  # Admin is scoped to tenant-A for demo purposes
        "role": "admin",
    },
]

# ──────────────────────────────────────────────
# Demo KB content
# ──────────────────────────────────────────────

TENANT_A_KB = """\
# Tenant A Payment and Returns Policy

Tenant A is Acme Payments. This dummy knowledge base is only about payment issues, refunds, and returns.

## Accepted Payment Methods

- Tenant A accepts credit cards, debit cards, and ACH transfer.
- If a payment fails, the customer should verify the billing address, confirm the card has not expired, and retry once after 15 minutes.
- If two payment attempts fail, the customer should contact Tenant A payment support.

## Duplicate Payments and Refunds

- If a customer believes they were charged twice, they should not submit another payment attempt.
- Pending duplicate authorizations may disappear within 24 hours.
- If the duplicate payment has settled, Tenant A treats it as refundable.
- Approved duplicate-payment refunds are returned to the original payment method within five business days.

## Returns Policy

- Physical items can be returned within 30 days of delivery if unused and in original packaging.
- A return authorization number is required before shipping an item back.
- Original shipping fees are not refundable unless Tenant A caused the fulfillment error.

## Subscription Refunds

- Subscription charges can be refunded within 14 days if no premium feature was used during the billing period.
- Partial-month subscription refunds are not offered after the 14-day window.
"""

TENANT_B_KB = """\
# Tenant B Device Troubleshooting Policy

Tenant B is Beta Devices. This dummy knowledge base is only about device reset, update, and troubleshooting steps.

## Device Reset Steps

- For a soft reset, hold the device power button for 10 seconds, release it, and wait for the status light to turn solid blue.
- For a factory reset, hold the recessed reset button for 15 seconds until the status light flashes amber.
- A factory reset removes saved Wi-Fi settings and paired accounts.

## Device Update Steps

- Before updating, connect the device to Wi-Fi and make sure the battery is at least 50% charged.
- To update from the device menu, open Settings, choose Device, and select Update Firmware.
- If the device menu is unavailable, use the Beta Device Tool over USB and choose Manual Firmware Update.

## Connectivity Troubleshooting

- If the device cannot connect, restart the router and confirm the network is a 2.4 GHz Wi-Fi network.
- Move the device within 10 meters of the router during setup.
- If pairing fails three times, perform a soft reset and try pairing again.
"""

# Map tenant IDs to their KB content and file names
TENANT_KB_MAP = {
    "tenant-A": {
        "filename": "payment_returns_policy.md",
        "content": TENANT_A_KB,
    },
    "tenant-B": {
        "filename": "device_troubleshooting_policy.md",
        "content": TENANT_B_KB,
    },
}


async def seed_tenants() -> None:
    """
    Seed tenant records into SQLite if they do not already exist.

    Creates tenant-A and tenant-B with their display names and metadata.
    """
    async with get_db_session() as session:
        for tenant_data in SEED_TENANTS:
            # Check if tenant already exists
            result = await session.execute(
                select(Tenant).where(Tenant.tenant_id == tenant_data["tenant_id"])
            )
            existing = result.scalar_one_or_none()

            if existing is None:
                tenant = Tenant(
                    tenant_id=tenant_data["tenant_id"],
                    tenant_name=tenant_data["tenant_name"],
                    created_at=datetime.now(timezone.utc).isoformat(),
                    metadata_json=tenant_data["metadata_json"],
                )
                session.add(tenant)
                logger.info("Seeded tenant: %s", tenant_data["tenant_id"])
            else:
                logger.info("Tenant already exists: %s", tenant_data["tenant_id"])


def seed_kb_files() -> None:
    """
    Create demo knowledge base markdown files if they do not already exist.

    Writes tenant-specific markdown documents to data/kb/<tenant_id>/.
    """
    kb_root = settings.kb_root_path

    for tenant_id, kb_info in TENANT_KB_MAP.items():
        tenant_dir = kb_root / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)

        file_path = tenant_dir / kb_info["filename"]
        if not file_path.exists():
            file_path.write_text(kb_info["content"], encoding="utf-8")
            logger.info("Created KB file: %s", file_path)
        else:
            logger.info("KB file already exists: %s", file_path)


async def run_all_seeds() -> None:
    """Run all seed operations: tenants and KB files."""
    seed_kb_files()
    await seed_tenants()
    logger.info("Seed operations complete")
