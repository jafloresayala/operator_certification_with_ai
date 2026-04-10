#!/usr/bin/env python
"""Limpiar registros huérfanos en la BD"""

import sqlite3
import os

conn = sqlite3.connect("data/database.db")
c = conn.cursor()

print("\n🧹 LIMPIEZA DE REGISTROS HUÉRFANOS\n")

# Paso 1: Obtener image paths de face_references huérfanas
c.execute("SELECT reference_image_path FROM face_references WHERE employee_id NOT IN (SELECT id FROM employees)")
image_paths = [row[0] for row in c.fetchall()]

print(f"1️⃣ Eliminando {len(image_paths)} archivos de imagen huérfanos...")
for path in image_paths:
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"  ✓ {path}")
    except Exception as e:
        print(f"  ⚠ Error: {path} - {e}")

# Paso 2: Limpiar registros de BD
print(f"\n2️⃣ Eliminando registros huérfanos de la BD...")

# Eliminar face_references huérfanas
c.execute("DELETE FROM face_references WHERE employee_id NOT IN (SELECT id FROM employees)")
count1 = c.rowcount
print(f"  ✓ Eliminadas {count1} referencias de face_references")

# Eliminar identity_samples huérfanas
c.execute("DELETE FROM identity_samples WHERE identity_id NOT IN (SELECT id FROM face_identities)")
count2 = c.rowcount
print(f"  ✓ Eliminadas {count2} muestras de identity_samples")

# Eliminar face_identities sin samples
c.execute("DELETE FROM face_identities WHERE id NOT IN (SELECT identity_id FROM identity_samples)")
count3 = c.rowcount
print(f"  ✓ Eliminadas {count3} identidades de face_identities")

conn.commit()
conn.close()

print(f"\n✅ Limpieza completada exitosamente")
print(f"Total registros eliminados: {count1 + count2 + count3}")
