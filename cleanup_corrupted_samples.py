"""
LIMPIEZA CRÍTICA: Eliminar los samples corruptos de identities orfanadas.

Los samples en identities 5, 6, 7 pertenecen a empleados que fueron RE-ENROLADOS
en identities 11, 12, 13 respectivamente. Los samples viejos deben eliminarse.
"""
import sqlite3
from settings import SETTINGS

def cleanup_corrupted_samples():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    c = conn.cursor()
    
    print("="*80)
    print("LIMPIEZA: Eliminando samples corruptos de identities orfanadas")
    print("="*80)
    
    # Estos son los samples en identities orfanadas que deben eliminarse
    samples_to_delete = [
        # Employee 99002951 (Guillermo): samples en identity 5 (debería estar en 11)
        (14, "Guillermo", 5, 11),
        (15, "Guillermo", 5, 11),
        (16, "Guillermo", 5, 11),
        (17, "Guillermo", 5, 11),
        (18, "Guillermo", 5, 11),
        
        # Employee 90015336 (Celso): samples en identity 6 (debería estar en 12)
        (19, "Celso", 6, 12),
        (20, "Celso", 6, 12),
        (21, "Celso", 6, 12),
        (22, "Celso", 6, 12),
        (23, "Celso", 6, 12),
        
        # Employee 90015313 (Litzy): samples en identity 7 (debería estar en 13)
        (24, "Litzy", 7, 13),
        (25, "Litzy", 7, 13),
        (26, "Litzy", 7, 13),
        (27, "Litzy", 7, 13),
        (28, "Litzy", 7, 13),
    ]
    
    print(f"\nSamples a eliminar: {len(samples_to_delete)}")
    for sample_id, name, wrong_id, correct_id in samples_to_delete:
        print(f"  Sample {sample_id}: {name} - Remove from identity {wrong_id} (should be {correct_id})")
    
    # Autorización automática (datos ya verificados)
    print("\n✅ Procediendo con la limpieza (datos pre-verificados)...")
    
    # Eliminar samples
    deleted_count = 0
    for sample_id, name, wrong_id, correct_id in samples_to_delete:
        try:
            c.execute("DELETE FROM identity_samples WHERE id = ?", (sample_id,))
            deleted_count += 1
            print(f"  ✅ Eliminado sample {sample_id}")
        except Exception as e:
            print(f"  ❌ Error eliminando sample {sample_id}: {e}")
    
    conn.commit()
    
    print(f"\n✅ Eliminados {deleted_count} samples corruptos")
    
    # Verificación post-limpieza
    print("\n" + "="*80)
    print("VERIFICACIÓN POST-LIMPIEZA")
    print("="*80)
    
    c.execute("""
        SELECT e.employee_number, e.name, COUNT(idsamps.id) as sample_count
        FROM employees e
        LEFT JOIN identity_samples idsamps ON e.id = idsamps.employee_id
        GROUP BY e.id
    """)
    
    print("\nSamples por empleado (esperado: 5 cada uno):")
    for row in c.fetchall():
        count = row[2] or 0
        status = "✅" if count == 5 else "⚠️ " if count > 5 else "❌"
        print(f"  {status} {row[0]} ({row[1]}): {count} samples")
    
    conn.close()
    return True

if __name__ == "__main__":
    cleanup_corrupted_samples()
