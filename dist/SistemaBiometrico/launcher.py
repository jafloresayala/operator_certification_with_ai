"""
Launcher para ejecutar la aplicación Sistema Biométrico Facial.
Este archivo es el punto de entrada del ejecutable (.exe).
"""
import sys
import os

def get_app_dir():
    """Obtiene el directorio de la aplicación (funciona tanto en dev como en exe)."""
    if getattr(sys, 'frozen', False):
        # Ejecutable PyInstaller
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def main():
    app_dir = get_app_dir()
    os.chdir(app_dir)

    # Configurar variable para que settings.py use rutas relativas al exe
    os.environ["BIOMETRIC_APP_DIR"] = app_dir

    from streamlit.web import cli as stcli
    sys.argv = [
        "streamlit",
        "run",
        os.path.join(app_dir, "app.py"),
        "--server.headless=true",
        "--server.port=8501",
        "--browser.gatherUsageStats=false",
        "--theme.base=light",
    ]
    stcli.main()

if __name__ == "__main__":
    main()
