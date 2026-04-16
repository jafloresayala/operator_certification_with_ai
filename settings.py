from dataclasses import dataclass
import os
import json

@dataclass(frozen=True)
class Settings:
    # Crear directorio 'data' en el raíz del proyecto (fuera del alcance de Streamlit cache)
    _data_dir: str = os.path.join(os.path.dirname(__file__), "data")
    
    DB_PATH: str = os.path.join(_data_dir, "database.db")
    REF_IMAGES_DIR: str = "reference_images"

    # ROI / UX
    ROI_WIDTH_RATIO: float = 0.46
    ROI_HEIGHT_RATIO: float = 0.62
    ROI_SAFE_MARGIN_RATIO: float = 0.08
    FACE_CROP_PADDING_RATIO: float = 0.20

    # Enrollment / muestras
    MIN_SAMPLES_PER_IDENTITY: int = 5
    MAX_SAMPLES_PER_IDENTITY: int = 12

    # Quality gate
    MIN_FACE_SIZE_PX: int = 120
    MIN_BRIGHTNESS: float = 45.0
    MAX_BRIGHTNESS: float = 210.0
    MAX_BLUR_VARIANCE_THRESHOLD: float = 50.0  # Laplacian variance, muy permisivo (sincronizado con biometric_engine)
    MAX_YAW_DEG: float = 18.0
    MAX_PITCH_DEG: float = 18.0

    # Calibración / operación
    DEFAULT_TARGET_FAR: float = 0.001  # ejemplo operativo
    DEFAULT_THRESHOLD: float = 0.40  # Reducido de 0.45 para mayor seguridad tras limpieza de datos

    # 1:1 preferido
    REQUIRE_EMPLOYEE_NUMBER_FOR_VERIFICATION: bool = True

    # TRAC_MEX API
    TRACMEX_API_URL: str = "http://nts5512/TracMexApi/api/StationInitialization/Get_User_Access_Status"
    TRACMEX_DEFAULT_PROCESS_ID: int = 50048

    # TRESS API (datos de empleados)
    TRESS_API_URL: str = "http://nts5102/TressWebAPI/api/EmployeeInfo/GetEmployeeInfo"


SETTINGS = Settings()

# Asegurarse de que los directorios existen
os.makedirs(SETTINGS._data_dir, exist_ok=True)
os.makedirs(SETTINGS.REF_IMAGES_DIR, exist_ok=True)

# --- Configuración persistente en data/config.json ---
_CONFIG_PATH = os.path.join(SETTINGS._data_dir, "config.json")

def _load_config() -> dict:
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_config(cfg: dict):
    with open(_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def get_tracmex_process_id() -> int:
    cfg = _load_config()
    return int(cfg.get("tracmex_process_id", SETTINGS.TRACMEX_DEFAULT_PROCESS_ID))

def set_tracmex_process_id(pid: int):
    cfg = _load_config()
    cfg["tracmex_process_id"] = pid
    _save_config(cfg)