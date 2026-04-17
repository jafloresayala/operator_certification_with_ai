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
from camera_input_live import camera_input_live

from settings import SETTINGS, get_tracmex_process_id, set_tracmex_process_id
from repository import init_db, list_employees_df, get_employee_by_number, get_db_connection as _get_db_conn
from services import enroll_sample_for_employee, verify_employee_one_to_one, identify_faces_in_frame
from biometric_engine import ArcFaceEngine
from biometric_models import LivenessResult

st.set_page_config(page_title="Sistema Biométrico Facial", layout="wide")


def fetch_tress_employee(employee_number: str) -> Optional[Dict[str, Any]]:
    """Consulta la API de TRESS para obtener datos del empleado."""
    import requests
    try:
        resp = requests.get(
            SETTINGS.TRESS_API_URL,
            params={"EmployeeNumber": employee_number},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and data.get("EmployeeNumber"):
                return data
        return None
    except Exception as e:
        print(f"Error consultando TRESS API: {e}")
        return None

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
    Formulario simplificado: ingresa número de empleado → consulta TRESS API → confirma datos → enrolamiento.
    """

    # Inicializar estado del formulario
    if "form_wizard_step" not in st.session_state:
        st.session_state.form_wizard_step = 0
        st.session_state.form_wizard_data = {
            "employee_number": "",
            "name": "",
            "first_name": "",
            "last_name": "",
            "middle_name": "",
            "user_id": "",
            "email": "",
            "level": "",
            "role_code": "",
            "role_description": "",
            "cost_center_code": "",
            "cost_center_description": "",
            "shift_code": "",
            "shift_description": "",
            "supervisor_role": "",
            "status": "Activo",
            "uses_glasses": False,
            "notes": "",
        }
        st.session_state.form_wizard_errors = {}
        st.session_state.tress_fetched = False
    
    form_data = st.session_state.form_wizard_data
    errors = st.session_state.form_wizard_errors
    current_step = st.session_state.form_wizard_step
    
    steps = [
        {"title": "🔢 Número de Empleado", "emoji": "🔢"},
        {"title": "📋 Datos del Empleado (TRESS)", "emoji": "📋"},
        {"title": "👓 Confirmación", "emoji": "✅"},
    ]
    
    # Barra de progreso
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        progress_text = f"Paso {current_step + 1} de {len(steps)}"
        st.progress((current_step + 1) / len(steps), text=progress_text)
    
    step_indicators = " → ".join(
        [f"{'**' if i == current_step else ''}{s['emoji']}{' ←' if i == current_step else ''}" for i, s in enumerate(steps)]
    )
    st.markdown(f"<div style='text-align: center; font-size: 20px;'>{step_indicators}</div>", unsafe_allow_html=True)
    
    st.subheader(steps[current_step]["title"])
    st.markdown("---")
    
    # ==========================================
    # PASO 0: Número de Empleado
    # ==========================================
    if current_step == 0:
        st.markdown("Ingresa el número de empleado. Los datos se cargarán automáticamente desde TRESS.")
        
        form_data["employee_number"] = st.text_input(
            "🔢 Número de empleado",
            value=form_data["employee_number"],
            key="step0_employee_number"
        ).strip()
        
        valid, msg = validate_employee_number(form_data["employee_number"])
        if not valid and form_data["employee_number"]:
            st.error(f"❌ {msg}")
            errors["employee_number"] = msg
        else:
            errors.pop("employee_number", None)
        
        # Verificar si ya existe en la base de datos
        if form_data["employee_number"] and "employee_number" not in errors:
            conn = _get_db_conn()
            try:
                existing = get_employee_by_number(conn, form_data["employee_number"])
            finally:
                conn.close()
            if existing:
                st.error(f"❌ El empleado #{form_data['employee_number']} ya está registrado en el sistema ({existing['name']}).")
                errors["employee_number"] = "Ya existe"
        
        step_valid = len(errors) == 0 and bool(form_data["employee_number"])
        
        if not step_valid and "employee_number" not in errors:
            st.warning("⚠️ Ingresa un número de empleado válido")
    
    # ==========================================
    # PASO 1: Datos de TRESS (auto-llenado + editable)
    # ==========================================
    elif current_step == 1:
        # Consultar TRESS si aún no se ha hecho
        if not st.session_state.tress_fetched:
            with st.spinner("🔄 Consultando datos en TRESS..."):
                tress_data = fetch_tress_employee(form_data["employee_number"])
            
            if tress_data:
                form_data["name"] = tress_data.get("PrettyName", "")
                form_data["first_name"] = tress_data.get("FirstName", "")
                form_data["last_name"] = tress_data.get("LastName", "")
                form_data["middle_name"] = tress_data.get("MiddleName", "")
                form_data["user_id"] = tress_data.get("UserID", "")
                form_data["email"] = tress_data.get("Email", "")
                form_data["level"] = tress_data.get("Level", "")
                form_data["role_code"] = tress_data.get("RoleCode", "")
                form_data["role_description"] = tress_data.get("RoleDescription", "")
                form_data["cost_center_code"] = tress_data.get("CostCenterCode", "")
                form_data["cost_center_description"] = tress_data.get("CostCenterDescription", "")
                form_data["shift_code"] = tress_data.get("ShiftCode", "")
                form_data["shift_description"] = tress_data.get("ShiftDescription", "")
                form_data["supervisor_role"] = tress_data.get("SupervisorRole", "")
                st.session_state.tress_fetched = True
                st.success("✅ Datos cargados desde TRESS")
            else:
                st.error("❌ El número de empleado no existe en TRESS. Verifica el número e intenta de nuevo.")
                st.session_state.tress_fetched = False
                st.session_state.form_wizard_step = 0
                import time; time.sleep(2)
                st.rerun()
                return
        
        st.markdown("Verifica y ajusta los datos del empleado.")
        
        col1, col2 = st.columns(2)
        with col1:
            form_data["name"] = st.text_input("👤 Nombre completo", value=form_data["name"], key="step1_name")
            form_data["first_name"] = st.text_input("Nombre(s)", value=form_data["first_name"], key="step1_first_name")
            form_data["last_name"] = st.text_input("Apellido paterno", value=form_data["last_name"], key="step1_last_name")
            form_data["middle_name"] = st.text_input("Apellido materno", value=form_data["middle_name"], key="step1_middle_name")
            form_data["user_id"] = st.text_input("🆔 User ID", value=form_data["user_id"], key="step1_user_id")
            form_data["email"] = st.text_input("📧 Correo", value=form_data["email"], key="step1_email")
            form_data["level"] = st.text_input("📊 Nivel", value=form_data["level"], key="step1_level")
        
        with col2:
            form_data["role_code"] = st.text_input("Código de rol", value=form_data["role_code"], key="step1_role_code")
            form_data["role_description"] = st.text_input("👔 Rol", value=form_data["role_description"], key="step1_role_desc")
            form_data["cost_center_code"] = st.text_input("Código centro costos", value=form_data["cost_center_code"], key="step1_cc_code")
            form_data["cost_center_description"] = st.text_input("🏢 Centro de costos", value=form_data["cost_center_description"], key="step1_cc_desc")
            form_data["shift_code"] = st.text_input("Código de turno", value=form_data["shift_code"], key="step1_shift_code")
            form_data["shift_description"] = st.text_input("⏰ Turno", value=form_data["shift_description"], key="step1_shift_desc")
            form_data["supervisor_role"] = st.text_input("👑 Rol de supervisor (S/N)", value=form_data["supervisor_role"], key="step1_supervisor")
        
        step_valid = bool(form_data["name"])
        if not step_valid:
            st.warning("⚠️ El nombre es obligatorio")
    
    # ==========================================
    # PASO 2: Confirmación
    # ==========================================
    elif current_step == 2:
        st.markdown("Confirma la información y opciones adicionales.")
        
        form_data["uses_glasses"] = st.checkbox(
            "👓 El candidato usa lentes normalmente",
            value=form_data["uses_glasses"],
            key="step2_glasses"
        )
        
        form_data["status"] = st.selectbox(
            "📊 Estatus",
            ["Activo", "Inactivo", "Baja"],
            index=["Activo", "Inactivo", "Baja"].index(form_data["status"]),
            key="step2_status"
        )
        
        form_data["notes"] = st.text_area(
            "📝 Notas adicionales (opcional)",
            value=form_data["notes"],
            height=100,
            key="step2_notes"
        ).strip()
        
        st.markdown("---")
        st.markdown("### 📋 Resumen de Datos")
        
        summary_cols = st.columns(2)
        with summary_cols[0]:
            st.write(f"**No. Empleado:** {form_data['employee_number']}")
            st.write(f"**Nombre:** {form_data['name']}")
            st.write(f"**User ID:** {form_data['user_id']}")
            st.write(f"**Email:** {form_data['email']}")
            st.write(f"**Nivel:** {form_data['level']}")
        
        with summary_cols[1]:
            st.write(f"**Rol:** {form_data['role_description']}")
            st.write(f"**Centro de Costos:** {form_data['cost_center_description']}")
            st.write(f"**Turno:** {form_data['shift_description']}")
            st.write(f"**Supervisor:** {form_data['supervisor_role']}")
            st.write(f"**Usa lentes:** {'Sí' if form_data['uses_glasses'] else 'No'}")
        
        step_valid = True
    
    # ==========================================
    # Botones de Navegación
    # ==========================================
    st.markdown("---")
    nav_cols = st.columns([1, 1, 1, 1, 1])
    
    with nav_cols[0]:
        if st.button("⬅️ Atrás", width='stretch', disabled=(current_step == 0)):
            if current_step == 1:
                st.session_state.tress_fetched = False
            st.session_state.form_wizard_step = current_step - 1
            st.rerun()
    
    with nav_cols[4]:
        if current_step < len(steps) - 1:
            if st.button("➡️ Siguiente", width='stretch', disabled=(not step_valid)):
                st.session_state.form_wizard_step = current_step + 1
                st.rerun()
        else:
            if st.button("✅ Iniciar Enrolamiento Guiado", width='stretch', type="primary", disabled=(not step_valid)):
                if not form_data["employee_number"] or not form_data["name"]:
                    st.error("❌ Número de empleado y nombre son obligatorios.")
                    return
                
                uses_glasses = form_data.pop("uses_glasses")
                employee_data_clean = {k: v for k, v in form_data.items() if k != "uses_glasses"}
                
                plan = get_guided_enrollment_plan(uses_glasses)
                
                st.session_state.guided_enrollment = {
                    "started": True,
                    "employee_data": employee_data_clean,
                    "uses_glasses": uses_glasses,
                    "plan": plan,
                    "step_idx": 0,
                    "completed_samples": [],
                }
                
                del st.session_state.form_wizard_step
                del st.session_state.form_wizard_data
                if "tress_fetched" in st.session_state:
                    del st.session_state.tress_fetched
                
                st.rerun()

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
            st.dataframe(summary_df, width='stretch', hide_index=True)

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
                width='stretch',
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
            width='stretch',
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
            width='stretch',
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
            if st.button("⬅️ Volver al Formulario", width='stretch'):
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
            st.image(image, caption="Foto capturada", width='stretch')
        
        with col2:
            st.subheader("Parámetros de Verificación")
            st.metric("Numero de Empleado", employee_number or "No especificado")
            st.metric("Threshold", f"{threshold:.2f}")
        
        st.divider()
        
        # Botón para verificar
        if st.button("🔍 Verificar Identidad", type="primary", width='stretch'):
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

            # Obtener nombre del empleado
            _conn = _get_db_conn()
            _emp = get_employee_by_number(_conn, employee_number.strip())
            _conn.close()
            emp_name = _emp["name"] if _emp else "Desconocido"

            # Enviar resultado a PI
            with st.spinner("📡 Enviando resultado a PI..."):
                pi_result = send_to_pi(employee_number.strip(), access_granted, emp_name)

            # Resultado principal - GRANDE Y CLARO
            if access_granted:
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
    st.dataframe(df, width='stretch', hide_index=True)

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
                if st.button("Ingresar", type="primary", width='stretch'):
                    if verify_admin_credentials(username, password):
                        st.session_state.db_authenticated = True
                        st.success("✅ Autenticación exitosa")
                        st.rerun()
                    else:
                        st.error("❌ Usuario o contraseña incorrectos")
            
            with col_cancel:
                if st.button("Cancelar", width='stretch'):
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
        if st.button("🚪 Cerrar Sesión", width='stretch'):
            st.session_state.db_authenticated = False
            st.rerun()
    
    st.markdown("---")
    
    # Selector de operación
    operation = st.radio(
        "Selecciona una operación:",
        ["Ver Empleados", "Editar Empleado", "Eliminar Empleado"],
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
                st.dataframe(employees_df, width='stretch', hide_index=True)
                
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
                employee_options = [f"{row['employee_number']} - {row['name']}" for _, row in employees_df.iterrows()]
                selected_option = st.selectbox("Selecciona un empleado", employee_options)
                
                selected_idx = employee_options.index(selected_option)
                selected_employee = employees_df.iloc[selected_idx].to_dict()
                
                st.markdown("---")
                st.write(f"**ID:** {selected_employee['id']}")
                st.write(f"**Número de Empleado:** {selected_employee['employee_number']}")
                st.write(f"**Fecha de Registro:** {selected_employee['registration_date']}")
                
                # Botón para recargar datos desde TRESS
                if st.button("🔄 Recargar datos desde TRESS"):
                    with st.spinner("Consultando TRESS..."):
                        tress_data = fetch_tress_employee(str(selected_employee['employee_number']))
                    if tress_data:
                        updated = {
                            "name": tress_data.get("PrettyName", ""),
                            "first_name": tress_data.get("FirstName", ""),
                            "last_name": tress_data.get("LastName", ""),
                            "middle_name": tress_data.get("MiddleName", ""),
                            "user_id": tress_data.get("UserID", ""),
                            "email": tress_data.get("Email", ""),
                            "level": tress_data.get("Level", ""),
                            "role_code": tress_data.get("RoleCode", ""),
                            "role_description": tress_data.get("RoleDescription", ""),
                            "cost_center_code": tress_data.get("CostCenterCode", ""),
                            "cost_center_description": tress_data.get("CostCenterDescription", ""),
                            "shift_code": tress_data.get("ShiftCode", ""),
                            "shift_description": tress_data.get("ShiftDescription", ""),
                            "supervisor_role": tress_data.get("SupervisorRole", ""),
                        }
                        if update_employee(conn, selected_employee['id'], updated):
                            st.success("✅ Datos actualizados desde TRESS")
                            st.rerun()
                    else:
                        st.error("No se encontró información en TRESS")
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("👤 Nombre completo", value=selected_employee.get('name', '') or '')
                    first_name = st.text_input("Nombre(s)", value=selected_employee.get('first_name', '') or '')
                    last_name = st.text_input("Apellido paterno", value=selected_employee.get('last_name', '') or '')
                    middle_name = st.text_input("Apellido materno", value=selected_employee.get('middle_name', '') or '')
                    user_id = st.text_input("🆔 User ID", value=selected_employee.get('user_id', '') or '')
                    email = st.text_input("📧 Correo", value=selected_employee.get('email', '') or '')
                    level = st.text_input("📊 Nivel", value=selected_employee.get('level', '') or '')
                
                with col2:
                    role_code = st.text_input("Código de rol", value=selected_employee.get('role_code', '') or '')
                    role_description = st.text_input("👔 Rol", value=selected_employee.get('role_description', '') or '')
                    cost_center_code = st.text_input("Código centro costos", value=selected_employee.get('cost_center_code', '') or '')
                    cost_center_description = st.text_input("🏢 Centro de costos", value=selected_employee.get('cost_center_description', '') or '')
                    shift_code = st.text_input("Código de turno", value=selected_employee.get('shift_code', '') or '')
                    shift_description = st.text_input("⏰ Turno", value=selected_employee.get('shift_description', '') or '')
                    supervisor_role = st.text_input("👑 Supervisor (S/N)", value=selected_employee.get('supervisor_role', '') or '')
                
                status_val = selected_employee.get('status', 'Activo') or 'Activo'
                status_idx = ["Activo", "Inactivo", "Baja"].index(status_val) if status_val in ["Activo", "Inactivo", "Baja"] else 0
                status = st.selectbox("📊 Estatus", ["Activo", "Inactivo", "Baja"], index=status_idx)
                notes = st.text_area("📝 Notas", value=selected_employee.get('notes', '') or '', height=100)
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Guardar Cambios", type="primary", width='stretch'):
                        updated_data = {
                            "name": name,
                            "first_name": first_name,
                            "last_name": last_name,
                            "middle_name": middle_name,
                            "user_id": user_id,
                            "email": email,
                            "level": level,
                            "role_code": role_code,
                            "role_description": role_description,
                            "cost_center_code": cost_center_code,
                            "cost_center_description": cost_center_description,
                            "shift_code": shift_code,
                            "shift_description": shift_description,
                            "supervisor_role": supervisor_role,
                            "status": status,
                            "notes": notes,
                        }
                        
                        if update_employee(conn, selected_employee['id'], updated_data):
                            st.success("✅ Empleado actualizado correctamente")
                            st.rerun()
                        else:
                            st.error("❌ Error al actualizar empleado")
                
                with col2:
                    if st.button("Cancelar", width='stretch'):
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
                    if st.button("❌ Confirmar Eliminación", type="secondary", width='stretch'):
                        if delete_employee(conn, selected_employee['id']):
                            st.success("✅ Empleado eliminado correctamente")
                            st.rerun()
                        else:
                            st.error("❌ Error al eliminar empleado")
                
                with col2:
                    if st.button("Cancelar", width='stretch'):
                        pass
        
        except Exception as e:
            st.error(f"Error en eliminación: {str(e)}")
    
    conn.close()


def send_to_pi(employee_number: str, access_granted: bool, employee_name: str = "") -> dict:
    """Envía el resultado de verificación al PI Web Service."""
    import requests

    value = employee_number if access_granted else "0"
    name_value = employee_name if access_granted and employee_name else "0"
    tag_user = f"ME14764-AXN.User|{value}"
    tag_name = f"ME14764-AXN.User_Name|{name_value}"

    pi_url = "http://nts5111/PI_FunctionalWS/PIWebService.asmx/Send_Functional_Master_To_PI"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        resp1 = requests.post(pi_url, data={"tag_and_value": tag_user}, headers=headers, timeout=10)
        resp2 = requests.post(pi_url, data={"tag_and_value": tag_name}, headers=headers, timeout=10)
        ok = resp1.status_code == 200 and resp2.status_code == 200
        return {"ok": ok, "status": resp1.status_code, "body": resp1.text, "error": None}
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

        submitted = st.form_submit_button("Consultar Estatus", width='stretch')

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


def render_tracmex_config_section():
    """Sección de administrador para configurar el Process ID de TRAC_MEX."""
    st.header("⚙️ Configuración TRAC_MEX")
    st.info(
        "Configura el **Process ID** que se usará en la validación automática del operador. "
        "Este valor se guarda de forma persistente y el operador **no puede modificarlo**."
    )

    current_pid = get_tracmex_process_id()

    st.metric("Process ID actual", current_pid)

    st.markdown("---")
    st.subheader("Cambiar Process ID")

    new_pid = st.number_input(
        "Nuevo Process ID",
        value=current_pid,
        step=1,
        key="admin_tracmex_pid",
    )

    if st.button("💾 Guardar Process ID", type="primary", width='stretch'):
        set_tracmex_process_id(int(new_pid))
        st.success(f"✅ Process ID actualizado a **{int(new_pid)}**")
        st.rerun()


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

def _process_identification(engine, frame_bgr, threshold, process_id):
    """Ejecuta identificación 1:N + TRAC_MEX + PI. Retorna (face_results, certified_employee, pi_msg, diagnostics)."""
    face_results = []
    certified_employee = None
    diagnostics = []

    id_results = identify_faces_in_frame(engine, frame_bgr, threshold)
    diagnostics.append(f"Rostros detectados: {len(id_results)}")

    for i, r in enumerate(id_results):
        entry = {
            "face_box": r["face_box"],
            "matched": r["matched"],
            "name": r["employee_name"],
            "emp_number": r["employee_number"],
            "certified": False,
        }

        dist_str = f"{r.get('distance', 'N/A'):.4f}" if isinstance(r.get('distance'), (int, float)) else "N/A"
        diagnostics.append(
            f"Rostro #{i+1}: matched={r['matched']}, "
            f"emp={r.get('employee_number', 'N/A')}, "
            f"name={r.get('employee_name', 'N/A')}, "
            f"distance={dist_str}, threshold={threshold}"
        )

        if r["matched"] and r["employee_number"]:
            tr = check_tracmex_access(r["employee_number"], process_id=process_id)
            diagnostics.append(
                f"  TRAC_MEX(user_id={r['employee_number']}, process_id={process_id}): "
                f"passed={tr.get('passed')}, msg={tr.get('message')}, err={tr.get('error')}"
            )
            if tr["passed"]:
                entry["certified"] = True
                if certified_employee is None:
                    certified_employee = r

        face_results.append(entry)

    # Enviar señal a PI
    if certified_employee:
        pi_result = send_to_pi(
            certified_employee["employee_number"], True,
            certified_employee["employee_name"]
        )
        value_sent = certified_employee["employee_number"]
    else:
        pi_result = send_to_pi("0", False)
        value_sent = "0"

    if pi_result.get("ok"):
        pi_msg = f"✅ Enviado ME14764-AXN.User|{value_sent}"
    elif pi_result.get("error"):
        pi_msg = f"❌ Error: {pi_result['error']}"
    else:
        pi_msg = f"❌ HTTP {pi_result['status']}"

    return face_results, certified_employee, pi_msg, diagnostics


def _render_identification_results(status_placeholder, detail_placeholder, pi_placeholder,
                                    time_placeholder, face_results, certified_employee, pi_msg,
                                    diagnostics=None):
    """Muestra los resultados de identificación en los placeholders."""
    status_placeholder.empty()
    detail_placeholder.empty()

    if not face_results:
        pi_placeholder.caption(f"📡 PI: {pi_msg}")
        time_placeholder.caption(f"🕐 Última verificación: {time.strftime('%H:%M:%S')}")
    else:
        with status_placeholder.container():
            if certified_employee:
                st.success(
                    f"## ✅ ACCESO PERMITIDO\n"
                    f"### 👤 {certified_employee['employee_name']}\n"
                    f"No. {certified_employee['employee_number']}"
                )
            else:
                st.error("## ❌ ACCESO DENEGADO")

        with detail_placeholder.container():
            for fr in face_results:
                if fr["certified"]:
                    st.success(f"✅ {fr['name']} — Certificación válida")
                elif fr["matched"]:
                    st.error(f"❌ {fr['name']} — Sin certificación TRAC_MEX")
                else:
                    st.warning(f"⚠️ Rostro no identificado (no coincide con ningún empleado)")

            if diagnostics:
                with st.expander("🔧 Diagnóstico detallado", expanded=False):
                    for line in diagnostics:
                        st.text(line)

        pi_placeholder.caption(f"📡 PI: {pi_msg}")
        time_placeholder.caption(f"🕐 Última verificación: {time.strftime('%H:%M:%S')}")


def _annotate_frame(frame_bgr, face_results):
    """Dibuja bounding boxes y etiquetas sobre el frame."""
    annotated = frame_bgr.copy()
    for fr in face_results:
        fb = fr["face_box"]
        top, right, bottom, left = fb.top, fb.right, fb.bottom, fb.left
        if fr["certified"]:
            color = (0, 255, 0)
            label = fr["name"] or "Certificado"
        elif fr["matched"]:
            color = (0, 0, 255)
            label = f"{fr['name'] or 'Sin cert.'} - NO CERT."
        else:
            color = (0, 0, 255)
            label = "DESCONOCIDO"

        cv2.rectangle(annotated, (left, top), (right, bottom), color, 3)
        cv2.rectangle(annotated, (left, bottom), (right, bottom + 35), color, -1)
        cv2.putText(annotated, label, (left + 6, bottom + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return annotated


def _render_operator_browser(engine, threshold, process_id):
    """Modo Navegador: usa camera_input_live con @st.fragment para evitar rerun global."""

    # Inicializar estado persistente una sola vez
    for key, default in [
        ("browser_last_verify_time", 0.0),
        ("browser_last_results", []),
        ("browser_last_certified", None),
        ("browser_last_pi_msg", ""),
        ("browser_last_diagnostics", []),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # --- Todo dentro del fragment para que se actualice junto ---
    @st.fragment(run_every=5)
    def _camera_fragment():
        col_cam, col_result = st.columns([1, 1])

        with col_cam:
            image = camera_input_live(
                key="operator_browser_cam",
                show_controls=False,
                debounce=4000,
            )

            if image is not None:
                pil_image = Image.open(image)
                frame_bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

                now = time.time()
                if now - st.session_state.browser_last_verify_time >= 5.0:
                    st.session_state.browser_last_verify_time = now
                    face_results, certified_employee, pi_msg, diag = _process_identification(
                        engine, frame_bgr, threshold, process_id
                    )
                    st.session_state.browser_last_results = face_results
                    st.session_state.browser_last_certified = certified_employee
                    st.session_state.browser_last_pi_msg = pi_msg
                    st.session_state.browser_last_diagnostics = diag

                # Anotar frame con los resultados actuales
                annotated = _annotate_frame(frame_bgr, st.session_state.browser_last_results)
                annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                st.image(annotated_rgb, channels="RGB", width="stretch")
            else:
                st.info("📷 Esperando cámara del navegador...")

        with col_result:
            face_results = st.session_state.browser_last_results
            certified_employee = st.session_state.browser_last_certified
            pi_msg = st.session_state.browser_last_pi_msg
            diagnostics = st.session_state.browser_last_diagnostics

            if not face_results and not pi_msg:
                st.info("📷 Video en vivo — verificación cada 5 segundos")
            else:
                if certified_employee:
                    st.success(
                        f"## ✅ ACCESO PERMITIDO\n"
                        f"### 👤 {certified_employee['employee_name']}\n"
                        f"No. {certified_employee['employee_number']}"
                    )
                else:
                    st.error("## ❌ ACCESO DENEGADO")

                for fr in face_results:
                    if fr["certified"]:
                        st.success(f"✅ {fr['name']} — Certificación válida")
                    elif fr["matched"]:
                        st.error(f"❌ {fr['name']} — Sin certificación TRAC_MEX")
                    else:
                        st.warning(f"⚠️ Rostro no identificado")

                if diagnostics:
                    with st.expander("🔧 Diagnóstico detallado", expanded=False):
                        for line in diagnostics:
                            st.text(line)

                st.caption(f"📡 PI: {pi_msg}")
                st.caption(f"🕐 Última verificación: {time.strftime('%H:%M:%S')}")

    _camera_fragment()


def render_operator_section():
    """Sección para operadores: identificación 1:N en tiempo real."""

    if "operator_active" not in st.session_state:
        st.session_state.operator_active = True

    process_id = get_tracmex_process_id()

    st.divider()

    engine = get_biometric_engine()
    if engine is None:
        st.error("❌ Motor biométrico no disponible.")
        return

    threshold = float(SETTINGS.DEFAULT_THRESHOLD)

    _render_operator_browser(engine, threshold, process_id)


def main():
    init_db()

    st.title("Facial Recognition with AI")

    # --- Gate de autenticación ---
    from repository import verify_admin_credentials

    if "app_role" not in st.session_state:
        st.session_state.app_role = "operator"  # Por defecto: operador
    if "operator_active" not in st.session_state:
        st.session_state.operator_active = True   # Webcam auto-encendida

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
            if st.sidebar.button("🔑 Iniciar Sesión", width='stretch'):
                if verify_admin_credentials(username, password):
                    st.session_state.app_role = "admin"
                    st.rerun()
                else:
                    st.sidebar.error("❌ Credenciales incorrectas")
            # Main area message
            st.info("🔑 Ingresa tus credenciales de administrador en la barra lateral para acceder.")
        else:
            if st.sidebar.button("▶️ Entrar como Operador", width='stretch'):
                st.session_state.app_role = "operator"
                st.rerun()
            st.info("👷 Presiona **Entrar como Operador** en la barra lateral para iniciar.")
        return

    # --- Operador: solo verificación en tiempo real ---
    if st.session_state.app_role == "operator":
        st.sidebar.markdown(f"**Rol:** 👷 Operador")
        if st.sidebar.button("🚪 Cerrar Sesión", width='stretch'):
            send_to_pi("0", False)  # reset PI al salir
            st.session_state.app_role = None
            st.session_state.operator_active = False
            st.rerun()
        render_operator_section()
        return

    # --- Administrador: menú completo ---
    st.sidebar.markdown(f"**Rol:** 🔑 Administrador")
    if st.sidebar.button("🚪 Cerrar Sesión", width='stretch'):
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
            "Configuración TRAC_MEX",
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
    elif menu == "Configuración TRAC_MEX":
        render_tracmex_config_section()
    elif menu == "DB":
        render_database_section()

if __name__ == "__main__":
    main()