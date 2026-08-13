import asyncio
import sys
import os

# Add the backend directory to sys.path so 'app' can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.base import AsyncSessionLocal
from app.models.user import User
from app.services.passwords import hash_password

async def main():
    async with AsyncSessionLocal() as db:
        hashed = hash_password("StrongPassword123!")
        user = User(email="daddy@example.com", hashed_pw=hashed)
        db.add(user)
        await db.commit()
        print("User created successfully!")

if __name__ == "__main__":
    asyncio.run(main())
