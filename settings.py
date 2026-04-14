from dataclasses import dataclass
import os

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

    # TRAC_MEX SQL Server
    TRACMEX_SERVER: str = "NTS5562"
    TRACMEX_DATABASE: str = "TRAC_MEX"
    TRACMEX_USER: str = "tracmex_reader"
    TRACMEX_PASSWORD: str = r"GK<A{@g5n!"
    TRACMEX_APP_NAME: str = "TracMexApi"


SETTINGS = Settings()

# Asegurarse de que los directorios existen
os.makedirs(SETTINGS._data_dir, exist_ok=True)
os.makedirs(SETTINGS.REF_IMAGES_DIR, exist_ok=True)