#!/usr/bin/env python
"""Script para limpiar los logs de verificación en tiempo real."""

import sqlite3
import os

def clean_verification_logs():
    db_path = "data/database.db"
    
    if not os.path.exists(db_path):
        print("❌ No existe database.db")
        return False
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # Contar registros antes
        c.execute("SELECT COUNT(*) FROM verification_logs")
        count_before = c.fetchone()[0]
        print(f"📊 Registros en verification_logs ANTES: {count_before}")
        
        # Eliminar todos los registros
        c.execute("DELETE FROM verification_logs")
        conn.commit()
        
        # Contar registros después
        c.execute("SELECT COUNT(*) FROM verification_logs")
        count_after = c.fetchone()[0]
        print(f"📊 Registros en verification_logs DESPUÉS: {count_after}")
        
        # Resetear autoincrement
        c.execute("DELETE FROM sqlite_sequence WHERE name='verification_logs'")
        conn.commit()
        
        print(f"\n✅ Eliminados {count_before} registros de verificación_logs")
        print("✅ Base de datos limpiada exitosamente")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = clean_verification_logs()
    exit(0 if success else 1)
