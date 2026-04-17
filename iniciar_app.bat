@echo off
REM ============================================================
REM  Lanza la app de reconocimiento facial con camara habilitada
REM ============================================================

set APP_URL=http://localhost:8502
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"

echo [1/2] Abriendo Chrome con permisos de camara...
start "" %CHROME_PATH% --unsafely-treat-insecure-origin-as-secure="%APP_URL%" "%APP_URL%"

echo [2/2] Iniciando Streamlit...
echo      Presiona Ctrl+C para detener la aplicacion.
echo.
streamlit run app.py --server.port 8502
