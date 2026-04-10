"""
Test suite para verificar las soluciones implementadas.
Ejecutar: python test_fixes.py
"""

import os
import sqlite3
import sys
from pathlib import Path

def test_database_location():
    """Verifica que database.db está en data/ (ubicación segura)"""
    print("\n📍 TEST 1: Database Location")
    print("=" * 50)
    
    # Test: database.db NO debe estar en raíz
    root_db = "database.db"
    if os.path.exists(root_db):
        print(f"❌ FALLÓ: database.db aún existe en raíz")
        print(f"   Ejecuta: python migrate_database.py")
        return False
    else:
        print(f"✓ database.db NO en raíz (correcto)")
    
    # Test: database.db debe estar en data/
    data_dir = "data"
    data_db = os.path.join(data_dir, "database.db")
    if os.path.exists(data_db):
        print(f"✓ database.db está en {data_db} (correcto)")
        return True
    else:
        print(f"❌ FALLÓ: database.db no encontrado en {data_db}")
        return False

def test_database_connection():
    """Verifica que pueda conectarse a la base de datos"""
    print("\n🔌 TEST 2: Database Connection")
    print("=" * 50)
    
    try:
        from settings import SETTINGS
        
        # Verificar que DB_PATH es ruta absoluta
        if SETTINGS.DB_PATH.startswith("data"):
            print(f"✓ DB_PATH usa ruta segura: {SETTINGS.DB_PATH}")
        else:
            print(f"⚠ DB_PATH: {SETTINGS.DB_PATH}")
        
        # Intentar conectar
        conn = sqlite3.connect(SETTINGS.DB_PATH)
        c = conn.cursor()
        
        # Verificar que contiene datos (al menos tabla employees)
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = c.fetchall()
        
        if tables:
            print(f"✓ Conexión exitosa a {SETTINGS.DB_PATH}")
            print(f"✓ Tablas encontradas: {len(tables)}")
            for table in tables:
                c.execute(f"SELECT COUNT(*) FROM {table[0]}")
                count = c.fetchone()[0]
                print(f"  - {table[0]}: {count} registros")
            conn.close()
            return True
        else:
            print(f"❌ FALLÓ: No se encontraron tablas")
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ FALLÓ: Error al conectar a base de datos: {e}")
        return False

def test_delete_function_syntax():
    """Verifica que delete_employee() compila sin errores"""
    print("\n🔧 TEST 3: delete_employee() Syntax")
    print("=" * 50)
    
    try:
        import py_compile
        result = py_compile.compile('repository.py', doraise=True)
        print(f"✓ repository.py compila exitosamente")
        print(f"✓ delete_employee() syntax es válido")
        return True
    except Exception as e:
        print(f"❌ FALLÓ: Error de compilación: {e}")
        return False

def test_no_orphaned_records():
    """Verifica que NO hay registros huérfanos en la BD actual"""
    print("\n🧹 TEST 4: Check for Orphaned Records")
    print("=" * 50)
    
    try:
        from settings import SETTINGS
        conn = sqlite3.connect(SETTINGS.DB_PATH)
        c = conn.cursor()
        
        # Test 1: identity_samples sin employee_id válido
        c.execute("""
            SELECT COUNT(*) FROM identity_samples 
            WHERE employee_id NOT IN (SELECT id FROM employees)
        """)
        orphaned_samples = c.fetchone()[0]
        
        # Test 2: face_references sin employee_id válido
        c.execute("""
            SELECT COUNT(*) FROM face_references 
            WHERE employee_id NOT IN (SELECT id FROM employees)
        """)
        orphaned_refs = c.fetchone()[0]
        
        # Test 3: face_identities sin employee_id válido
        c.execute("""
            SELECT COUNT(*) FROM face_identities 
            WHERE id NOT IN (SELECT face_identity_id FROM employees WHERE face_identity_id IS NOT NULL)
        """)
        orphaned_identities = c.fetchone()[0]
        
        conn.close()
        
        print(f"Registros huérfanos en identity_samples: {orphaned_samples}")
        print(f"Registros huérfanos en face_references: {orphaned_refs}")
        print(f"Registros huérfanos en face_identities: {orphaned_identities}")
        
        if orphaned_samples == 0 and orphaned_refs == 0 and orphaned_identities == 0:
            print(f"✓ No se encontraron registros huérfanos (excelente)")
            return True
        else:
            print(f"⚠ Se encontraron registros huérfanos - considerar ejecutar delete_employee() de nuevo")
            return False
            
    except Exception as e:
        print(f"⚠ No se pueden verificar registros huérfanos: {e}")
        return False

def main():
    """Ejecutar todas las pruebas"""
    print("\n" + "=" * 50)
    print("🧪 FACE RECOGNITION - TEST FIXES")
    print("=" * 50)
    
    tests = [
        ("Database Location", test_database_location),
        ("Database Connection", test_database_connection),
        ("delete_employee() Syntax", test_delete_function_syntax),
        ("Orphaned Records Check", test_no_orphaned_records),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ Excepción no capturada en {name}: {e}")
            results.append((name, False))
    
    # Resumen final
    print("\n" + "=" * 50)
    print("📊 RESUMEN DE PRUEBAS")
    print("=" * 50)
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    print("\n" + "=" * 50)
    if passed_count == total_count:
        print(f"✅ TODAS LAS PRUEBAS PASARON ({total_count}/{total_count})")
        print("Sistema listo para usar")
    else:
        print(f"⚠ {passed_count}/{total_count} pruebas pasaron")
        print("Por favor revisa los errores arriba")
    print("=" * 50 + "\n")
    
    return passed_count == total_count

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
