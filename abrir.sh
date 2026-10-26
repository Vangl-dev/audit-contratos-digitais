#!/usr/bin/env bash
# Abre a janela do programa, ou gera o relatório se receber um PDF:
#   ./abrir.sh                      janela
#   ./abrir.sh contrato.pdf         gera o relatório ao lado do PDF
#   ./abrir.sh --janela contrato.pdf
DIR="$(dirname "$(readlink -f "$0")")"
exec "$DIR/.venv/bin/python" -W ignore -m auditoria_contratos "$@"
