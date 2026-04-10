"""
Migrate database.db from root folder to data/ folder.
Ejecutar una sola vez: python migrate_database.py
"""

import os
import shutil
from pathlib import Path

def migrate_database():
    """Mueve database.db del raíz a data/ si existe."""
    
    # Rutas
    root_db = "database.db"
    data_dir = "data"
    new_db_path = os.path.join(data_dir, "database.db")
    
    # Si el nuevo archivo ya existe, no hacer nada
    if os.path.exists(new_db_path):
        print(f"✓ database.db ya está en {new_db_path}")
        return
    
    # Si el archivo antiguo existe en raíz, mover
    if os.path.exists(root_db):
        os.makedirs(data_dir, exist_ok=True)
        shutil.move(root_db, new_db_path)
        print(f"✓ database.db migrado de raíz a {new_db_path}")
    else:
        print(f"✓ No se encontró database.db en raíz (nueva instalación)")

if __name__ == "__main__":
    migrate_database()
    print("✅ Migración completada")
