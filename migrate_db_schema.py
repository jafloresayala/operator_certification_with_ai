#!/usr/bin/env python
"""
Script de migración: Convierte la estructura antigua de employees (con TEXT para department/role)
a la nueva estructura con FOREIGN KEYs a las tablas departments y roles.

Ejecutar: python migrate_db_schema.py
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

def migrate_db_schema():
    """Migra la BD antigua a la nueva estructura con departamentos y roles como tablas."""
    
    db_path = "data/database.db"
    
    if not os.path.exists(db_path):
        print("❌ No se encontró database.db")
        return
    
    print("🔄 Iniciando migración de esquema...")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # Paso 1: Crear tabla temporal employees_old
        print("1️⃣ Creando backup de employees...")
        c.execute("ALTER TABLE employees RENAME TO employees_old")
        conn.commit()
        
        # Paso 2: Leer datos antiguos
        c.execute("""
            SELECT id, employee_number, name, department, role, registration_date, 
                   face_identity_id, email, phone, location, shift, status, notes 
            FROM employees_old
        """)
        old_employees = c.fetchall()
        print(f"  ✓ {len(old_employees)} empleados leídos")
        
        # Paso 3: Recrear tabla employees con FKs nuevos
        print("\n2️⃣ Recreando tabla employees con estructura nueva...")
        c.execute("""
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_number TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                department_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                location_id INTEGER,
                registration_date TEXT NOT NULL,
                face_identity_id INTEGER,
                email TEXT,
                phone TEXT,
                shift TEXT,
                status TEXT,
                notes TEXT,
                FOREIGN KEY(department_id) REFERENCES departments(id),
                FOREIGN KEY(role_id) REFERENCES roles(id),
                FOREIGN KEY(location_id) REFERENCES locations(id)
            )
        """)
        conn.commit()
        print("  ✓ Tabla recreada")
        
        # Paso 4: Migrar datos
        print("\n3️⃣ Migrando datos...")
        migrated_count = 0
        skipped_count = 0
        
        for emp in old_employees:
            emp_id, emp_number, emp_name, dept_text, role_text, reg_date, face_id, email, phone, location, shift, status, notes = emp
            
            # Obtener department_id
            c.execute("SELECT id FROM departments WHERE name = ?", (dept_text,))
            dept_row = c.fetchone()
            if not dept_row:
                print(f"  ⚠️ Empleado {emp_number}: Departamento '{dept_text}' no encontrado (skipped)")
                skipped_count += 1
                continue
            dept_id = dept_row[0]
            
            # Obtener role_id
            c.execute("SELECT id FROM roles WHERE name = ? AND department_id = ?", (role_text, dept_id))
            role_row = c.fetchone()
            if not role_row:
                print(f"  ⚠️ Empleado {emp_number}: Rol '{role_text}' no encontrado en {dept_text} (skipped)")
                skipped_count += 1
                continue
            role_id = role_row[0]
            
            # Obtener location_id (si existe)
            location_id = None
            if location:
                c.execute("SELECT id FROM locations WHERE name = ?", (location,))
                loc_row = c.fetchone()
                if loc_row:
                    location_id = loc_row[0]
            
            # Insertar con nuevos IDs
            c.execute("""
                INSERT INTO employees (
                    id, employee_number, name, department_id, role_id, location_id,
                    registration_date, face_identity_id, email, phone, shift, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (emp_id, emp_number, emp_name, dept_id, role_id, location_id, 
                  reg_date, face_id, email, phone, shift, status, notes))
            
            migrated_count += 1
        
        conn.commit()
        print(f"  ✓ {migrated_count} empleados migrados exitosamente")
        if skipped_count > 0:
            print(f"  ⚠️ {skipped_count} empleados saltados (verificar datos)")
        
        # Paso 5: Eliminar tabla antigua
        print("\n4️⃣ Limpiando...")
        c.execute("DROP TABLE employees_old")
        conn.commit()
        print("  ✓ Tabla antigua elimina")
        
        print("\n✅ Migración completada exitosamente")
        
    except Exception as e:
        print(f"\n❌ Error durante migración: {e}")
        print("   Revirtiendo cambios...")
        try:
            c.execute("ALTER TABLE employees_old RENAME TO employees")
            conn.commit()
            print("   ✓ BD revertida")
        except:
            pass
        return False
    
    finally:
        conn.close()
    
    return True

if __name__ == "__main__":
    success = migrate_db_schema()
    exit(0 if success else 1)
