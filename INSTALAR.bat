@echo off
title Sistema Biometrico Facial - Instalador
echo ============================================================
echo   INSTALADOR - Sistema Biometrico Facial
echo   Kimball Electronics
echo ============================================================
echo.

:: Verificar si Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado.
    echo.
    echo Descarga Python 3.10+ desde https://www.python.org/downloads/
    echo IMPORTANTE: Marca la casilla "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

echo [OK] Python encontrado:
python --version
echo.

:: Verificar ODBC Driver
reg query "HKLM\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ADVERTENCIA] ODBC Driver 17 for SQL Server no encontrado.
    echo   La conexion a TRAC_MEX no funcionara sin este driver.
    echo   Descarga: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
    echo.
)

:: Crear entorno virtual
echo [1/4] Creando entorno virtual...
if not exist "venv" (
    python -m venv venv
    echo   Entorno virtual creado.
) else (
    echo   Entorno virtual ya existe, reutilizando.
)
echo.

:: Activar entorno virtual
echo [2/4] Activando entorno virtual...
call venv\Scripts\activate.bat
echo.

:: Instalar dependencias
echo [3/4] Instalando dependencias (esto puede tardar varios minutos)...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Hubo un error instalando dependencias.
    echo   Verifica tu conexion a internet e intenta de nuevo.
    pause
    exit /b 1
)
echo.

:: Instalar face_recognition (requiere cmake y dlib)
echo [4/4] Verificando dependencias especiales...
pip install cmake >nul 2>&1
pip install dlib >nul 2>&1
pip install face_recognition >nul 2>&1
echo.

:: Crear directorios necesarios
if not exist "data" mkdir data
if not exist "reference_images" mkdir reference_images

echo ============================================================
echo   INSTALACION COMPLETADA EXITOSAMENTE
echo ============================================================
echo.
echo   Para iniciar la aplicacion ejecuta: INICIAR.bat
echo.
pause
