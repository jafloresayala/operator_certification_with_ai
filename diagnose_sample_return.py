"""
Diagnóstico CRÍTICO: ¿Se está usando la IDENTITY CORRECTA para verificación?
"""
import sqlite3
import json
import numpy as np
from settings import SETTINGS

def check_how_samples_returned():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    print("\n" + "="*80)
    print("SIMULACIÓN: ¿QUÉ EMBEDDINGS SE RETORNAN EN VERIFICACIÓN?")
    print("="*80)
    
    # Para cada empleado, simular lo que hace verify_employee_one_to_one
    c.execute("SELECT id, employee_number, name FROM employees ORDER BY id")
    employees = c.fetchall()
    
    for emp in employees:
        emp_id = emp['id']
        emp_number = emp['employee_number']
        emp_name = emp['name']
        
        # Obtener el employee correctamente (como hace verify_one_to_one)
        c.execute("SELECT * FROM employees WHERE id = ?", (emp_id,))
        emp_row = c.fetchone()
        
        if emp_row is None:
            print(f"\n❌ {emp_number}: Employee not found!")
            continue
        
        face_identity_id = emp_row['face_identity_id']
        
        # Ahora simular get_employee_samples (filtra solo por employee_id)
        c.execute("""
            SELECT id, identity_id, embedding_json FROM identity_samples 
            WHERE employee_id = ?
        """, (emp_id,))
        
        samples = c.fetchall()
        
        print(f"\n{emp_number} ({emp_name}) [ID={emp_id}]:")
        print(f"  Expected face_identity_id: {face_identity_id}")
        print(f"  Total samples returned: {len(samples)}")
        
        # Agrupar por identity_id
        identity_groups = {}
        for sample in samples:
            iid = sample['identity_id']
            if iid not in identity_groups:
                identity_groups[iid] = []
            identity_groups[iid].append(sample['id'])
        
        for iid, sample_ids in sorted(identity_groups.items()):
            status = "✅ CORRECT" if iid == face_identity_id else f"❌ WRONG (should be {face_identity_id})"
            print(f"    Identity {iid}: {len(sample_ids)} samples {status}")
            print(f"      Sample IDs: {sample_ids}")
    
    # PRUEBA CRÍTICA: ¿Hay duplicates en samples?
    print("\n" + "="*80)
    print("PRUEBA CRÍTICA: Verificar identity_samples por identity_id")
    print("="*80)
    
    c.execute("""
        SELECT identity_id, COUNT(*) as count FROM identity_samples
        GROUP BY identity_id
        ORDER BY count DESC
    """)
    
    for row in c.fetchall():
        # Obtener q ué employee debería tener esta identity
        c.execute("""
            SELECT e.employee_number, e.name FROM employees e
            WHERE e.face_identity_id = ?
        """, (row['identity_id'],))
        
        emp_for_identity = c.fetchone()
        emp_text = f"{emp_for_identity['employee_number']} ({emp_for_identity['name']})" if emp_for_identity else "ORPHANED"
        
        print(f"\nIdentity {row['identity_id']}: {row['count']} samples (belongs to {emp_text})")
    
    conn.close()

if __name__ == "__main__":
    print("🔍 Verificando cómo se RETORNAN los samples para verificación...")
    check_how_samples_returned()
    print("\n✅ Diagnóstico completado\n")
