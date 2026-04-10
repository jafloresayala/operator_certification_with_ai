"""
Script para descargar los modelos de InsightFace manualmente.
Útil cuando hay problemas de SSL o conexión.
"""

import os
import urllib.request
import zipfile
from pathlib import Path


def download_buffalo_model():
    """Descarga el modelo buffalo_l desde GitHub."""
    
    # URL del modelo
    model_url = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
    
    # Carpeta de destino
    home = Path.home()
    insightface_dir = home / '.insightface' / 'models'
    insightface_dir.mkdir(parents=True, exist_ok=True)
    
    zip_path = insightface_dir / 'buffalo_l.zip'
    extract_path = insightface_dir / 'buffalo_l'
    
    print(f"📥 Descargando modelo buffalo_l...")
    print(f"   URL: {model_url}")
    print(f"   Destino: {zip_path}")
    print()
    
    try:
        # Descargar con barra de progreso
        def download_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 // total_size, 100)
            bar = '█' * (percent // 2) + '░' * (50 - percent // 2)
            print(f"\r   Progreso: {bar} {percent}%", end='', flush=True)
        
        urllib.request.urlretrieve(model_url, zip_path, reporthook=download_progress)
        print("\n\n   ✓ Descarga completada\n")
        
        # Extraer
        print(f"📂 Extrayendo modelo...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        print(f"   ✓ Modelo extraído en: {extract_path}\n")
        
        # Verificar
        if extract_path.exists() and list(extract_path.glob('*.onnx')):
            print(f"✅ Éxito! Modelo instalado correctamente.")
            print(f"   Archivos encontrados:")
            for f in extract_path.glob('*'):
                print(f"   - {f.name}")
            print()
            print(f"   Ahora puedes iniciar la aplicación con:")
            print(f"   streamlit run app.py\n")
            return True
        else:
            print(f"❌ Error: No se encontraron archivos .onnx en {extract_path}")
            return False
            
    except Exception as e:
        print(f"\n❌ Error durante la descarga: {str(e)}")
        print(f"\nIntenta estas alternativas:")
        print(f"1. Descarga manualmente desde:")
        print(f"   {model_url}")
        print(f"2. Extrae en: {extract_path}")
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Descargador de Modelos InsightFace")
    print("=" * 60)
    print()
    
    success = download_buffalo_model()
    
    if not success:
        print("\n" + "=" * 60)
        print("Alternativamente, descarga manualmente:")
        print("=" * 60)
        home = Path.home()
        print(f"\n1. Ve a: https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip")
        print(f"2. Crea la carpeta: {home / '.insightface' / 'models' / 'buffalo_l'}")
        print(f"3. Extrae el ZIP en esa carpeta")
        print()
