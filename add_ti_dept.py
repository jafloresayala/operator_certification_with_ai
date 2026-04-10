#!/usr/bin/env python
"""Agregar TI a los departamentos si no existe."""

import sqlite3
import os

db_path = "data/database.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Listar departamentos actuales
print("📋 Departamentos actuales:")
c.execute("SELECT id, name FROM departments ORDER BY name")
depts = c.fetchall()
for dept_id, name in depts:
    print(f"  {dept_id}: {name}")

# Verificar si TI existe
c.execute("SELECT id FROM departments WHERE name = 'TI'")
if not c.fetchone():
    print("\n➕ Agregando departamento TI...")
    c.execute("INSERT INTO departments (name, created_at) VALUES (?, datetime('now'))", ("TI",))
    conn.commit()
    print("✅ TI agregado")
else:
    print("\n✅ TI ya existe")

conn.close()
