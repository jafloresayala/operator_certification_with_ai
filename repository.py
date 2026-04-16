import os
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd

from settings import SETTINGS

# Columnas adicionales que se agregan con ALTER TABLE (para DBs existentes)
EXTRA_EMPLOYEE_FIELDS = [
    ("email", "TEXT"),
    ("phone", "TEXT"),
    ("status", "TEXT"),
    ("notes", "TEXT"),
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

def get_db_connection():
    conn = sqlite3.connect(SETTINGS.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Tablas legacy (departments, roles, locations) se mantienen para no romper
    # la BD existente, pero ya no se usan en código nuevo.

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department_id INTEGER,
            role_id INTEGER,
            location_id INTEGER,
            registration_date TEXT NOT NULL,
            face_identity_id INTEGER
        )
        """
    )

    existing = get_employee_columns(conn)
    for col_name, col_type in EXTRA_EMPLOYEE_FIELDS:
        if col_name not in existing:
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

    # Legacy columns: evitar NOT NULL constraint
    data.setdefault("department_id", 0)
    data.setdefault("role_id", 0)
    data.setdefault("location_id", 0)

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
            e.first_name,
            e.last_name,
            e.cost_center_description,
            e.role_description,
            e.shift_description,
            e.registration_date,
            e.email,
            e.status
        FROM employees e
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
    """Obtiene todos los empleados para edición."""
    query = """
        SELECT 
            e.id, 
            e.employee_number, 
            e.name,
            e.first_name,
            e.last_name,
            e.middle_name,
            e.user_id,
            e.email,
            e.level,
            e.role_code,
            e.role_description,
            e.cost_center_code,
            e.cost_center_description,
            e.shift_code,
            e.shift_description,
            e.supervisor_role,
            e.registration_date,
            e.status,
            e.notes,
            e.face_identity_id
        FROM employees e
        ORDER BY e.id DESC
    """
    return pd.read_sql_query(query, conn)


def update_employee(conn, employee_id: int, employee_data: Dict[str, Any]) -> bool:
    """Actualiza los datos de un empleado."""
    try:
        c = conn.cursor()
        data_to_update = employee_data.copy()
        
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

