#!/usr/bin/env python3
"""Backfill phash_int and phash_q0-q3 columns from existing phash hex strings.

Usage: Run inside the API container:
    python db/backfill_phash_quarters.py
"""
import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))


async def main():
    from sqlalchemy import text
    from core.database import async_engine

    batch_size = 10000
    total = 0

    async with async_engine.begin() as conn:
        # Count rows needing backfill
        row = await conn.execute(text(
            "SELECT COUNT(*) FROM blobs WHERE phash IS NOT NULL AND phash_int IS NULL"
        ))
        remaining = row.scalar_one()
        print(f"Rows to backfill: {remaining}")

        while True:
            result = await conn.execute(text("""
                UPDATE blobs SET
                    phash_int = ('x' || lpad(phash, 16, '0'))::bit(64)::bigint,
                    phash_q0 = ((('x' || lpad(phash, 16, '0'))::bit(64)::bigint >> 48) & 65535)::smallint,
                    phash_q1 = ((('x' || lpad(phash, 16, '0'))::bit(64)::bigint >> 32) & 65535)::smallint,
                    phash_q2 = ((('x' || lpad(phash, 16, '0'))::bit(64)::bigint >> 16) & 65535)::smallint,
                    phash_q3 = (('x' || lpad(phash, 16, '0'))::bit(64)::bigint & 65535)::smallint
                WHERE sha256 IN (
                    SELECT sha256 FROM blobs
                    WHERE phash IS NOT NULL AND phash_int IS NULL
                    LIMIT :batch_size
                )
            """), {"batch_size": batch_size})

            updated = result.rowcount
            total += updated
            print(f"  Backfilled {total} rows ({updated} this batch)")

            if updated < batch_size:
                break

    print(f"Done: {total} rows backfilled")


if __name__ == "__main__":
    asyncio.run(main())
