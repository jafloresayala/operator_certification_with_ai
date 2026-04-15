import os
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd

from settings import SETTINGS

EXTRA_EMPLOYEE_FIELDS = [
    ("email", "TEXT"),
    ("phone", "TEXT"),
    ("location", "TEXT"),
    ("shift", "TEXT"),
    ("status", "TEXT"),
    ("notes", "TEXT"),
]

def get_db_connection():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(department_id) REFERENCES departments(id),
            UNIQUE(name, department_id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            location_id INTEGER,
            registration_date TEXT NOT NULL,
            face_identity_id INTEGER,
            FOREIGN KEY(department_id) REFERENCES departments(id),
            FOREIGN KEY(role_id) REFERENCES roles(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
        """
    )

    existing = get_employee_columns(conn)
    for col_name, col_type in EXTRA_EMPLOYEE_FIELDS:
        if col_name not in existing and col_name not in ["location"]:  # location es FK ahora
            c.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS face_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_embedding_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS identity_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            sample_tag TEXT,
            glasses INTEGER DEFAULT 0,
            lighting_tag TEXT,
            pose_tag TEXT,
            quality_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(identity_id) REFERENCES face_identities(id),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS face_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            identity_sample_id INTEGER,
            reference_image_path TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id),
            FOREIGN KEY(identity_sample_id) REFERENCES identity_samples(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            identity_id INTEGER,
            distance REAL,
            threshold_used REAL,
            matched INTEGER NOT NULL,
            quality_json TEXT,
            liveness_json TEXT,
            source TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS threshold_calibrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            threshold REAL NOT NULL,
            target_far REAL NOT NULL,
            far_observed REAL,
            fnr_observed REAL,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()
    
    # Crear admin por defecto si la tabla está vacía
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM admins")
    if c.fetchone()[0] == 0:
        import hashlib
        default_password = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute(
            "INSERT INTO admins (username, password_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
            ("admin", default_password, "Administrador", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    
    # Inicializar datos por defecto (departamentos, roles, ubicaciones)
    init_default_data(conn)
    
    conn.close()

def get_employee_columns(conn):
    c = conn.cursor()
    c.execute("PRAGMA table_info(employees)")
    return [row[1] for row in c.fetchall()]

def create_identity(conn, canonical_embedding: Optional[np.ndarray] = None) -> int:
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO face_identities (canonical_embedding_json, created_at)
        VALUES (?, ?)
        """,
        (
            json.dumps(canonical_embedding.tolist()) if canonical_embedding is not None else None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    return c.lastrowid

def create_employee(conn, employee_data: Dict[str, Any], identity_id: int) -> int:
    data = dict(employee_data)
    data["registration_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["face_identity_id"] = identity_id

    columns = list(data.keys())
    placeholders = ", ".join(["?"] * len(columns))
    values = tuple(data[col] for col in columns)

    c = conn.cursor()
    c.execute(
        f"INSERT INTO employees ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return c.lastrowid

def add_identity_sample(
    conn,
    identity_id: int,
    employee_id: int,
    embedding: np.ndarray,
    quality: dict,
    image_path: str,
    sample_tag: str = "",
    glasses: bool = False,
    lighting_tag: str = "",
    pose_tag: str = "",
) -> int:
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO identity_samples (
            identity_id, employee_id, embedding_json, sample_tag, glasses,
            lighting_tag, pose_tag, quality_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identity_id,
            employee_id,
            json.dumps(embedding.tolist()),
            sample_tag,
            1 if glasses else 0,
            lighting_tag,
            pose_tag,
            json.dumps(quality),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    sample_id = c.lastrowid

    c.execute(
        """
        INSERT INTO face_references (
            employee_id, identity_sample_id, reference_image_path, created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            employee_id,
            sample_id,
            image_path,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    return sample_id

def get_employee_by_number(conn, employee_number: str):
    c = conn.cursor()
    c.execute("SELECT * FROM employees WHERE employee_number = ?", (employee_number,))
    return c.fetchone()

def get_employee_samples(conn, employee_id: int, identity_id: Optional[int] = None) -> List[np.ndarray]:
    """
    Obtiene los embeddings de un empleado.
    
    Args:
        conn: Conexión a BD
        employee_id: ID del empleado
        identity_id: ID de la identidad específica (IMPORTANTE para evitar samples corruptos).
                    Si se proporciona, solo retorna embeddings de esa identidad.
                    Si NO se proporciona, retorna todos los embeddings del empleado (puede haber corrupción).
    
    Returns:
        Lista de embeddings (numpy arrays)
    """
    c = conn.cursor()
    
    if identity_id is not None:
        # RECOMENDADO: Filtrar por identity_id específicA (más seguro)
        c.execute(
            """
            SELECT embedding_json
            FROM identity_samples
            WHERE employee_id = ? AND identity_id = ?
            ORDER BY id DESC
            """,
            (employee_id, identity_id),
        )
    else:
        # Fallback: Filtrar solo por employee_id (puede retornar samples de identities incorrectas)
        c.execute(
            """
            SELECT embedding_json
            FROM identity_samples
            WHERE employee_id = ?
            ORDER BY id DESC
            """,
            (employee_id,),
        )
    
    rows = c.fetchall()
    embeddings = []
    for row in rows:
        try:
            embeddings.append(np.array(json.loads(row["embedding_json"]), dtype=np.float32))
        except Exception:
            continue
    return embeddings


def get_all_enrolled_identities(conn) -> List[Dict[str, Any]]:
    """
    Retorna una lista con todos los empleados enrolados y sus embeddings agrupados.
    Cada elemento: {employee_id, employee_number, name, identity_id, embeddings: [np.array]}
    """
    c = conn.cursor()
    c.execute(
        """
        SELECT e.id AS employee_id, e.employee_number, e.name, e.face_identity_id,
               s.embedding_json
        FROM employees e
        JOIN identity_samples s ON s.employee_id = e.id AND s.identity_id = e.face_identity_id
        WHERE e.face_identity_id IS NOT NULL
        ORDER BY e.id
        """
    )
    rows = c.fetchall()

    grouped: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        eid = row["employee_id"]
        if eid not in grouped:
            grouped[eid] = {
                "employee_id": eid,
                "employee_number": row["employee_number"],
                "name": row["name"],
                "identity_id": row["face_identity_id"],
                "embeddings": [],
            }
        try:
            grouped[eid]["embeddings"].append(
                np.array(json.loads(row["embedding_json"]), dtype=np.float32)
            )
        except Exception:
            continue

    return list(grouped.values())


def list_employees_df() -> pd.DataFrame:
    conn = get_db_connection()
    query = """
        SELECT 
            e.id, 
            e.employee_number, 
            e.name, 
            d.name as department, 
            r.name as role,
            l.name as location,
            e.registration_date,
            e.email,
            e.phone,
            e.shift,
            e.status
        FROM employees e
        LEFT JOIN departments d ON e.department_id = d.id
        LEFT JOIN roles r ON e.role_id = r.id
        LEFT JOIN locations l ON e.location_id = l.id
        ORDER BY e.id DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def log_verification(
    conn,
    employee_id: Optional[int],
    identity_id: Optional[int],
    distance: Optional[float],
    threshold_used: float,
    matched: bool,
    quality_json: dict,
    liveness_json: dict,
    source: str,
):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO verification_logs (
            employee_id, identity_id, distance, threshold_used, matched,
            quality_json, liveness_json, source, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            employee_id,
            identity_id,
            distance,
            threshold_used,
            1 if matched else 0,
            json.dumps(quality_json),
            json.dumps(liveness_json),
            source,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()


def verify_admin_credentials(username: str, password: str) -> bool:
    """Verifica si las credenciales del admin son correctas."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("SELECT id FROM admins WHERE username = ? AND password_hash = ?", (username, password_hash))
        result = c.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False


def get_all_employees_for_edit(conn) -> pd.DataFrame:
    """Obtiene todos los empleados para edición con nombres de department, role, location."""
    query = """
        SELECT 
            e.id, 
            e.employee_number, 
            e.name, 
            e.department_id,
            d.name as department, 
            e.role_id,
            r.name as role,
            e.location_id,
            l.name as location,
            e.registration_date,
            e.email,
            e.phone,
            e.shift,
            e.status,
            e.notes,
            e.face_identity_id
        FROM employees e
        LEFT JOIN departments d ON e.department_id = d.id
        LEFT JOIN roles r ON e.role_id = r.id
        LEFT JOIN locations l ON e.location_id = l.id
        ORDER BY e.id DESC
    """
    return pd.read_sql_query(query, conn)


def update_employee(conn, employee_id: int, employee_data: Dict[str, Any]) -> bool:
    """Actualiza los datos de un empleado.
    
    employee_data puede contener:
    - Nombres de department/role/location (se convierten a IDs automáticamente)
    - O directamente department_id/role_id/location_id
    """
    try:
        c = conn.cursor()
        
        # Convertir nombres a IDs si es necesario
        data_to_update = employee_data.copy()
        
        if "department" in data_to_update and "department_id" not in data_to_update:
            dept_name = data_to_update.pop("department")
            if dept_name:
                c.execute("SELECT id FROM departments WHERE name = ?", (dept_name,))
                row = c.fetchone()
                if row:
                    data_to_update["department_id"] = row[0]
        
        if "role" in data_to_update and "role_id" not in data_to_update:
            role_name = data_to_update.pop("role")
            if role_name:
                c.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                row = c.fetchone()
                if row:
                    data_to_update["role_id"] = row[0]
        
        if "location" in data_to_update and "location_id" not in data_to_update:
            loc_name = data_to_update.pop("location")
            if loc_name:
                c.execute("SELECT id FROM locations WHERE name = ?", (loc_name,))
                row = c.fetchone()
                if row:
                    data_to_update["location_id"] = row[0]
        
        # Construir dinámicamente el UPDATE
        columns_to_update = []
        values = []
        for key, value in data_to_update.items():
            if key not in ["id", "registration_date", "face_identity_id"]:
                columns_to_update.append(f"{key} = ?")
                values.append(value)
        
        if not columns_to_update:
            return False
        
        values.append(employee_id)
        query = f"UPDATE employees SET {', '.join(columns_to_update)} WHERE id = ?"
        c.execute(query, values)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error actualizando empleado: {e}")
        return False


def delete_employee(conn, employee_id: int) -> bool:
    """
    Elimina un empleado y TODOS sus datos relacionados de forma exhaustiva.
    - Imágenes del disco (reference_images/)
    - face_references (referencias de imágenes)
    - identity_samples (muestras biométricas)
    - face_identities (identidades)
    - verification_logs (logs de verificación)
    - employees (empleado)
    """
    try:
        c = conn.cursor()
        
        # PASO 1: Obtener TODOS los identity_ids asociados a este empleado
        c.execute(
            "SELECT DISTINCT identity_id FROM identity_samples WHERE employee_id = ?",
            (employee_id,)
        )
        identity_ids = [row[0] for row in c.fetchall()]
        print(f"Identidades a eliminar para empleado {employee_id}: {identity_ids}")
        
        # PASO 2: Obtener y eliminar TODOS los archivos de imagen del disco
        c.execute(
            "SELECT DISTINCT reference_image_path FROM face_references WHERE employee_id = ?",
            (employee_id,)
        )
        image_paths = [row[0] for row in c.fetchall()]
        deleted_count = 0
        for image_path in image_paths:
            try:
                if image_path and os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_count += 1
                    print(f"✓ Imagen eliminada: {image_path}")
            except Exception as e:
                print(f"⚠ Error al eliminar imagen {image_path}: {e}")
        print(f"Total de imágenes eliminadas: {deleted_count}")
        
        # PASO 3: Eliminar face_references (depende de identity_samples)
        c.execute("DELETE FROM face_references WHERE employee_id = ?", (employee_id,))
        ref_count = c.rowcount
        print(f"✓ Registros eliminados de face_references: {ref_count}")
        
        # PASO 4: Eliminar identity_samples (depende de identity_id)
        c.execute("DELETE FROM identity_samples WHERE employee_id = ?", (employee_id,))
        samples_count = c.rowcount
        print(f"✓ Registros eliminados de identity_samples: {samples_count}")
        
        # PASO 5: Eliminar face_identities (por cada identity_id encontrado)
        for identity_id in identity_ids:
            c.execute("DELETE FROM face_identities WHERE id = ?", (identity_id,))
            id_count = c.rowcount
            if id_count > 0:
                print(f"✓ Identidad {identity_id} eliminada")
        
        # PASO 6: Eliminar verification_logs
        c.execute("DELETE FROM verification_logs WHERE employee_id = ?", (employee_id,))
        logs_count = c.rowcount
        print(f"✓ Registros eliminados de verification_logs: {logs_count}")
        
        # PASO 7: Eliminar employees (al último, porque tiene FOREIGN KEYs)
        c.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        emp_count = c.rowcount
        if emp_count > 0:
            print(f"✓ Empleado {employee_id} eliminado")
        
        # PASO 8: Commit final para guardar todos los cambios
        conn.commit()
        print(f"✅ Eliminación completada exitosamente para empleado {employee_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error eliminando empleado {employee_id}: {e}")
        conn.rollback()  # Revertir cambios en caso de error
        return False


# ═══════════════════════════════════════════════════════════════════════════════════
# CRUD PARA DEPARTMENTS
# ═══════════════════════════════════════════════════════════════════════════════════

def get_all_departments(conn) -> List[Dict[str, Any]]:
    """Obtiene todos los departamentos."""
    c = conn.cursor()
    c.execute("SELECT id, name FROM departments ORDER BY name")
    return [{"id": row[0], "name": row[1]} for row in c.fetchall()]

def add_department(conn, name: str) -> bool:
    """Agrega un nuevo departamento."""
    try:
        c = conn.cursor()
        c.execute("INSERT INTO departments (name, created_at) VALUES (?, ?)", 
                  (name.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        print(f"Error: Departamento '{name}' ya existe")
        return False
    except Exception as e:
        print(f"Error al agregar departamento: {e}")
        return False

def update_department(conn, department_id: int, new_name: str) -> bool:
    """Actualiza el nombre de un departamento."""
    try:
        c = conn.cursor()
        c.execute("UPDATE departments SET name = ? WHERE id = ?", (new_name.strip(), department_id))
        conn.commit()
        return c.rowcount > 0
    except sqlite3.IntegrityError:
        print(f"Error: Departamento '{new_name}' ya existe")
        return False
    except Exception as e:
        print(f"Error al actualizar departamento: {e}")
        return False

def delete_department(conn, department_id: int) -> bool:
    """Elimina un departamento (solo si no tiene roles asociados)."""
    try:
        c = conn.cursor()
        
        # Verificar si hay roles asociados
        c.execute("SELECT COUNT(*) FROM roles WHERE department_id = ?", (department_id,))
        if c.fetchone()[0] > 0:
            print("Error: No se puede eliminar un departamento que tiene roles asociados")
            return False
        
        c.execute("DELETE FROM departments WHERE id = ?", (department_id,))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"Error al eliminar departamento: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════════
# CRUD PARA ROLES
# ═══════════════════════════════════════════════════════════════════════════════════

def get_roles_by_department(conn, department_id: int) -> List[Dict[str, Any]]:
    """Obtiene todos los roles de un departamento."""
    c = conn.cursor()
    c.execute("SELECT id, name FROM roles WHERE department_id = ? ORDER BY name", (department_id,))
    return [{"id": row[0], "name": row[1]} for row in c.fetchall()]

def get_all_roles_with_dept(conn) -> List[Dict[str, Any]]:
    """Obtiene todos los roles con su departamento."""
    c = conn.cursor()
    c.execute("""
        SELECT r.id, r.name, r.department_id, d.name as department_name 
        FROM roles r 
        JOIN departments d ON r.department_id = d.id 
        ORDER BY d.name, r.name
    """)
    return [{"id": row[0], "name": row[1], "department_id": row[2], "department_name": row[3]} 
            for row in c.fetchall()]

def add_role(conn, name: str, department_id: int) -> bool:
    """Agrega un nuevo rol a un departamento."""
    try:
        c = conn.cursor()
        c.execute("INSERT INTO roles (name, department_id, created_at) VALUES (?, ?, ?)",
                  (name.strip(), department_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        print(f"Error: Rol '{name}' ya existe en este departamento")
        return False
    except Exception as e:
        print(f"Error al agregar rol: {e}")
        return False

def update_role(conn, role_id: int, new_name: str, department_id: int) -> bool:
    """Actualiza un rol."""
    try:
        c = conn.cursor()
        c.execute("UPDATE roles SET name = ?, department_id = ? WHERE id = ?",
                  (new_name.strip(), department_id, role_id))
        conn.commit()
        return c.rowcount > 0
    except sqlite3.IntegrityError:
        print(f"Error: Rol '{new_name}' ya existe en este departamento")
        return False
    except Exception as e:
        print(f"Error al actualizar rol: {e}")
        return False

def delete_role(conn, role_id: int) -> bool:
    """Elimina un rol (solo si no hay empleados asociados)."""
    try:
        c = conn.cursor()
        
        # Verificar si hay empleados asociados
        c.execute("SELECT COUNT(*) FROM employees WHERE role_id = ?", (role_id,))
        if c.fetchone()[0] > 0:
            print("Error: No se puede eliminar un rol que tiene empleados asociados")
            return False
        
        c.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"Error al eliminar rol: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════════
# CRUD PARA LOCATIONS
# ═══════════════════════════════════════════════════════════════════════════════════

def get_all_locations(conn) -> List[Dict[str, Any]]:
    """Obtiene todas las ubicaciones."""
    c = conn.cursor()
    c.execute("SELECT id, name FROM locations ORDER BY name")
    return [{"id": row[0], "name": row[1]} for row in c.fetchall()]

def add_location(conn, name: str) -> bool:
    """Agrega una nueva ubicación."""
    try:
        c = conn.cursor()
        c.execute("INSERT INTO locations (name, created_at) VALUES (?, ?)",
                  (name.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        print(f"Error: Ubicación '{name}' ya existe")
        return False
    except Exception as e:
        print(f"Error al agregar ubicación: {e}")
        return False

def update_location(conn, location_id: int, new_name: str) -> bool:
    """Actualiza una ubicación."""
    try:
        c = conn.cursor()
        c.execute("UPDATE locations SET name = ? WHERE id = ?", (new_name.strip(), location_id))
        conn.commit()
        return c.rowcount > 0
    except sqlite3.IntegrityError:
        print(f"Error: Ubicación '{new_name}' ya existe")
        return False
    except Exception as e:
        print(f"Error al actualizar ubicación: {e}")
        return False

def delete_location(conn, location_id: int) -> bool:
    """Elimina una ubicación (solo si no hay empleados asociados)."""
    try:
        c = conn.cursor()
        
        # Verificar si hay empleados asociados
        c.execute("SELECT COUNT(*) FROM employees WHERE location_id = ?", (location_id,))
        if c.fetchone()[0] > 0:
            print("Error: No se puede eliminar una ubicación que tiene empleados asociados")
            return False
        
        c.execute("DELETE FROM locations WHERE id = ?", (location_id,))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"Error al eliminar ubicación: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN DE DATOS POR DEFECTO
# ═══════════════════════════════════════════════════════════════════════════════════

def init_default_data(conn):
    """Inicializa los datos por defecto (departments, roles, locations) si están vacíos."""
    c = conn.cursor()
    
    # Verificar suma de registros
    c.execute("SELECT COUNT(*) FROM departments")
    if c.fetchone()[0] > 0:
        return  # Ya hay datos
    
    # Datos por defecto
    default_departments = ["TI", "Ventas", "RRHH", "Finanzas", "Logistica", "Calidad", "Manufactura"]
    
    department_roles = {
        "TI": ["Gerente", "Supervisor", "Desarrollador", "Cientifico de Datos", "Analista de Datos"],
        "Ventas": ["Gerente", "Supervisor", "Vendedor", "Asesor"],
        "RRHH": ["Gerente", "Especialista", "Coordinador"],
        "Finanzas": ["Gerente", "Contador", "Analista"],
        "Logistica": ["Gerente", "Supervisor", "Coordinador"],
        "Calidad": ["Gerente", "Inspector", "Auditor"],
        "Manufactura": ["Gerente", "Supervisor", "Operario", "Técnico"],
    }
    
    default_locations = ["Oficina Principal", "Sucursal Norte", "Sucursal Sur", "Centro de Distribución", "Remoto"]
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Insertar departamentos
    for dept in default_departments:
        c.execute("INSERT OR IGNORE INTO departments (name, created_at) VALUES (?, ?)", (dept, now))
    conn.commit()
    
    # Insertar roles
    for dept in default_departments:
        c.execute("SELECT id FROM departments WHERE name = ?", (dept,))
        dept_id = c.fetchone()[0]
        roles = department_roles.get(dept, ["Interno"])
        for role in roles:
            c.execute("INSERT OR IGNORE INTO roles (name, department_id, created_at) VALUES (?, ?, ?)",
                      (role, dept_id, now))
    conn.commit()
    
    # Insertar locations
    for location in default_locations:
        c.execute("INSERT OR IGNORE INTO locations (name, created_at) VALUES (?, ?)", (location, now))
    conn.commit()