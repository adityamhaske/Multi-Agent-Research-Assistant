import asyncio
from app.db.base import async_session_maker
from app.models.user import User
from app.services.passwords import hash_password

async def main():
    async with async_session_maker() as db:
        hashed = hash_password("StrongPassword123!")
        user = User(email="daddy@example.com", hashed_pw=hashed)
        db.add(user)
        await db.commit()
        print("User created successfully!")

if __name__ == "__main__":
    asyncio.run(main())
