#!/bin/sh
# Inicia o sistema de orçamentos no Linux ou macOS
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
echo "Abra http://127.0.0.1:5000 no navegador"
.venv/bin/python app.py
