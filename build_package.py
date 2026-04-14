"""
Script para empaquetar la aplicación en una carpeta distribuible.
Ejecutar: python build_package.py

Crea una carpeta 'dist/SistemaBiometrico/' lista para copiar a otra máquina.
"""
import os
import shutil

DIST_DIR = "dist"
PACKAGE_NAME = "SistemaBiometrico"
OUTPUT_DIR = os.path.join(DIST_DIR, PACKAGE_NAME)

# Archivos de la aplicación (solo los necesarios)
APP_FILES = [
    "app.py",
    "biometric_engine.py",
    "biometric_models.py",
    "calibration.py",
    "quality_gate.py",
    "repository.py",
    "services.py",
    "settings.py",
    "download_models.py",
    "launcher.py",
    "requirements.txt",
    "INSTALAR.bat",
    "INICIAR.bat",
]

# Directorios a copiar (con contenido)
APP_DIRS_WITH_CONTENT = [
    "data",
    "reference_images",
]

# Directorios a crear vacíos
APP_DIRS_EMPTY = []


def build():
    print("=" * 60)
    print("  Empaquetando Sistema Biométrico Facial")
    print("=" * 60)

    # Limpiar distribución anterior
    if os.path.exists(OUTPUT_DIR):
        print(f"\n[1] Limpiando distribución anterior...")
        # Windows: forzar permisos de escritura antes de eliminar
        import stat
        def force_remove_readonly(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(OUTPUT_DIR, onerror=force_remove_readonly)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Copiar archivos de aplicación
    print(f"\n[2] Copiando archivos de aplicación...")
    for f in APP_FILES:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(OUTPUT_DIR, f))
            print(f"    ✓ {f}")
        else:
            print(f"    ✗ {f} (no encontrado, omitido)")

    # Copiar directorios con contenido
    print(f"\n[3] Copiando directorios...")
    for d in APP_DIRS_WITH_CONTENT:
        src = d
        dst = os.path.join(OUTPUT_DIR, d)
        if os.path.exists(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            file_count = sum(len(files) for _, _, files in os.walk(dst))
            print(f"    ✓ {d}/ ({file_count} archivos)")
        else:
            os.makedirs(dst, exist_ok=True)
            print(f"    ✓ {d}/ (creado vacío)")

    # Crear directorios vacíos
    for d in APP_DIRS_EMPTY:
        dst = os.path.join(OUTPUT_DIR, d)
        os.makedirs(dst, exist_ok=True)
        print(f"    ✓ {d}/ (creado vacío)")

    # Crear archivo .streamlit/config.toml
    print(f"\n[4] Creando configuración de Streamlit...")
    streamlit_dir = os.path.join(OUTPUT_DIR, ".streamlit")
    os.makedirs(streamlit_dir, exist_ok=True)
    with open(os.path.join(streamlit_dir, "config.toml"), "w") as f:
        f.write("""[server]
headless = true
port = 8501
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
base = "light"
primaryColor = "#1f77b4"
""")
    print(f"    ✓ .streamlit/config.toml")

    # Resumen
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(OUTPUT_DIR):
        for fname in filenames:
            total_size += os.path.getsize(os.path.join(dirpath, fname))

    print(f"\n{'=' * 60}")
    print(f"  EMPAQUETADO COMPLETO")
    print(f"  Ubicación: {os.path.abspath(OUTPUT_DIR)}")
    print(f"  Tamaño: {total_size / (1024*1024):.1f} MB")
    print(f"{'=' * 60}")
    print(f"\n  Instrucciones:")
    print(f"  1. Copia la carpeta '{PACKAGE_NAME}' a la PC destino")
    print(f"  2. En la PC destino, ejecuta INSTALAR.bat")
    print(f"  3. Luego ejecuta INICIAR.bat para abrir la aplicación")
    print(f"\n  Prerequisitos en PC destino:")
    print(f"  - Python 3.10+ (con PATH configurado)")
    print(f"  - ODBC Driver 17 for SQL Server")
    print(f"  - Cámara conectada")
    print(f"  - Acceso a red (TRAC_MEX en NTS5562, PI en nts5111)")


if __name__ == "__main__":
    build()
