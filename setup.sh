#!/bin/bash
# Script de instalación del proyecto SHCP
# Ejecutar: bash setup.sh

set -e

echo "=== Configurando entorno virtual ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Instalando dependencias ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Configurando Streamlit ==="
mkdir -p .streamlit
cat > .streamlit/config.toml << 'EOF'
[server]
headless = true
port = 8501
address = "localhost"
maxUploadSize = 200

[theme]
primaryColor = "#BC955C"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#10312B"
font = "sans serif"

[browser]
gatherUsageStats = false
EOF

echo ""
echo "=== Instalación completa ==="
echo "Para ejecutar: source venv/bin/activate && streamlit run app.py"
