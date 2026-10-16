"""Spike item 5 input: dump every symbol name on the demo account to data/local/spike/."""

from __future__ import annotations

import asyncio
import json

from _conn import OUT, demo_client


async def main() -> None:
    async with demo_client() as client:
        names = await client.symbol_names()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "symbols.json").write_text(json.dumps(names, indent=1, sort_keys=True))
    us = sorted(n for n in names if ".US" in n)
    print(f"{len(names)} symbols, {len(us)} containing '.US'")


if __name__ == "__main__":
    asyncio.run(main())
