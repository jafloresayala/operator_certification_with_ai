import io
import os
import time
import cv2
import av
import numpy as np
import pandas as pd
import streamlit as st
import threading
import face_recognition
from typing import List, Optional, Tuple, Dict, Any
from streamlit_webrtc import webrtc_streamer, WebRtcMode, VideoProcessorBase
from PIL import Image

from settings import SETTINGS
from repository import init_db, list_employees_df, get_employee_by_number, get_db_connection as _get_db_conn
from services import enroll_sample_for_employee, verify_employee_one_to_one
from biometric_engine import ArcFaceEngine
from biometric_models import LivenessResult

st.set_page_config(page_title="Sistema Biométrico Facial", layout="wide")


def get_departments(conn) -> List[str]:
    """Carga dinámicamente los departamentos desde la BD."""
    from repository import get_all_departments
    deps = get_all_departments(conn)
    return [d["name"] for d in deps]

def get_roles_for_department(conn, department_id: int) -> List[str]:
    """Obtiene los roles para un departamento específico."""
    from repository import get_roles_by_department
    roles = get_roles_by_department(conn, department_id)
    return [r["name"] for r in roles]

def get_locations(conn) -> List[str]:
    """Carga dinámicamente las ubicaciones desde la BD."""
    from repository import get_all_locations
    locs = get_all_locations(conn)
    return [l["name"] for l in locs]

def get_department_id_by_name(conn, name: str) -> Optional[int]:
    """Obtiene el ID de un departamento por nombre."""
    c = conn.cursor()
    c.execute("SELECT id FROM departments WHERE name = ?", (name,))
    row = c.fetchone()
    return row[0] if row else None

def get_role_id_by_name(conn, role_name: str, department_id: int) -> Optional[int]:
    """Obtiene el ID de un rol por nombre y departamento."""
    c = conn.cursor()
    c.execute("SELECT id FROM roles WHERE name = ? AND department_id = ?", (role_name, department_id))
    row = c.fetchone()
    return row[0] if row else None

def get_location_id_by_name(conn, name: str) -> Optional[int]:
    """Obtiene el ID de una ubicación por nombre."""
    c = conn.cursor()
    c.execute("SELECT id FROM locations WHERE name = ?", (name,))
    row = c.fetchone()
    return row[0] if row else None

def prepare_employee_data_for_db(conn, form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte nombres a IDs y prepara el diccionario para la BD."""
    data = form_data.copy()
    
    # Convertir department nombre -> department_id
    if "department" in data:
        dept_id = get_department_id_by_name(conn, data["department"])
        del data["department"]
        data["department_id"] = dept_id
    
    # Convertir role nombre -> role_id
    if "role" in data and data.get("department_id"):
        role_id = get_role_id_by_name(conn, data["role"], data["department_id"])
        del data["role"]
        data["role_id"] = role_id
    
    # Convertir location nombre -> location_id
    if "location" in data and data["location"]:
        loc_id = get_location_id_by_name(conn, data["location"])
        del data["location"]
        data["location_id"] = loc_id
    
    return data

# Funciones de validación
def validate_employee_number(value: str) -> tuple[bool, str]:
    """Valida que sea solo números."""
    if not value:
        return False, "Requerido"
    if not value.isdigit():
        return False, "Solo números"
    return True, ""

def validate_name(value: str) -> tuple[bool, str]:
    """Valida que sea solo caracteres alfabéticos y espacios."""
    if not value:
        return False, "Requerido"
    if not all(c.isalpha() or c.isspace() for c in value):
        return False, "Solo letras"
    return True, ""

def validate_email(value: str) -> tuple[bool, str]:
    """Valida formato de email."""
    if not value:
        return True, ""  # Email es opcional
    import re
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, value):
        return False, "Formato inválido"
    return True, ""

def validate_phone(value: str) -> tuple[bool, str]:
    """Valida que sea solo números, espacios y caracteres de teléfono."""
    if not value:
        return True, ""  # Phone es opcional
    if not all(c.isdigit() or c in "- ()" for c in value):
        return False, "Solo números y caracteres permitidos"
    return True, ""


DEPARTMENT_OPTIONS = ["TI", "Ventas", "RRHH", "Finanzas", "Logistica", "Calidad", "Manufactura"]
ROLE_OPTIONS = ["Gerente", "Supervisor", "Desarrollador", "Cientifico de Datos", "Analista de Datos", "Interno"]

@st.cache_resource
def get_biometric_engine():
    """Lazy load del motor biométrico ArcFace con caching de Streamlit."""
    try:
        return ArcFaceEngine()
    except Exception as e:
        st.error(f"Error al inicializar motor biométrico: {str(e)}")
        st.info("Verifica tu conexión a internet o intenta descargar los modelos manualmente.")
        return None

ENGINE = None  # Se inicializa bajo demanda

def get_center_face_roi(image_shape):
    h, w = image_shape[:2]
    roi_w = int(w * SETTINGS.ROI_WIDTH_RATIO)
    roi_h = int(h * SETTINGS.ROI_HEIGHT_RATIO)
    x1 = (w - roi_w) // 2
    y1 = (h - roi_h) // 2
    x2 = x1 + roi_w
    y2 = y1 + roi_h
    return x1, y1, x2, y2

def draw_face_roi_guide(image_bgr, message="Coloca tu rostro dentro del marco"):
    x1, y1, x2, y2 = get_center_face_roi(image_bgr.shape)

    mask = np.zeros_like(image_bgr, dtype=np.uint8)
    cv2.rectangle(mask, (x1, y1), (x2, y2), (255, 255, 255), -1)
    darkened = cv2.addWeighted(image_bgr, 0.45, np.zeros_like(image_bgr), 0.55, 0)
    image_bgr = np.where(mask == 255, image_bgr, darkened)

    cv2.rectangle(image_bgr, (x1, y1), (x2, y2), (0, 255, 255), 2)
    cv2.putText(
        image_bgr,
        message,
        (x1, max(y1 - 12, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image_bgr

class FaceGuideProcessor(VideoProcessorBase):
    def __init__(self, guide_message="Coloca tu rostro dentro del marco"):
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.guide_message = guide_message

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        image_bgr = frame.to_ndarray(format="bgr24")
        with self.frame_lock:
            self.latest_frame = image_bgr.copy()

        preview = draw_face_roi_guide(image_bgr.copy(), message=self.guide_message)
        return av.VideoFrame.from_ndarray(preview, format="bgr24")

    def get_latest_frame(self):
        with self.frame_lock:
            if self.latest_frame is None:
                return None
            return self.latest_frame.copy()

def get_frame_from_webrtc_ctx(ctx):
    if ctx is None or not ctx.state.playing:
        return None
    processor = getattr(ctx, "video_processor", None)
    if processor is None or not hasattr(processor, "get_latest_frame"):
        return None
    return processor.get_latest_frame()

def build_employee_form(prefix="reg"):
    employee_number = st.text_input("Numero de empleado", key=f"{prefix}_employee_number")
    name = st.text_input("Nombre completo", key=f"{prefix}_name")
    department = st.selectbox("Departamento", DEPARTMENT_OPTIONS, key=f"{prefix}_department")
    role = st.selectbox("Rol", ROLE_OPTIONS, key=f"{prefix}_role")
    email = st.text_input("Correo", key=f"{prefix}_email")
    phone = st.text_input("Telefono", key=f"{prefix}_phone")
    location = st.text_input("Ubicacion", key=f"{prefix}_location")
    shift = st.selectbox("Turno", ["Matutino", "Vespertino", "Nocturno"], key=f"{prefix}_shift")
    status = st.selectbox("Estatus", ["Activo", "Inactivo", "Baja"], key=f"{prefix}_status")
    notes = st.text_area("Notas", key=f"{prefix}_notes")

    return {
        "employee_number": employee_number.strip(),
        "name": name.strip(),
        "department": department,
        "role": role,
        "email": email.strip(),
        "phone": phone.strip(),
        "location": location.strip(),
        "shift": shift,
        "status": status,
        "notes": notes.strip(),
    }

def fake_liveness_placeholder():
    """
    Placeholder de interfaz. Sustituir por proveedor real PAD/liveness.
    """
    return LivenessResult(
        passed=True,
        score=0.0,
        method="placeholder",
        reasons=["Liveness real pendiente de integración"],
    )

def get_guided_enrollment_plan(uses_glasses: bool):
    """
    Devuelve el plan de 5 capturas de forma automática.
    """
    if uses_glasses:
        return [
            {
                "sample_tag": "frontal_con_lentes",
                "instruction": "Foto 1 de 5: Mira de frente con expresión neutra y con lentes.",
                "glasses": True,
                "lighting_tag": "normal",
                "pose_tag": "frontal",
            },
            {
                "sample_tag": "izquierda_con_lentes",
                "instruction": "Foto 2 de 5: Gira ligeramente tu rostro hacia la izquierda, con lentes.",
                "glasses": True,
                "lighting_tag": "normal",
                "pose_tag": "left",
            },
            {
                "sample_tag": "derecha_con_lentes",
                "instruction": "Foto 3 de 5: Gira ligeramente tu rostro hacia la derecha, con lentes.",
                "glasses": True,
                "lighting_tag": "normal",
                "pose_tag": "right",
            },
            {
                "sample_tag": "frontal_sin_lentes",
                "instruction": "Foto 4 de 5: Retira tus lentes y mira de frente con expresión neutra.",
                "glasses": False,
                "lighting_tag": "normal",
                "pose_tag": "frontal",
            },
            {
                "sample_tag": "variante_sin_lentes",
                "instruction": "Foto 5 de 5: Sin lentes, inclina ligeramente el rostro o cambia un poco la expresión.",
                "glasses": False,
                "lighting_tag": "normal",
                "pose_tag": "variant",
            },
        ]

    return [
        {
            "sample_tag": "frontal",
            "instruction": "Foto 1 de 5: Mira de frente con expresión neutra.",
            "glasses": False,
            "lighting_tag": "normal",
            "pose_tag": "frontal",
        },
        {
            "sample_tag": "izquierda",
            "instruction": "Foto 2 de 5: Gira ligeramente tu rostro hacia la izquierda.",
            "glasses": False,
            "lighting_tag": "normal",
            "pose_tag": "left",
        },
        {
            "sample_tag": "derecha",
            "instruction": "Foto 3 de 5: Gira ligeramente tu rostro hacia la derecha.",
            "glasses": False,
            "lighting_tag": "normal",
            "pose_tag": "right",
        },
        {
            "sample_tag": "menton_arriba",
            "instruction": "Foto 4 de 5: Levanta ligeramente el mentón.",
            "glasses": False,
            "lighting_tag": "normal",
            "pose_tag": "chin_up",
        },
        {
            "sample_tag": "menton_abajo",
            "instruction": "Foto 5 de 5: Baja ligeramente el mentón.",
            "glasses": False,
            "lighting_tag": "normal",
            "pose_tag": "chin_down",
        },
    ]

def init_guided_enrollment_state():
    if "guided_enrollment" not in st.session_state:
        st.session_state.guided_enrollment = {
            "started": False,
            "employee_data": None,
            "uses_glasses": False,
            "plan": [],
            "step_idx": 0,
            "completed_samples": [],
        }


def reset_guided_enrollment_state():
    st.session_state.guided_enrollment = {
        "started": False,
        "employee_data": None,
        "uses_glasses": False,
        "plan": [],
        "step_idx": 0,
        "completed_samples": [],
    }

def detect_largest_face_from_image(image_bgr):
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb, model="hog")

    if not face_locations:
        return None, []

    def face_area(loc):
        top, right, bottom, left = loc
        return max(1, right - left) * max(1, bottom - top)

    best_location = max(face_locations, key=face_area)
    return best_location, face_locations

def draw_detected_face_box(image_bgr, face_location, total_faces=1):
    preview = image_bgr.copy()

    if face_location is None:
        return preview

    top, right, bottom, left = face_location
    cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 0), 2)

    label = f"Rostro detectado"
    if total_faces > 1:
        label = f"Se detectaron {total_faces} rostros - se usara el mas grande"

    cv2.putText(
        preview,
        label,
        (left, max(top - 10, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    return preview

def render_employee_form_step_by_step():
    """
    Formulario interactivo de datos del candidato dividido en 5 pasos.
    Cada paso muestra solo los campos relevantes con animación de progreso.
    """
    from repository import get_db_connection
    conn = get_db_connection()
    
    # Cargar opciones dinámicamente desde BD
    departments = get_departments(conn)
    locations = get_locations(conn)
    
    # Inicializar estado del formulario
    if "form_wizard_step" not in st.session_state:
        st.session_state.form_wizard_step = 0
        st.session_state.form_wizard_data = {
            "employee_number": "",
            "name": "",
            "department": departments[0] if departments else "TI",
            "role": "",
            "email": "",
            "phone": "",
            "location": locations[0] if locations else "",
            "shift": "Matutino",
            "status": "Activo",
            "uses_glasses": False,
            "notes": "",
        }
        st.session_state.form_wizard_errors = {}
    
    form_data = st.session_state.form_wizard_data
    errors = st.session_state.form_wizard_errors
    current_step = st.session_state.form_wizard_step
    
    # Emojis y descripciones para cada paso
    steps = [
        {"title": "📋 Información Básica", "emoji": "👤"},
        {"title": "🏢 Organización", "emoji": "🏢"},
        {"title": "📞 Contacto", "emoji": "📧"},
        {"title": "⏰ Detalles de Trabajo", "emoji": "⏰"},
        {"title": "👓 Confirmación", "emoji": "✅"},
    ]
    
    # Mostrar barra de progreso visual
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        progress_text = f"Paso {current_step + 1} de {len(steps)}"
        st.progress((current_step + 1) / len(steps), text=progress_text)
    
    # Mostrar indicadores de pasos (estilo breadcrumb)
    step_indicators = " → ".join(
        [f"{s['emoji']}" if i == current_step else f"{s['emoji']}" for i, s in enumerate(steps)]
    )
    st.markdown(f"<div style='text-align: center; font-size: 20px;'>{step_indicators}</div>", unsafe_allow_html=True)
    
    # Título del paso actual
    st.subheader(steps[current_step]["title"])
    st.markdown("---")
    
    # ==========================================
    # PASO 0: Información Básica
    # ==========================================
    if current_step == 0:
        st.markdown("Ingresa los datos básicos del usuario.")
        col1, col2 = st.columns(2)
        
        with col1:
            form_data["employee_number"] = st.text_input(
                "🔢 Número de empleado",
                value=form_data["employee_number"],
                key="step0_employee_number"
            ).strip()
            valid, msg = validate_employee_number(form_data["employee_number"])
            if not valid and form_data["employee_number"]:
                st.error(f"❌ Número de empleado: {msg}")
                errors["employee_number"] = msg
            else:
                errors.pop("employee_number", None)
        
        with col2:
            form_data["name"] = st.text_input(
                "👤 Nombre completo",
                value=form_data["name"],
                key="step0_name"
            ).strip()
            valid, msg = validate_name(form_data["name"])
            if not valid and form_data["name"]:
                st.error(f"❌ Nombre: {msg}")
                errors["name"] = msg
            else:
                errors.pop("name", None)
        
        # Validación del paso
        step_0_valid = len(errors) == 0 and form_data["employee_number"] and form_data["name"]
        if not step_0_valid:
            st.warning("⚠️ Los campos son requeridos y deben cumplir los formatos")
    
    # ==========================================
    # PASO 1: Organización
    # ==========================================
    elif current_step == 1:
        st.markdown("Información de la organización del candidato.")
        col1, col2 = st.columns(2)
        
        with col1:
            idx = departments.index(form_data["department"]) if form_data["department"] in departments else 0
            form_data["department"] = st.selectbox(
                "🏢 Departamento",
                departments,
                index=idx,
                key="step1_department"
            )
            # Cargar roles para el departamento seleccionado
            dept_id = get_department_id_by_name(conn, form_data["department"])
            if dept_id:
                available_roles = get_roles_for_department(conn, dept_id)
            else:
                available_roles = []
        
        with col2:
            if available_roles:
                idx = available_roles.index(form_data["role"]) if form_data["role"] in available_roles else 0
                form_data["role"] = st.selectbox(
                    "👔 Rol",
                    available_roles,
                    index=idx,
                    key="step1_role"
                )
            else:
                st.warning("No hay roles disponibles para este departamento")
                form_data["role"] = ""
        
        idx = locations.index(form_data["location"]) if form_data["location"] in locations else 0
        form_data["location"] = st.selectbox(
            "📍 Ubicación",
            locations,
            index=idx,
            key="step1_location"
        )
        
        step_0_valid = form_data["department"] and form_data["role"] and form_data["location"]
    
    # ==========================================
    # PASO 2: Contacto
    # ==========================================
    elif current_step == 2:
        st.markdown("Información de contacto del candidato.")
        col1, col2 = st.columns(2)
        
        with col1:
            form_data["email"] = st.text_input(
                "📧 Correo electrónico",
                value=form_data["email"],
                key="step2_email"
            ).strip()
            valid, msg = validate_email(form_data["email"])
            if not valid and form_data["email"]:
                st.error(f"❌ Correo: {msg}")
                errors["email"] = msg
            else:
                errors.pop("email", None)
        
        with col2:
            form_data["phone"] = st.text_input(
                "☎️ Teléfono",
                value=form_data["phone"],
                key="step2_phone"
            ).strip()
            valid, msg = validate_phone(form_data["phone"])
            if not valid and form_data["phone"]:
                st.error(f"❌ Teléfono: {msg}")
                errors["phone"] = msg
            else:
                errors.pop("phone", None)
        
        step_0_valid = len(errors) == 0
    
    # ==========================================
    # PASO 3: Detalles de Trabajo
    # ==========================================
    elif current_step == 3:
        st.markdown("Detalles del contrato y disponibilidad.")
        col1, col2 = st.columns(2)
        
        with col1:
            form_data["shift"] = st.selectbox(
                "⏰ Turno",
                ["Matutino", "Vespertino", "Nocturno"],
                index=["Matutino", "Vespertino", "Nocturno"].index(form_data["shift"]),
                key="step3_shift"
            )
        
        with col2:
            form_data["status"] = st.selectbox(
                "📊 Estatus",
                ["Activo", "Inactivo", "Baja"],
                index=["Activo", "Inactivo", "Baja"].index(form_data["status"]),
                key="step3_status"
            )
        
        step_0_valid = True
    
    # ==========================================
    # PASO 4: Confirmación y Finalización
    # ==========================================
    elif current_step == 4:
        st.markdown("Completa los últimos detalles y confirma la información.")
        
        # Checkbox de lentes
        form_data["uses_glasses"] = st.checkbox(
            "👓 El candidato usa lentes normalmente",
            value=form_data["uses_glasses"],
            key="step4_glasses"
        )
        
        # Notas adicionales
        form_data["notes"] = st.text_area(
            "📝 Notas adicionales (opcional)",
            value=form_data["notes"],
            height=100,
            key="step4_notes"
        ).strip()
        
        # Mostrar resumen
        st.markdown("---")
        st.markdown("### 📋 Resumen de Datos Ingresados")
        
        summary_cols = st.columns(2)
        with summary_cols[0]:
            st.write(f"**Empleado:** {form_data['employee_number']} - {form_data['name']}")
            st.write(f"**Departamento:** {form_data['department']}")
            st.write(f"**Rol:** {form_data['role']}")
            st.write(f"**Correo:** {form_data['email']}")
        
        with summary_cols[1]:
            st.write(f"**Teléfono:** {form_data['phone']}")
            st.write(f"**Ubicación:** {form_data['location']}")
            st.write(f"**Turno:** {form_data['shift']}")
            st.write(f"**Estatus:** {form_data['status']}")
        
        st.write(f"**Usa lentes:** {'Sí' if form_data['uses_glasses'] else 'No'}")
        
        if form_data["notes"]:
            st.write(f"**Notas:** {form_data['notes']}")
        
        step_0_valid = True
    
    # ==========================================
    # Botones de Navegación
    # ==========================================
    st.markdown("---")
    nav_cols = st.columns([1, 1, 1, 1, 1])
    
    # Botón Atrás
    with nav_cols[0]:
        if st.button("⬅️ Atrás", use_container_width=True, disabled=(current_step == 0)):
            st.session_state.form_wizard_step = current_step - 1
            st.rerun()
    
    # Botón Siguiente (o Iniciar Enrolamiento en el último paso)
    with nav_cols[4]:
        if current_step < len(steps) - 1:
            if st.button("➡️ Siguiente", use_container_width=True, disabled=(not step_0_valid)):
                st.session_state.form_wizard_step = current_step + 1
                st.rerun()
        else:
            # Último paso: botón para iniciar enrolamiento
            if st.button("✅ Iniciar Enrolamiento Guiado", use_container_width=True, type="primary", disabled=(not step_0_valid)):
                # Validaciones finales
                if not form_data["employee_number"] or not form_data["name"]:
                    st.error("❌ Número de empleado y nombre son obligatorios.")
                    return
                
                # Separar uses_glasses del resto de datos
                uses_glasses = form_data.pop("uses_glasses")
                form_data_temp = form_data.copy()
                
                # Convertir nombres a IDs para la BD
                employee_data_clean = prepare_employee_data_for_db(conn, form_data_temp)
                
                # Obtener plan de captura
                plan = get_guided_enrollment_plan(uses_glasses)
                
                # Guardar estado del enrolamiento
                st.session_state.guided_enrollment = {
                    "started": True,
                    "employee_data": employee_data_clean,
                    "uses_glasses": uses_glasses,
                    "plan": plan,
                    "step_idx": 0,
                    "completed_samples": [],
                }
                
                # Limpiar estado del formulario wizard para próximos usos
                del st.session_state.form_wizard_step
                del st.session_state.form_wizard_data
                
                st.rerun()
    
    conn.close()  # Cerrar la conexión al final

def render_register_section():
    st.header("Registro Guiado de Identidad")

    init_guided_enrollment_state()
    state = st.session_state.guided_enrollment

    # =========================
    # PASO 1: CONFIGURACION INICIAL (Formulario por pasos)
    # =========================
    if not state["started"]:
        st.info(
            "📸 Al completar este formulario, pasarás al proceso de captura de 5 fotografías "
            "con instrucciones automáticas. "
        )
        
        render_employee_form_step_by_step()
        return

    # =========================
    # PASO 2: FLUJO GUIADO DE 5 TOMAS
    # =========================
    employee_data = state["employee_data"]
    plan = state["plan"]
    step_idx = state["step_idx"]

    if step_idx >= len(plan):
        st.success("Enrolamiento completado correctamente.")
        st.markdown(f"**Candidato:** {employee_data['name']}")
        st.markdown(f"**Numero de empleado:** {employee_data['employee_number']}")
        st.markdown(f"**Muestras capturadas:** {len(state['completed_samples'])}")

        if state["completed_samples"]:
            st.subheader("Resumen de muestras guardadas")
            summary_df = pd.DataFrame(state["completed_samples"])
            st.dataframe(summary_df, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Registrar otro candidato"):
                reset_guided_enrollment_state()
                st.rerun()

        with col2:
            if st.button("Finalizar y mantener resumen"):
                st.info("El enrolamiento ya fue guardado. Puedes cambiar de sección cuando quieras.")
        return

    current_step = plan[step_idx]

    st.subheader(f"Captura {step_idx + 1} de {len(plan)}")
    st.info(current_step["instruction"])

    progress = (step_idx) / len(plan)
    st.progress(progress, text=f"Progreso: {step_idx} de {len(plan)} muestras completadas")

    camera_key = f"guided_capture_step_{step_idx}"
    img_file = st.camera_input(
        "Toma la fotografía",
        key=camera_key,
    )

    if img_file is not None:
        image_bgr = uploaded_camera_image_to_bgr(img_file)

        face_location, all_faces = detect_largest_face_from_image(image_bgr)

        if face_location is None:
            st.error("No se detectó ningún rostro en la imagen. Intenta de nuevo con mejor iluminación y encuadre.")
            st.image(
                cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB),
                caption="Imagen capturada (sin rostro detectado)",
                use_container_width=True,
            )
            return

        # Validar calidad y obtener marco visual
        is_quality_valid, quality_issues, preview_with_frame = validate_and_draw_quality_frame(
            image_bgr, face_location
        )
        
        face_crop = crop_face_from_location(image_bgr, face_location, padding_ratio=0.20)

        if face_crop is None:
            st.error("No fue posible recortar el rostro detectado.")
            return

        # Mostrar imagen con marco coloreado
        st.image(
            cv2.cvtColor(preview_with_frame, cv2.COLOR_BGR2RGB),
            caption="Validación de Calidad",
            use_container_width=True,
        )
        
        # Mostrar estado de calidad
        if is_quality_valid:
            st.success("✅ La foto cumple con todos los estándares de calidad")
        else:
            st.warning("⚠️ La foto NO cumple con los estándares:")
            for issue in quality_issues:
                st.write(f"  • {issue}")

        st.image(
            cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB),
            caption="Recorte del rostro que se usará para el enrolamiento",
            use_container_width=True,
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Aceptar esta fotografía y continuar", type="primary", key=f"accept_step_{step_idx}"):
                engine = get_biometric_engine()
                if engine is None:
                    st.error("Motor biométrico no disponible. Revisa la consola para más detalles.")
                    return
                try:
                    ok, msg, payload = enroll_sample_for_employee(
                        engine=engine,
                        employee_data=employee_data,
                        frame_bgr=image_bgr,
                        sample_tag=current_step["sample_tag"],
                        glasses=current_step["glasses"],
                        lighting_tag=current_step["lighting_tag"],
                        pose_tag=current_step["pose_tag"],
                    )
                except NotImplementedError as e:
                    st.warning(str(e))
                    return

                if ok:
                    completed = dict(current_step)
                    completed["status"] = "Guardada"
                    state["completed_samples"].append(completed)
                    state["step_idx"] += 1
                    st.session_state.guided_enrollment = state
                    st.success(f"Muestra guardada correctamente: {current_step['sample_tag']}")
                    st.rerun()
                else:
                    st.error(msg)

        with col2:
            if st.button("Repetir esta fotografía", key=f"retry_step_{step_idx}"):
                # Limpiar la foto actual
                camera_key = f"guided_capture_step_{step_idx}"
                if camera_key in st.session_state:
                    del st.session_state[camera_key]
                st.rerun()
        
        with col1:
            if st.button("⬅️ Volver al Formulario", use_container_width=True):
                reset_guided_enrollment_state()
                if "form_wizard_step" in st.session_state:
                    del st.session_state.form_wizard_step
                if "form_wizard_data" in st.session_state:
                    del st.session_state.form_wizard_data
                st.rerun()

def uploaded_camera_image_to_bgr(img_file):
    image = Image.open(img_file)
    image_np = np.array(image)
    return cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

def validate_and_draw_quality_frame(image_bgr, face_location):
    """
    Valida la calidad de la imagen y dibuja un marco de color (verde = válida, rojo = inválida).
    Retorna: (is_valid, quality_issues, preview_image)
    """
    engine = get_biometric_engine()
    if engine is None:
        return False, ["Motor biométrico no disponible"], image_bgr
    
    try:
        # Extraer rostro y validar calidad
        extracted = engine.extract(image_bgr)
        quality = extracted.quality
        
        # Determinar si es válida (acceder a atributos del objeto QualityResult, no .get())
        is_valid = quality.passed
        
        # Obtener detalles de qué falló
        quality_issues = quality.reasons
        
        # Dibujar marco en la imagen
        preview = image_bgr.copy()
        top, right, bottom, left = face_location
        
        if is_valid:
            # Marco VERDE - Válida
            marco_color = (0, 255, 0)  # Verde en BGR
            label = "✅ CALIDAD ÓPTIMA"
        else:
            # Marco ROJO - Inválida
            marco_color = (0, 0, 255)  # Rojo en BGR
            label = "❌ CALIDAD INSUFICIENTE"
        
        # Dibujar rectángulo grueso
        cv2.rectangle(preview, (left, top), (right, bottom), marco_color, 4)
        
        # Dibujar etiqueta
        cv2.putText(
            preview,
            label,
            (left, max(top - 15, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            marco_color,
            2,
            cv2.LINE_AA,
        )
        
        return is_valid, quality_issues, preview
    
    except Exception as e:
        return False, [str(e)], image_bgr

def crop_face_from_location(image_bgr, face_location, padding_ratio=0.20):
    if face_location is None:
        return None

    h, w = image_bgr.shape[:2]
    top, right, bottom, left = face_location

    face_w = max(right - left, 1)
    face_h = max(bottom - top, 1)

    pad_x = int(face_w * padding_ratio)
    pad_y = int(face_h * padding_ratio)

    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(w, right + pad_x)
    bottom = min(h, bottom + pad_y)

    return image_bgr[top:bottom, left:right].copy()


def render_verify_section():
    st.header("Verificación 1:1")
    st.info(
        "En operación empresarial te conviene usar 1:1 siempre que sea posible "
        "(ej. número de empleado + rostro), en vez de 1:N contra todos."
    )

    col1, col2 = st.columns(2)
    
    with col1:
        employee_number = st.text_input("Numero de empleado a verificar", key="verify_employee_number")
    
    with col2:
        threshold = st.number_input(
            "Threshold operativo",
            min_value=0.0,
            max_value=2.0,
            value=float(SETTINGS.DEFAULT_THRESHOLD),
            step=0.01,
        )

    st.divider()
    
    # Captura de foto - Simple y estática
    st.subheader("📸 Captura de Rostro")
    st.info("Toma una foto clara de tu rostro. Asegúrate de estar bien iluminado y centrado.")
    
    img_file = st.camera_input(
        "Toma una fotografía",
        key="verify_camera",
    )
    
    if img_file is not None:
        # Convertir la imagen a BGR
        image = Image.open(img_file)
        image_np = np.array(image)
        frame_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
        
        # Mostrar preview
        col1, col2 = st.columns(2)
        with col1:
            st.image(image, caption="Foto capturada", use_container_width=True)
        
        with col2:
            st.subheader("Parámetros de Verificación")
            st.metric("Numero de Empleado", employee_number or "No especificado")
            st.metric("Threshold", f"{threshold:.2f}")
        
        st.divider()
        
        # Botón para verificar
        if st.button("🔍 Verificar Identidad", type="primary", use_container_width=True):
            if not employee_number.strip():
                st.error("❌ Por favor: Ingresa el número de empleado")
                return
            
            liveness_result = fake_liveness_placeholder()
            
            engine = get_biometric_engine()
            if engine is None:
                st.error("❌ Motor biométrico no disponible. Revisa la consola para más detalles.")
                return
            
            with st.spinner("🔄 Procesando verificación..."):
                try:
                    result = verify_employee_one_to_one(
                        engine=engine,
                        employee_number=employee_number.strip(),
                        frame_bgr=frame_bgr,
                        threshold=threshold,
                        liveness_result=liveness_result,
                    )
                except NotImplementedError as e:
                    st.warning(str(e))
                    return

            # Interfaz mejorada y amigable para usuarios no técnicos
            st.divider()

            # --- Doble verificación: Rostro + TRAC_MEX ---
            tracmex_result = None
            if result.matched:
                with st.spinner("🔄 Verificando certificación en TRAC_MEX..."):
                    tracmex_result = check_tracmex_access(employee_number.strip())

            # Determinar acceso final
            face_ok = result.matched
            tracmex_ok = tracmex_result["passed"] if tracmex_result else False
            access_granted = face_ok and tracmex_ok

            # Enviar resultado a PI
            with st.spinner("📡 Enviando resultado a PI..."):
                pi_result = send_to_pi(employee_number.strip(), access_granted)

            # Resultado principal - GRANDE Y CLARO
            if access_granted:
                # Obtener nombre del empleado
                _conn = _get_db_conn()
                _emp = get_employee_by_number(_conn, employee_number.strip())
                _conn.close()
                emp_name = _emp["name"] if _emp else "Desconocido"

                st.success("✅ VERIFICACIÓN EXITOSA")
                st.markdown(f"""
                <div style="text-align: center; font-size: 24px; margin: 20px 0;">
                    <span style="color: green; font-weight: bold;">ACCESO PERMITIDO</span><br>
                    <span style="font-size: 20px;">👤 {emp_name}</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error("❌ VERIFICACIÓN FALLIDA")
                st.markdown("""
                <div style="text-align: center; font-size: 24px; margin: 20px 0;">
                    <span style="color: red; font-weight: bold;">ACCESO DENEGADO</span>
                </div>
                """, unsafe_allow_html=True)

            # Detalle de cada verificación
            st.subheader("📋 Detalle de Verificación")
            vc1, vc2 = st.columns(2)
            with vc1:
                if face_ok:
                    st.success("✅ Rostro: Coincide con el empleado")
                else:
                    st.error("❌ Rostro: No coincide con el empleado")
            with vc2:
                if tracmex_result is None:
                    st.warning("⚠️ TRAC_MEX: No consultado (rostro no coincidió)")
                elif tracmex_result.get("error"):
                    st.error(f"❌ TRAC_MEX: Error de conexión - {tracmex_result['error']}")
                elif tracmex_ok:
                    st.success("✅ TRAC_MEX: Certificación válida")
                else:
                    st.error("❌ TRAC_MEX: Certificación no válida")

            if tracmex_result and tracmex_result.get("message"):
                st.info(f"**TRAC_MEX:** {tracmex_result['message']}")

            # Resultado de PI
            if pi_result.get("ok"):
                st.success(f"📡 PI: Dato enviado correctamente (MME14764-AXN.User|{employee_number.strip() if access_granted else '0'})")
            elif pi_result.get("error"):
                st.error(f"📡 PI: Error de conexión - {pi_result['error']}")
            else:
                st.error(f"📡 PI: Error HTTP {pi_result['status']}")

            st.divider()
            
            # Información del empleado verificado
            if result.matched and result.employee_id:
                st.subheader("ℹ️ Información del Empleado")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("ID de Empleado", result.employee_id)
                with col2:
                    st.metric("ID de Identidad", result.identity_id)
            
            # Métricas de confianza - Visible pero simple
            st.subheader("📊 Análisis de Confianza")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                # Similitud (convertir distancia a porcentaje de confianza)
                confidence_score = max(0, 100 * (1 - result.distance)) if result.distance is not None else 0
                st.metric(
                    "Confianza",
                    f"{confidence_score:.1f}%",
                    delta=f"Distancia: {result.distance:.4f}" if result.distance else None
                )
            
            with col2:
                # Threshold
                st.metric(
                    "Umbral de Referencia",
                    f"{result.threshold_used:.2f}",
                    help="Valor máximo permitido para la distancia"
                )
            
            with col3:
                # Estado de calidad
                quality_text = "✓ Excelente" if result.quality and result.quality.passed else "⚠ Revisar"
                st.metric(
                    "Calidad de Captura",
                    quality_text,
                )
            
            st.divider()
            
            # Detalle de calidad de imagen
            if result.quality:
                st.subheader("🎥 Detalles de Calidad de Imagen")
                
                quality = result.quality
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Brillo", f"{quality.brightness:.0f}", help="Rango ideal: 50-200")
                with col2:
                    st.metric("Enfoque", f"{quality.blur_variance:.1f}", help="Mayor es mejor (>100 es bueno)")
                with col3:
                    st.metric("Tamaño Rostro", f"{quality.face_size_px} px²")
                with col4:
                    centered_text = "✓ Sí" if quality.face_centered else "✗ No"
                    st.metric("Centrado", centered_text)
                
                if quality.reasons:
                    st.warning(f"⚠️ Problemas detectados: {' | '.join(quality.reasons)}")
            
            # Liveness check
            if result.liveness:
                st.subheader("🔍 Detección de Vida")
                if result.liveness.passed:
                    st.success(f"✓ Detección de vida completada")
                else:
                    st.warning(f"⚠ {result.liveness.method}: {', '.join(result.liveness.reasons)}")
            
            st.divider()
            
            # Sección técnica expandible para usuarios avanzados
            with st.expander("📋 Detalles técnicos (avanzado)"):
                st.subheader("Datos técnicos completos")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Resultado de Verificación:**")
                    st.json({
                        "matched": bool(result.matched),
                        "distance": float(result.distance) if result.distance else None,
                        "threshold": float(result.threshold_used),
                        "employee_id": result.employee_id,
                        "identity_id": result.identity_id,
                    })
                
                with col2:
                    st.write("**Quality Gate:**")
                    if result.quality:
                        st.json({
                            "passed": bool(result.quality.passed),
                            "brightness": float(result.quality.brightness),
                            "blur_variance": float(result.quality.blur_variance),
                            "face_size_px": int(result.quality.face_size_px),
                            "face_centered": bool(result.quality.face_centered),
                            "pose_ok": bool(result.quality.pose_ok),
                            "issues": result.quality.reasons or []
                        })
                
                if result.liveness:
                    st.write("**Liveness Detection:**")
                    st.json({
                        "passed": bool(result.liveness.passed),
                        "score": float(result.liveness.score),
                        "method": result.liveness.method,
                        "reasons": result.liveness.reasons or []
                    })


def render_management_section():
    st.header("Gestión de registros")
    df = list_employees_df()
    if df.empty:
        st.info("No hay empleados registrados.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)

def render_calibration_section():
    st.header("Calibración de threshold")
    st.info(
        "Exporta un CSV con columnas distance e is_genuine (1/0). "
        "Luego calibra el threshold buscando el FAR objetivo."
    )
    st.code(
        "from calibration import calibrate_threshold_from_scores\n"
        "import pandas as pd\n"
        "df = pd.read_csv('scores.csv')\n"
        "res = calibrate_threshold_from_scores(df, target_far=0.001)\n"
        "print(res['recommended_threshold'], res['far_observed'], res['fnr_observed'])"
    )


def render_database_section():
    """
    Sección de administración de base de datos.
    Requiere autenticación con usuario y contraseña.
    Permite editar y eliminar registros de empleados.
    """
    from repository import verify_admin_credentials, get_all_employees_for_edit, update_employee, delete_employee, get_db_connection
    
    st.header("🔐 Administración de Base de Datos")
    
    # Inicializar estado de autenticación
    if "db_authenticated" not in st.session_state:
        st.session_state.db_authenticated = False
    
    # Si no está autenticado, mostrar formulario de login
    if not st.session_state.db_authenticated:
        st.warning("⚠️ Esta sección requiere autenticación.")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("🔑 Iniciar Sesión")
            
            username = st.text_input("Usuario", key="db_username")
            password = st.text_input("Contraseña", type="password", key="db_password")
            
            col_login, col_cancel = st.columns(2)
            with col_login:
                if st.button("Ingresar", type="primary", use_container_width=True):
                    if verify_admin_credentials(username, password):
                        st.session_state.db_authenticated = True
                        st.success("✅ Autenticación exitosa")
                        st.rerun()
                    else:
                        st.error("❌ Usuario o contraseña incorrectos")
            
            with col_cancel:
                if st.button("Cancelar", use_container_width=True):
                    pass
        
        with col2:
            st.info(
                "**Credenciales de Prueba:**\n\n"
                "Usuario: `admin`\n\n"
                "Contraseña: `admin123`"
            )
        return
    
    # Si está autenticado, mostrar opciones de administración
    st.success("✅ Sesión autenticada")
    
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state.db_authenticated = False
            st.rerun()
    
    st.markdown("---")
    
    # Selector de operación
    operation = st.radio(
        "Selecciona una operación:",
        ["Ver Empleados", "Editar Empleado", "Eliminar Empleado", "⚙️ Configuración"],
        horizontal=True
    )
    
    conn = get_db_connection()
    
    # ============================
    # VER TODOS LOS EMPLEADOS
    # ============================
    if operation == "Ver Empleados":
        st.subheader("📋 Todos los Empleados")
        
        try:
            employees_df = get_all_employees_for_edit(conn)
            
            if employees_df.empty:
                st.info("No hay empleados registrados.")
            else:
                # Mostrar tabla
                st.dataframe(employees_df, use_container_width=True, hide_index=True)
                
                # Opciones de exportación
                col1, col2 = st.columns(2)
                with col1:
                    csv_export = employees_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Descargar CSV",
                        data=csv_export,
                        file_name="employees.csv",
                        mime="text/csv"
                    )
                
                with col2:
                    st.metric("Total de Empleados", len(employees_df))
        
        except Exception as e:
            st.error(f"Error al obtener empleados: {str(e)}")
    
    # ============================
    # EDITAR EMPLEADO
    # ============================
    elif operation == "Editar Empleado":
        st.subheader("✏️ Editar Datos de Empleado")
        
        try:
            employees_df = get_all_employees_for_edit(conn)
            
            if employees_df.empty:
                st.info("No hay empleados registrados para editar.")
            else:
                # Selector de empleado
                employee_options = [f"{row['employee_number']} - {row['name']}" for _, row in employees_df.iterrows()]
                selected_option = st.selectbox("Selecciona un empleado", employee_options)
                
                selected_idx = employee_options.index(selected_option)
                selected_employee = employees_df.iloc[selected_idx].to_dict()
                
                st.markdown("---")
                st.write(f"**ID:** {selected_employee['id']}")
                st.write(f"**Número de Empleado:** {selected_employee['employee_number']}")
                st.write(f"**Fecha de Registro:** {selected_employee['registration_date']}")
                st.markdown("---")
                
                # Formulario de edición
                col1, col2 = st.columns(2)
                
                with col1:
                    name = st.text_input("Nombre completo", value=selected_employee.get('name', ''))
                    department = st.text_input("Departamento", value=selected_employee.get('department', ''))
                    role = st.text_input("Rol", value=selected_employee.get('role', ''))
                    email = st.text_input("Correo", value=selected_employee.get('email', ''))
                
                with col2:
                    phone = st.text_input("Teléfono", value=selected_employee.get('phone', ''))
                    location = st.text_input("Ubicación", value=selected_employee.get('location', ''))
                    shift = st.text_input("Turno", value=selected_employee.get('shift', ''))
                    status = st.selectbox("Estatus", ["Activo", "Inactivo", "Baja"], 
                                         index=["Activo", "Inactivo", "Baja"].index(selected_employee.get('status', 'Activo')))
                
                notes = st.text_area("Notas", value=selected_employee.get('notes', ''), height=100)
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Guardar Cambios", type="primary", use_container_width=True):
                        updated_data = {
                            "name": name,
                            "department": department,
                            "role": role,
                            "email": email,
                            "phone": phone,
                            "location": location,
                            "shift": shift,
                            "status": status,
                            "notes": notes,
                        }
                        
                        if update_employee(conn, selected_employee['id'], updated_data):
                            st.success("✅ Empleado actualizado correctamente")
                            st.rerun()
                        else:
                            st.error("❌ Error al actualizar empleado")
                
                with col2:
                    if st.button("Cancelar", use_container_width=True):
                        pass
        
        except Exception as e:
            st.error(f"Error en edición: {str(e)}")
    
    # ============================
    # ELIMINAR EMPLEADO
    # ============================
    elif operation == "Eliminar Empleado":
        st.subheader("🗑️ Eliminar Empleado")
        st.warning("⚠️ Esta acción es irreversible y eliminará todos los datos asociados del empleado.")
        
        try:
            employees_df = get_all_employees_for_edit(conn)
            
            if employees_df.empty:
                st.info("No hay empleados registrados para eliminar.")
            else:
                employee_options = [f"{row['employee_number']} - {row['name']}" for _, row in employees_df.iterrows()]
                selected_option = st.selectbox("Selecciona un empleado a eliminar", employee_options)
                
                selected_idx = employee_options.index(selected_option)
                selected_employee = employees_df.iloc[selected_idx].to_dict()
                
                st.error(f"**Será eliminado:** {selected_employee['name']} ({selected_employee['employee_number']})")
                st.info("Se eliminarán:\n- Registro del empleado\n- Muestras biométricas\n- Logs de verificación")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("❌ Confirmar Eliminación", type="secondary", use_container_width=True):
                        if delete_employee(conn, selected_employee['id']):
                            st.success("✅ Empleado eliminado correctamente")
                            st.rerun()
                        else:
                            st.error("❌ Error al eliminar empleado")
                
                with col2:
                    if st.button("Cancelar", use_container_width=True):
                        pass
        
        except Exception as e:
            st.error(f"Error en eliminación: {str(e)}")
    
    # ============================
    # CONFIGURACIÓN - CRUD DE REFERENCIA
    # ============================
    elif operation == "⚙️ Configuración":
        from repository import (
            get_all_departments, add_department, update_department, delete_department,
            get_all_roles_with_dept, add_role, update_role, delete_role, get_roles_by_department,
            get_all_locations, add_location, update_location, delete_location
        )
        
        st.subheader("⚙️ Configuración del Sistema")
        st.info("Gestiona los departamentos, roles y ubicaciones disponibles en la aplicación.")
        
        # Selector de tipo de configuración
        config_type = st.selectbox(
            "¿Qué deseas configurar?",
            ["Departamentos", "Roles", "Ubicaciones"]
        )
        
        # ====== DEPARTAMENTOS ======
        if config_type == "Departamentos":
            st.markdown("### 🏢 Gestión de Departamentos")
            
            col1, col2 = st.columns([3, 1])
            with col1:
                new_dept = st.text_input("Nuevo departamento", key="new_department")
            with col2:
                if st.button("Agregar", use_container_width=True):
                    if new_dept.strip():
                        if add_department(conn, new_dept):
                            st.success(f"✅ Departamento '{new_dept}' agregado")
                            st.rerun()
                        else:
                            st.error("Error al agregar departamento")
                    else:
                        st.error("Campo requerido")
            
            st.markdown("---")
            st.markdown("**Departamentos existentes:**")
            
            depts = get_all_departments(conn)
            if depts:
                for dept in depts:
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.write(f"**{dept['name']}**")
                    
                    with col2:
                        new_name = st.text_input(f"Nuevo nombre", key=f"edit_dept_{dept['id']}", label_visibility="collapsed")
                        if new_name and st.button("✏️", key=f"update_dept_{dept['id']}", use_container_width=True):
                            if update_department(conn, dept['id'], new_name):
                                st.success("Actualizado")
                                st.rerun()
                    
                    with col3:
                        if st.button("🗑️", key=f"delete_dept_{dept['id']}", use_container_width=True):
                            if delete_department(conn, dept['id']):
                                st.success("Eliminado")
                                st.rerun()
                            else:
                                st.error("No se puede eliminar (tiene roles asociados)")
            else:
                st.info("No hay departamentos")
        
        # ====== ROLES ======
        elif config_type == "Roles":
            st.markdown("### 👔 Gestión de Roles")
            
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                depts = get_all_departments(conn)
                dept_options = [d['name'] for d in depts]
                selected_dept = st.selectbox("Departamento", dept_options, key="role_dept_select")
                selected_dept_id = next((d['id'] for d in depts if d['name'] == selected_dept), None)
            
            with col2:
                new_role = st.text_input("Nuevo rol", key="new_role")
            
            with col3:
                if st.button("Agregar", use_container_width=True):
                    if new_role.strip() and selected_dept_id:
                        if add_role(conn, new_role, selected_dept_id):
                            st.success("✅ Rol agregado")
                            st.rerun()
                        else:
                            st.error("Error al agregar rol")
                    else:
                        st.error("Campo requerido")
            
            st.markdown("---")
            
            if selected_dept_id:
                st.markdown(f"**Roles en {selected_dept}:**")
                roles = get_roles_by_department(conn, selected_dept_id)
                
                if roles:
                    for role in roles:
                        col1, col2, col3 = st.columns([2, 1, 1])
                        
                        with col1:
                            st.write(f"• {role['name']}")
                        
                        with col2:
                            new_name = st.text_input(f"Nuevo nombre", key=f"edit_role_{role['id']}", label_visibility="collapsed")
                            if new_name and st.button("✏️", key=f"update_role_{role['id']}", use_container_width=True):
                                if update_role(conn, role['id'], new_name, selected_dept_id):
                                    st.success("Actualizado")
                                    st.rerun()
                        
                        with col3:
                            if st.button("🗑️", key=f"delete_role_{role['id']}", use_container_width=True):
                                if delete_role(conn, role['id']):
                                    st.success("Eliminado")
                                    st.rerun()
                                else:
                                    st.error("No se puede eliminar (tiene empleados asociados)")
                else:
                    st.info("No hay roles en este departamento")
        
        # ====== UBICACIONES ======
        elif config_type == "Ubicaciones":
            st.markdown("### 📍 Gestión de Ubicaciones")
            
            col1, col2 = st.columns([3, 1])
            with col1:
                new_loc = st.text_input("Nueva ubicación", key="new_location")
            with col2:
                if st.button("Agregar", use_container_width=True):
                    if new_loc.strip():
                        if add_location(conn, new_loc):
                            st.success(f"✅ Ubicación '{new_loc}' agregada")
                            st.rerun()
                        else:
                            st.error("Error al agregar ubicación")
                    else:
                        st.error("Campo requerido")
            
            st.markdown("---")
            st.markdown("**Ubicaciones existentes:**")
            
            locs = get_all_locations(conn)
            if locs:
                for loc in locs:
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        st.write(f"**{loc['name']}**")
                    
                    with col2:
                        new_name = st.text_input(f"Nuevo nombre", key=f"edit_loc_{loc['id']}", label_visibility="collapsed")
                        if new_name and st.button("✏️", key=f"update_loc_{loc['id']}", use_container_width=True):
                            if update_location(conn, loc['id'], new_name):
                                st.success("Actualizado")
                                st.rerun()
                    
                    with col3:
                        if st.button("🗑️", key=f"delete_loc_{loc['id']}", use_container_width=True):
                            if delete_location(conn, loc['id']):
                                st.success("Eliminado")
                                st.rerun()
                            else:
                                st.error("No se puede eliminar (tiene empleados asociados)")
            else:
                st.info("No hay ubicaciones")
    
    conn.close()


def send_to_pi(employee_number: str, access_granted: bool) -> dict:
    """Envía el resultado de verificación al PI Web Service."""
    import requests

    value = employee_number if access_granted else "0"
    tag_and_value = f"ME14764-AXN.User|{value}"

    try:
        resp = requests.post(
            "http://nts5111/PI_FunctionalWS/PIWebService.asmx/Send_Functional_Master_To_PI",
            data={"tag_and_value": tag_and_value},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return {"ok": resp.status_code == 200, "status": resp.status_code, "body": resp.text, "error": None}
    except Exception as e:
        return {"ok": False, "status": None, "body": None, "error": str(e)}


def check_tracmex_access(employee_number: str, process_id: int = 50048,
                         operacion: int = 1, in_part_number: str = "0",
                         parameter_name: str = "TRESS Certification") -> dict:
    """Consulta Get_User_Access_Status via HTTP API y devuelve {passed, message, error}."""
    import requests

    try:
        params = {
            "user_id": employee_number,
            "process_id": process_id,
            "Operacion": operacion,
            "parameter_name": parameter_name,
        }
        headers = {"Accept": "application/json"}
        resp = requests.get(SETTINGS.TRACMEX_API_URL, params=params,
                            headers=headers, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        # La API devuelve un array: [{"PassedValidation":1,"ReturnMessage":"..."}]
        item = data[0] if isinstance(data, list) and len(data) > 0 else data
        passed_val = int(item.get("PassedValidation", 0))
        message = item.get("ReturnMessage") or "Sin mensaje"

        return {"passed": passed_val == 1, "message": message, "error": None}
    except Exception as e:
        return {"passed": False, "message": None, "error": str(e)}


def render_tracmex_section():
    """Sección para consultar el estatus de acceso de un usuario en TRAC_MEX."""
    st.header("Consulta TRAC_MEX - Estatus de Acceso")

    with st.form("tracmex_form"):
        col1, col2 = st.columns(2)
        with col1:
            user_id = st.text_input("User ID (No. Empleado)", value="", placeholder="Ej: 50003012")
            process_id = st.number_input("Process ID", value=50048, step=1)
            operacion = st.number_input("Operación", value=1, step=1)
        with col2:
            parameter_name = st.text_input("Parameter Name", value="TRESS Certification")

        submitted = st.form_submit_button("Consultar Estatus", use_container_width=True)

    if submitted:
        if not user_id.strip():
            st.error("Ingrese un User ID válido.")
            return

        try:
            with st.spinner("Consultando TRAC_MEX API..."):
                result = check_tracmex_access(
                    employee_number=user_id.strip(),
                    process_id=int(process_id),
                    operacion=int(operacion),
                    parameter_name=parameter_name.strip(),
                )

            if result["error"]:
                st.error(f"Error: {result['error']}")
            else:
                st.subheader("Resultado")
                icon = "✅" if result["passed"] else "❌"
                st.metric("PassedValidation", f"{icon} {1 if result['passed'] else 0}")
                st.markdown("**ReturnMessage:**")
                st.info(result["message"])

        except Exception as e:
            st.error(f"Error inesperado: {e}")


def capture_frame_from_camera(camera_index: int = 0) -> Optional[np.ndarray]:
    """Captura un frame de la cámara local usando OpenCV. Abre, captura y cierra."""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        return None
    try:
        ret, frame = cap.read()
        if ret:
            return frame
        return None
    finally:
        cap.release()

def render_operator_section():
    """Sección para operadores: verificación en tiempo real con video continuo."""
    st.header("🏭 Real Time Face Recognition")

    # --- Inicializar estado ---
    if "operator_employee_number" not in st.session_state:
        st.session_state.operator_employee_number = ""
    if "operator_active" not in st.session_state:
        st.session_state.operator_active = False
    if "operator_status" not in st.session_state:
        st.session_state.operator_status = None  # None | "granted" | "denied"

    # --- Paso 1: Pedir número de empleado ---
    if not st.session_state.operator_active:
        st.info("Ingresa tu número de empleado para iniciar la verificación continua.")
        emp_num = st.text_input("Número de Empleado", key="op_emp_input", placeholder="Ej: 50003012")
        if st.button("▶️ Iniciar Verificación", type="primary", use_container_width=True):
            if emp_num.strip():
                st.session_state.operator_employee_number = emp_num.strip()
                st.session_state.operator_active = True
                st.session_state.operator_status = None
                st.rerun()
            else:
                st.error("Ingresa un número de empleado válido.")
        return

    # --- Paso 2: Verificación activa con video en vivo ---
    employee_number = st.session_state.operator_employee_number

    col_header, col_stop = st.columns([3, 1])
    with col_header:
        st.markdown(f"### Empleado: `{employee_number}`")
    with col_stop:
        if st.button("⏹️ Detener", type="secondary", use_container_width=True):
            send_to_pi(employee_number, False)
            st.session_state.operator_active = False
            st.session_state.operator_status = None
            st.rerun()

    st.divider()

    # Layout: video a la izquierda, resultados a la derecha
    col_cam, col_result = st.columns([1, 1])
    with col_cam:
        frame_placeholder = st.empty()
    with col_result:
        status_placeholder = st.empty()
        detail_placeholder = st.empty()
        tracmex_placeholder = st.empty()
        pi_placeholder = st.empty()
        time_placeholder = st.empty()

    # Cargar engine una vez
    engine = get_biometric_engine()
    if engine is None:
        status_placeholder.error("❌ Motor biométrico no disponible.")
        return

    # Abrir cámara
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        status_placeholder.error("❌ No se pudo acceder a la cámara.")
        return

    threshold = float(SETTINGS.DEFAULT_THRESHOLD)
    last_verify_time = 0.0
    last_pi_time = 0.0
    access_granted = False
    face_matched = False
    tracmex_ok = False
    tracmex_msg = ""
    pi_msg = ""

    try:
        while cap.isOpened():
            ret, frame_bgr = cap.read()
            if not ret:
                frame_placeholder.error("❌ Error al leer la cámara.")
                break

            now = time.time()

            # --- Detectar rostros para dibujar rectángulo ---
            frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
            rgb_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_small, model="hog")

            # Color del rectángulo según último estado de validación
            if access_granted:
                rect_color = (0, 255, 0)  # Verde
                label = "ACCESO PERMITIDO"
            else:
                rect_color = (0, 0, 255)  # Rojo
                label = "ACCESO DENEGADO"

            annotated = frame_bgr.copy()
            for (top, right, bottom, left) in face_locations:
                # Escalar de vuelta al tamaño original
                top *= 2
                right *= 2
                bottom *= 2
                left *= 2
                cv2.rectangle(annotated, (left, top), (right, bottom), rect_color, 3)
                # Etiqueta
                cv2.rectangle(annotated, (left, bottom), (right, bottom + 35), rect_color, -1)
                cv2.putText(annotated, label, (left + 6, bottom + 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Mostrar frame con anotaciones
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            frame_placeholder.image(annotated_rgb, channels="RGB", use_container_width=True)

            # --- Verificación cada 5 segundos ---
            if now - last_verify_time >= 5.0:
                last_verify_time = now

                liveness_result = fake_liveness_placeholder()
                try:
                    result = verify_employee_one_to_one(
                        engine=engine,
                        employee_number=employee_number,
                        frame_bgr=frame_bgr,
                        threshold=threshold,
                        liveness_result=liveness_result,
                    )
                except NotImplementedError:
                    result = None

                if result:
                    face_matched = result.matched

                    # TRAC_MEX
                    tracmex_ok = False
                    tracmex_msg = ""
                    if face_matched:
                        tr = check_tracmex_access(employee_number)
                        tracmex_ok = tr["passed"]
                        tracmex_msg = tr.get("message", "")
                        if tr.get("error"):
                            tracmex_msg = f"Error: {tr['error']}"

                    access_granted = face_matched and tracmex_ok

                # Actualizar panel de resultados
                with status_placeholder.container():
                    if access_granted:
                        _conn = _get_db_conn()
                        _emp = get_employee_by_number(_conn, employee_number)
                        _conn.close()
                        emp_name = _emp["name"] if _emp else "Desconocido"
                        st.success(f"## ✅ ACCESO PERMITIDO\n### 👤 {emp_name}")
                    else:
                        st.error("## ❌ ACCESO DENEGADO")

                with detail_placeholder.container():
                    if face_matched:
                        st.success("✅ Rostro: Coincide")
                    else:
                        st.error("❌ Rostro: No coincide")
                    if not face_matched:
                        st.warning("⚠️ TRAC_MEX: No consultado")
                    elif tracmex_ok:
                        st.success("✅ TRAC_MEX: Certificación válida")
                    else:
                        st.error("❌ TRAC_MEX: Certificación no válida")

                if tracmex_msg:
                    tracmex_placeholder.info(f"**TRAC_MEX:** {tracmex_msg}")

                # --- POST a PI cada 5 segundos ---
                pi_result = send_to_pi(employee_number, access_granted)
                value_sent = employee_number if access_granted else "0"
                if pi_result.get("ok"):
                    pi_msg = f"✅ Enviado ME14764-AXN.User|{value_sent}"
                elif pi_result.get("error"):
                    pi_msg = f"❌ Error: {pi_result['error']}"
                else:
                    pi_msg = f"❌ HTTP {pi_result['status']}"
                pi_placeholder.caption(f"📡 PI: {pi_msg}")
                time_placeholder.caption(f"🕐 Última verificación: {time.strftime('%H:%M:%S')}")

            # ~15 FPS para video fluido sin saturar CPU
            time.sleep(0.066)

    finally:
        cap.release()
        # Siempre enviar 0 a PI al terminar (por detención, error o cierre)
        send_to_pi(employee_number, False)


def main():
    init_db()

    st.title("Sistema Biométrico Facial")
    st.markdown(
        "V.0.0.1 | Arquitectura desacoplada: UI Streamlit + motor biométrico separado + "
        "múltiples muestras por identidad + quality gate + verificación 1:1."
    )

    # --- Gate de autenticación ---
    from repository import verify_admin_credentials

    if "app_role" not in st.session_state:
        st.session_state.app_role = None  # None | "admin" | "operator"

    if st.session_state.app_role is None:
        st.sidebar.header("Acceso")
        access_mode = st.sidebar.radio(
            "Selecciona tu rol",
            ["Operador", "Administrador"],
            key="access_mode_radio",
        )

        if access_mode == "Administrador":
            st.sidebar.markdown("---")
            username = st.sidebar.text_input("Usuario", key="app_login_user")
            password = st.sidebar.text_input("Contraseña", type="password", key="app_login_pass")
            if st.sidebar.button("🔑 Iniciar Sesión", use_container_width=True):
                if verify_admin_credentials(username, password):
                    st.session_state.app_role = "admin"
                    st.rerun()
                else:
                    st.sidebar.error("❌ Credenciales incorrectas")
            # Main area message
            st.info("🔑 Ingresa tus credenciales de administrador en la barra lateral para acceder.")
        else:
            if st.sidebar.button("▶️ Entrar como Operador", use_container_width=True):
                st.session_state.app_role = "operator"
                st.rerun()
            st.info("👷 Presiona **Entrar como Operador** en la barra lateral para iniciar.")
        return

    # --- Operador: solo verificación en tiempo real ---
    if st.session_state.app_role == "operator":
        st.sidebar.markdown(f"**Rol:** 👷 Operador")
        if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state.app_role = None
            st.session_state.operator_active = False
            st.session_state.operator_status = None
            st.rerun()
        render_operator_section()
        return

    # --- Administrador: menú completo ---
    st.sidebar.markdown(f"**Rol:** 🔑 Administrador")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.app_role = None
        st.rerun()

    menu = st.sidebar.selectbox(
        "Menu",
        [
            "Enrolamiento de Muestras",
            "Verificación 1:1",
            "Gestión de Registros",
            "Calibración",
            "TRAC_MEX",
            "DB",
        ],
    )

    if menu == "Enrolamiento de Muestras":
        render_register_section()
    elif menu == "Verificación 1:1":
        render_verify_section()
    elif menu == "Gestión de Registros":
        render_management_section()
    elif menu == "Calibración":
        render_calibration_section()
    elif menu == "TRAC_MEX":
        render_tracmex_section()
    elif menu == "DB":
        render_database_section()

if __name__ == "__main__":
    main()