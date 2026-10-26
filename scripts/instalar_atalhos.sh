#!/usr/bin/env bash
# Cria, para o usuário atual (Linux):
#   - o atalho "Auditoria de Contratos Digitais" no menu de aplicativos
#   - o submenu no Dolphin (botão direito sobre um PDF)
# Para remover: scripts/instalar_atalhos.sh --remover
set -e
RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ID="auditoria-contratos-digitais"
APPS="$HOME/.local/share/applications"
MENUS="$HOME/.local/share/kio/servicemenus"
ICONES="$HOME/.local/share/icons/hicolor"

if [ "$1" = "--remover" ]; then
  rm -f "$APPS/$ID.desktop" "$MENUS/$ID.desktop" \
        "$ICONES/scalable/apps/$ID.svg" "$ICONES/256x256/apps/$ID.png" "$ICONES/64x64/apps/$ID.png"
  echo "Atalhos removidos."
  exit 0
fi

mkdir -p "$APPS" "$MENUS" "$ICONES/scalable/apps" "$ICONES/256x256/apps" "$ICONES/64x64/apps"
cp "$RAIZ/auditoria_contratos/recursos/icone.svg" "$ICONES/scalable/apps/$ID.svg"
cp "$RAIZ/auditoria_contratos/recursos/icone-256.png" "$ICONES/256x256/apps/$ID.png"
cp "$RAIZ/auditoria_contratos/recursos/icone-64.png" "$ICONES/64x64/apps/$ID.png"

cat > "$APPS/$ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Auditoria de Contratos Digitais
GenericName=Integridade de contratos em PDF
Comment=Relatório técnico de integridade documental de contratos eletrônicos
Exec="$RAIZ/abrir.sh" --janela %f
Path=$RAIZ
Icon=$ID
Terminal=false
MimeType=application/pdf;
Categories=Office;
Keywords=contrato;pdf;assinatura;icp-brasil;integridade;relatório;banco;
StartupWMClass=$ID
DESKTOP

cat > "$MENUS/$ID.desktop" <<MENU
[Desktop Entry]
Type=Service
MimeType=application/pdf;
Actions=gerarRelatorio;abrirJanela;
X-KDE-Submenu=Auditoria de Contratos Digitais
X-KDE-Priority=TopLevel
Icon=$ID

[Desktop Action gerarRelatorio]
Name=Gerar relatório de integridade
Icon=$ID
Exec=bash -c 'for f in "\$@"; do "$RAIZ/abrir.sh" --abrir "\$f"; done' _ %F

[Desktop Action abrirJanela]
Name=Abrir na janela (preencher processo)
Icon=$ID
Exec="$RAIZ/abrir.sh" --janela %f
MENU
chmod +x "$APPS/$ID.desktop" "$MENUS/$ID.desktop"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$ICONES" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

echo "Atalho criado no menu de aplicativos: Auditoria de Contratos Digitais"
echo "Dolphin: botão direito sobre um PDF > Auditoria de Contratos Digitais"
