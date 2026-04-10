#!/usr/bin/env python
"""Completar migración con TI existente."""

import sqlite3
import os

def complete_migration_v2():
    db_path = "data/database.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    print("🔍 Verificando roloes en IT...")
    c.execute("SELECT id, name FROM roles WHERE department_id = (SELECT id FROM departments WHERE name = 'IT')")
    it_roles = c.fetchall()
    print(f"  Roles en IT: {[r[1] for r in it_roles]}")
    
    # Verificar qué roles tienen los empleados antiguos
    print("\n🔍 Roles en employees_old:")
    c.execute("SELECT DISTINCT role FROM employees_old")
    old_roles = c.fetchall()
    print(f"  Roles: {[r[0] for r in old_roles]}")
    
    # Obtener IT department ID
    c.execute("SELECT id FROM departments WHERE name IN ('IT', 'TI')")
    dept_result = c.fetchone()
    it_dept_id = dept_result[0] if dept_result else None
    
    if not it_dept_id:
        print("❌ No encontré departamento IT")
        conn.close()
        return False
    
    print(f"\n✅ Usando departamento IT (ID={it_dept_id})")
    
    # Obtener Analyst role (o el más genérico)
    c.execute("""SELECT id FROM roles 
                 WHERE department_id = ? 
                 ORDER BY name 
                 LIMIT 1""", (it_dept_id,))
    role_result = c.fetchone()
    if not role_result:
        print("❌ No hay roles en IT")
        conn.close()
        return False
    
    default_role_id = role_result[0]
    print(f"✅ Usando rol por defecto (ID={default_role_id})")
    
    # Migrar
    print("\n2️⃣ Migrando empleados...")
    c.execute("SELECT id, employee_number, name, registration_date, face_identity_id, email, phone, shift, status, notes FROM employees_old")
    old_employees = c.fetchall()
    
    migrated = 0
    for emp_id, emp_number, emp_name, reg_date, face_id, email, phone, shift, status, notes in old_employees:
        c.execute("""
            INSERT INTO employees (
                id, employee_number, name, department_id, role_id, location_id,
                registration_date, face_identity_id, email, phone, shift, status, notes
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
        """, (emp_id, emp_number, emp_name, it_dept_id, default_role_id, 
              reg_date, face_id, email, phone, shift, status, notes))
        migrated += 1
        print(f"  ✓ {emp_number}")
    
    conn.commit()
    print(f"\n✅ {migrated} empleados migrados")
    
    # Eliminar tabla antigua
    print("\n3️⃣ Limpiando...")
    c.execute("DROP TABLE employees_old")
    conn.commit()
    print("  ✓ Tabla antigua eliminada")
    
    print("\n✅ Migración completada")
    conn.close()
    return True

if __name__ == "__main__":
    success = complete_migration_v2()
    exit(0 if success else 1)
