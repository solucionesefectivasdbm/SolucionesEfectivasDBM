"""Script para crear el usuario administrador inicial."""
import asyncio
import uuid
import sys
import os

# Asegurar que el directorio backend esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import AsyncSessionLocal, engine, Base
from app.models.usuario import Usuario, TipoUsuario
from app.models import cliente, credito, pago, gestor, receptor, audit_log
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def crear_tablas():
    """Crea todas las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tablas creadas/verificadas.")


async def crear_admin():
    """Crea el usuario admin inicial."""
    async with AsyncSessionLocal() as db:
        # Verificar si ya existe
        from sqlalchemy import select
        existe = (await db.execute(
            select(Usuario).where(Usuario.username == "admin")
        )).scalar_one_or_none()

        if existe:
            print("El usuario admin ya existe. No se creo duplicado.")
            return

        admin = Usuario(
            id=uuid.uuid4(),
            username="admin",
            password_hash=pwd_context.hash("Admin123"),
            telefono="3000000000",
            tipo_usuario=TipoUsuario.admin,
            activo=True,
            must_change_password=True,
        )
        db.add(admin)
        await db.commit()
        print("Usuario admin creado exitosamente.")
        print("  Username: admin")
        print("  Password: Admin123 (se obligara a cambiarla en el primer ingreso)")


async def main():
    await crear_tablas()
    await crear_admin()


if __name__ == "__main__":
    asyncio.run(main())
