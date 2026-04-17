#!/bin/bash
# Genera certificado SSL autofirmado para nginx
# Ejecutar desde la raíz del proyecto

mkdir -p ssl

openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout ssl/selfsigned.key \
  -out ssl/selfsigned.crt \
  -subj "/C=MX/ST=Tamaulipas/L=Reynosa/O=Kimball Electronics/OU=IT/CN=face-recognition.local"

echo "Certificado generado en ssl/selfsigned.crt y ssl/selfsigned.key"
