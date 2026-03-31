#!/usr/bin/env python3
"""
Správa uživatelů v databázi.

Příkazy:
  create  <email> <heslo>   Vytvoří nového uživatele
  reset   <email> <heslo>   Změní heslo existujícímu uživateli
  list                      Vypíše všechny uživatele

Použití uvnitř Docker kontejneru:
  docker compose exec backend python scripts/create_user.py create admin@dautuu.local moje_heslo
  docker compose exec backend python scripts/create_user.py reset  admin@dautuu.local nove_heslo
  docker compose exec backend python scripts/create_user.py list
"""

import asyncio
import sys
from pathlib import Path

# Přidáme /app do sys.path (kořen backendu v kontejneru)
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.db.models import User
from app.db.init_db import init_db


async def cmd_create(email: str, password: str) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            print(f"[chyba] Uživatel '{email}' již existuje. Pro změnu hesla použij: reset {email} <heslo>")
            sys.exit(1)

        user = User(email=email, hashed_password=get_password_hash(password))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"[ok] Uživatel vytvořen:")
        print(f"     id:    {user.id}")
        print(f"     email: {user.email}")


async def cmd_reset(email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"[chyba] Uživatel '{email}' nenalezen.")
            sys.exit(1)

        user.hashed_password = get_password_hash(password)
        await db.commit()
        print(f"[ok] Heslo pro '{email}' bylo změněno.")


async def cmd_list() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).order_by(User.created_at))
        users = result.scalars().all()
        if not users:
            print("[prázdno] Žádní uživatelé v databázi.")
            return
        for u in users:
            print(f"  {u.email}  (id: {u.id}, vytvořen: {u.created_at})")


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(1)

    cmd = args[0]

    if cmd == "create":
        if len(args) != 3:
            print("Použití: create <email> <heslo>")
            sys.exit(1)
        _, email, password = args
        if len(password) < 6:
            print("[chyba] Heslo musí mít alespoň 6 znaků.")
            sys.exit(1)
        asyncio.run(cmd_create(email, password))

    elif cmd == "reset":
        if len(args) != 3:
            print("Použití: reset <email> <heslo>")
            sys.exit(1)
        _, email, password = args
        if len(password) < 6:
            print("[chyba] Heslo musí mít alespoň 6 znaků.")
            sys.exit(1)
        asyncio.run(cmd_reset(email, password))

    elif cmd == "list":
        asyncio.run(cmd_list())

    else:
        print(f"[chyba] Neznámý příkaz '{cmd}'.")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
