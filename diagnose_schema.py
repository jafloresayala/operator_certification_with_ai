#!/usr/bin/env python
"""Diagnóstico del esquema actual de la BD."""

import sqlite3
import os

def diagnose():
    db_path = "data/database.db"
    
    if not os.path.exists(db_path):
        print("❌ No existe database.db")
        return
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Listar todas las tablas
    print("📊 Tablas en la BD:")
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    for table in tables:
        print(f"  - {table[0]}")
    
    # Ver schema de employees
    print("\n🗂️ Esquema de la tabla 'employees':")
    c.execute("PRAGMA table_info(employees)")
    columns = c.fetchall()
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    
    # Ver schema de employees_old (si existe)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='employees_old'")
    if c.fetchone():
        print("\n🗂️ Esquema de la tabla 'employees_old':")
        c.execute("PRAGMA table_info(employees_old)")
        columns = c.fetchall()
        for col in columns:
            print(f"  {col[1]}: {col[2]}")
        
        # Contar registros
        c.execute("SELECT COUNT(*) FROM employees_old")
        count = c.fetchone()[0]
        print(f"  📦 Registros: {count}")
    
    # Contar registros en employees
    c.execute("SELECT COUNT(*) FROM employees")
    count = c.fetchone()[0]
    print(f"\n📦 Registros en 'employees': {count}")
    
    conn.close()

if __name__ == "__main__":
    diagnose()
