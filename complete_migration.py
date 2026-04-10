#!/usr/bin/env python
"""
Script de migración corregido: Completa la migración de employees_old a employees.
"""

import sqlite3
import os

def complete_migration():
    """Completa la migración de la BD antigua a la nueva estructura."""
    
    db_path = "data/database.db"
    
    if not os.path.exists(db_path):
        print("❌ No se encontró database.db")
        return False
    
    print("🔄 Completando migración...")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # Verificar si employees_old existe
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='employees_old'")
        if not c.fetchone():
            print("✅ employees_old no existe, BD ya está migrada")
            conn.close()
            return True
        
        # Leer datos de employees_old
        print("\n1️⃣ Leyendo datos de employees_old...")
        c.execute("""
            SELECT id, employee_number, name, department, role, registration_date, 
                   face_identity_id, email, phone, location, shift, status, notes 
            FROM employees_old
        """)
        old_employees = c.fetchall()
        print(f"  ✓ {len(old_employees)} empleados encontrados")
        
        if len(old_employees) == 0:
            print("\n2️⃣ No hay empleados para migrar, eliminando tabla antigua...")
            c.execute("DROP TABLE employees_old")
            conn.commit()
            print("✅ Migración completada (sin datos)")
            conn.close()
            return True
        
        # Migrar datos
        print("\n2️⃣ Migrando datos...")
        migrated_count = 0
        skipped_count = 0
        
        for emp in old_employees:
            emp_id, emp_number, emp_name, dept_text, role_text, reg_date, face_id, email, phone, location, shift, status, notes = emp
            
            try:
                # Obtener department_id
                c.execute("SELECT id FROM departments WHERE name = ?", (dept_text,))
                dept_row = c.fetchone()
                if not dept_row:
                    print(f"  ⚠️ {emp_number}: Departamento '{dept_text}' no existe")
                    skipped_count += 1
                    continue
                dept_id = dept_row[0]
                
                # Obtener role_id
                c.execute("SELECT id FROM roles WHERE name = ? AND department_id = ?", (role_text, dept_id))
                role_row = c.fetchone()
                if not role_row:
                    print(f"  ⚠️ {emp_number}: Rol '{role_text}' no existe en {dept_text}")
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
                print(f"  ✓ {emp_number} migrado")
                
            except Exception as e:
                print(f"  ❌ Error migrando {emp_number}: {e}")
                skipped_count += 1
        
        conn.commit()
        print(f"\n✅ {migrated_count} empleados migrados exitosamente")
        if skipped_count > 0:
            print(f"⚠️ {skipped_count} empleados saltados")
        
        # Eliminar tabla antigua
        print("\n3️⃣ Limpiando...")
        c.execute("DROP TABLE employees_old")
        conn.commit()
        print("  ✓ Tabla antigua eliminada")
        
        print("\n✅ Migración completada exitosamente")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        conn.close()
    
    return True

if __name__ == "__main__":
    success = complete_migration()
    exit(0 if success else 1)
