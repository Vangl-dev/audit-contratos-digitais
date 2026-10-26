#!/usr/bin/env bash
# Instala o programa num ambiente Python próprio (.venv) dentro desta pasta.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[testes]"
[ -f perfil.yaml ] || cp perfil.exemplo.yaml perfil.yaml
echo
[ "$(uname)" = "Linux" ] && scripts/instalar_atalhos.sh
echo "Pronto. Para abrir: ./abrir.sh (ou pelo menu de aplicativos)"
echo "Preencha seus dados em perfil.yaml ou no botão \"Meus dados\" da janela."
