@echo off
title Sistema Biometrico Facial
echo ============================================================
echo   Sistema Biometrico Facial - Kimball Electronics
echo ============================================================
echo.

:: Activar entorno virtual
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [ERROR] Entorno virtual no encontrado.
    echo   Ejecuta INSTALAR.bat primero.
    pause
    exit /b 1
)

:: Verificar que streamlit existe
streamlit --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Streamlit no esta instalado.
    echo   Ejecuta INSTALAR.bat primero.
    pause
    exit /b 1
)

echo Iniciando aplicacion...
echo   La aplicacion se abrira en tu navegador automaticamente.
echo   URL: http://localhost:8501
echo.
echo   Para detener la aplicacion cierra esta ventana o presiona Ctrl+C.
echo ============================================================
echo.

streamlit run app.py --server.port=8501 --server.headless=true --browser.gatherUsageStats=false --theme.base=light
