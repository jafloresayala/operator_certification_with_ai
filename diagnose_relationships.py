"""
Diagnóstico profundo: Verificar integridad de relaciones entre:
- employees -> face_identities -> identity_samples
"""
import sqlite3
import json
import numpy as np
from settings import SETTINGS

def diagnosis_relationships():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    print("\n" + "="*80)
    print("VERIFICACIÓN 1: Relación employees -> face_identities")
    print("="*80)
    
    c.execute("""
        SELECT 
            e.id as emp_id,
            e.employee_number,
            e.name,
            e.face_identity_id,
            COUNT(fi.id) as identity_count,
            COUNT(idsamps.id) as sample_count
        FROM employees e
        LEFT JOIN face_identities fi ON e.face_identity_id = fi.id
        LEFT JOIN identity_samples idsamps ON fi.id = idsamps.identity_id
        GROUP BY e.id
        ORDER BY e.employee_number
    """)
    
    rows = c.fetchall()
    for row in rows:
        print(f"\nEmployee: {row['employee_number']} ({row['name']})")
        print(f"  ID: {row['emp_id']}")
        print(f"  Face Identity ID: {row['face_identity_id']}")
        print(f"  Identities linked: {row['identity_count']}")
        print(f"  Samples in identity: {row['sample_count']}")
        
        if row['identity_count'] is None or row['identity_count'] == 0:
            print(f"  ❌ ERROR: No identity found!")
        elif row['identity_count'] > 1:
            print(f"  ⚠️  WARNING: Multiple identities! (Should be 1)")
    
    # Verificar si identities están asociadas a MÚLTIPLES empleados
    print("\n" + "="*80)
    print("VERIFICACIÓN 2: ¿Hay face_identities compartidas entre empleados?")
    print("="*80)
    
    c.execute("""
        SELECT 
            fi.id as identity_id,
            COUNT(e.id) as emp_count,
            GROUP_CONCAT(e.employee_number, ', ') as employee_numbers,
            GROUP_CONCAT(e.name, ', ') as employee_names
        FROM face_identities fi
        LEFT JOIN employees e ON fi.id = e.face_identity_id
        GROUP BY fi.id
        HAVING COUNT(e.id) > 1 OR COUNT(e.id) = 0
    """)
    
    rows = c.fetchall()
    if rows:
        print("\n⚠️  PROBLEMAS ENCONTRADOS:")
        for row in rows:
            print(f"\n  Identity ID: {row['identity_id']}")
            if row['emp_count'] == 0:
                print(f"    ❌ No employee linked (orphaned identity)")
            else:
                print(f"    ❌ {row['emp_count']} employees linked (data corruption):")
                print(f"       Numbers: {row['employee_numbers']}")
                print(f"       Names: {row['employee_names']}")
    else:
        print("✅ No shared identities detected")
    
    # Verificar si samples están en la identity CORRECTA
    print("\n" + "="*80)
    print("VERIFICACIÓN 3: ¿identity_samples tienen employee_id correcto?")
    print("="*80)
    
    c.execute("""
        SELECT 
            idsamps.id as sample_id,
            idsamps.identity_id,
            idsamps.employee_id,
            e.employee_number,
            fi.id as fi_id,
            (SELECT COUNT(*) FROM employees WHERE id = idsamps.employee_id) as emp_exists
        FROM identity_samples idsamps
        LEFT JOIN employees e ON idsamps.employee_id = e.id
        LEFT JOIN face_identities fi ON idsamps.identity_id = fi.id
        ORDER BY idsamps.id
    """)
    
    rows = c.fetchall()
    errors = []
    for row in rows:
        # Verify that this sample's employee is in the correct identity
        c.execute("""
            SELECT face_identity_id FROM employees WHERE id = ?
        """, (row['employee_id'],))
        
        emp_identity = c.fetchone()
        if emp_identity and emp_identity['face_identity_id'] != row['identity_id']:
            errors.append(f"Sample {row['sample_id']}: employee {row['employee_number']} " +
                         f"should use identity {emp_identity['face_identity_id']}, " +
                         f"but uses {row['identity_id']}")
    
    if errors:
        print("\n❌ INCONSISTENCIAS EN identity_samples:")
        for err in errors:
            print(f"  - {err}")
    else:
        print("✅ All samples linked to correct identity")
    
    # Descargar embeddings directamente
    print("\n" + "="*80)
    print("VERIFICACIÓN 4: Verificar que embeddings reales estén donde deben")
    print("="*80)
    
    c.execute("""
        SELECT 
            idsamps.id,
            idsamps.employee_id,
            e.employee_number,
            e.name,
            idsamps.identity_id,
            LENGTH(idsamps.embedding_json) as embedding_size
        FROM identity_samples idsamps
        JOIN employees e ON idsamps.employee_id = e.id
        ORDER BY idsamps.employee_id, idsamps.id
    """)
    
    for row in c.fetchall():
        try:
            c.execute("SELECT embedding_json FROM identity_samples WHERE id = ?", (row['id'],))
            embedding_row = c.fetchone()
            emb = json.loads(embedding_row['embedding_json'])
            emb_array = np.array(emb, dtype=np.float32)
            
            print(f"\nSample {row['id']}: emp {row['employee_number']} " +
                  f"(emp_id={row['employee_id']}, identity_id={row['identity_id']})")
            print(f"  Embedding shape: {emb_array.shape}, values range: [{emb_array.min():.4f}, {emb_array.max():.4f}]")
            
            if emb_array.shape[0] != 512:
                print(f"  ❌ ERROR: Expected 512 dims, got {emb_array.shape[0]}")
        except Exception as e:
            print(f"  ❌ ERROR parsing embedding: {e}")
    
    conn.close()

if __name__ == "__main__":
    print("🔍 Diagnóstico profundo de integridad de datos...")
    diagnosis_relationships()
    print("\n✅ Diagnóstico completado\n")
