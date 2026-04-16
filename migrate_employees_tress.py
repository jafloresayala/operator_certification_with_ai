"""
Migración: Actualizar tabla employees para usar columnas directas de TRESS API.
Elimina dependencia de tablas departments, roles, locations.

ANTES:  employee_number, name, department_id(FK), role_id(FK), location_id(FK), email, phone, shift, status, notes
DESPUÉS: employee_number, name, first_name, last_name, middle_name, user_id, email, level,
         role_code, role_description, cost_center_code, cost_center_description,
         shift_code, shift_description, supervisor_role, status, notes

Ejecutar UNA sola vez:  python migrate_employees_tress.py
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "database.db")

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ No se encontró la base de datos en: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Obtener columnas actuales de employees
    c.execute("PRAGMA table_info(employees)")
    existing_cols = {row[1] for row in c.fetchall()}
    print(f"Columnas actuales: {existing_cols}")

    # 2. Nuevas columnas que necesitamos agregar
    new_columns = [
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("middle_name", "TEXT"),
        ("user_id", "TEXT"),
        ("level", "TEXT"),
        ("role_code", "TEXT"),
        ("role_description", "TEXT"),
        ("cost_center_code", "TEXT"),
        ("cost_center_description", "TEXT"),
        ("shift_code", "TEXT"),
        ("shift_description", "TEXT"),
        ("supervisor_role", "TEXT"),
    ]

    added = []
    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            c.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}")
            added.append(col_name)
            print(f"  ✅ Columna agregada: {col_name} ({col_type})")
        else:
            print(f"  ⏭️ Columna ya existe: {col_name}")

    # 3. Migrar datos existentes: resolver department/role/location names desde FK
    c.execute("SELECT id, department_id, role_id, location_id, shift FROM employees")
    rows = c.fetchall()
    
    for row in rows:
        emp_id = row[0]
        dept_id = row[1]
        role_id = row[2]
        loc_id = row[3]
        old_shift = row[4]

        # Obtener nombre de departamento → cost_center_description (best effort mapping)
        dept_name = None
        if dept_id:
            c.execute("SELECT name FROM departments WHERE id = ?", (dept_id,))
            r = c.fetchone()
            if r:
                dept_name = r[0]

        # Obtener nombre de rol → role_description
        role_name = None
        if role_id:
            c.execute("SELECT name FROM roles WHERE id = ?", (role_id,))
            r = c.fetchone()
            if r:
                role_name = r[0]

        # Obtener nombre de ubicación (info legacy)
        loc_name = None
        if loc_id:
            c.execute("SELECT name FROM locations WHERE id = ?", (loc_id,))
            r = c.fetchone()
            if r:
                loc_name = r[0]

        # Actualizar con datos migrados
        updates = {}
        if dept_name and "cost_center_description" in (existing_cols | set(added)):
            updates["cost_center_description"] = dept_name
        if role_name and "role_description" in (existing_cols | set(added)):
            updates["role_description"] = role_name
        if old_shift and "shift_description" in (existing_cols | set(added)):
            updates["shift_description"] = old_shift

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [emp_id]
            c.execute(f"UPDATE employees SET {set_clause} WHERE id = ?", values)
            print(f"  📝 Empleado #{emp_id}: migrados campos {list(updates.keys())}")

    conn.commit()

    # 4. Nota: NO eliminamos las tablas departments, roles, locations aquí
    #    porque SQLite no soporta DROP COLUMN fácilmente.
    #    Las FK columns (department_id, role_id, location_id) quedarán como legacy.
    #    El código nuevo simplemente las ignorará.

    print("\n✅ Migración completada exitosamente.")
    print("   Las tablas departments, roles, locations siguen existiendo pero ya no se usarán.")
    print("   Las columnas department_id, role_id, location_id quedan como legacy (no se pueden eliminar en SQLite).")
    
    conn.close()


if __name__ == "__main__":
    migrate()
