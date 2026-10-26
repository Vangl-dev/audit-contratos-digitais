"""
Janela do programa: escolher o PDF, preencher a capa e gerar o relatório.
"""

import sys
from pathlib import Path

import yaml
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QCheckBox,
)

from . import __version__
from .auditoria import auditar
from .relatorio.gerador import carregar_perfil, gerar

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "perfil.yaml"
ICONE = Path(__file__).resolve().parent / "recursos" / "icone.svg"

CORES = {"VERDE": "#1d6b3a", "AMARELO": "#c07a0a", "VERMELHO": "#a8201a"}
CAMPOS_PERFIL = [
    ("nome", "Nome completo"),
    ("qualificacao", "Qualificação (ex.: Advogada)"),
    ("registro", "Registro (ex.: OAB/SP 000.000)"),
    ("escritorio", "Escritório"),
    ("email", "E-mail"),
    ("telefone", "Telefone"),
    ("cidade", "Cidade (linha de assinatura)"),
    ("logotipo", "Logotipo (PNG ou SVG)"),
]


class Trabalho(QThread):
    concluido = Signal(object, object)
    falhou = Signal(str)

    def __init__(self, arquivo: Path, caso: dict):
        super().__init__()
        self.arquivo, self.caso = arquivo, caso

    def run(self):
        try:
            perfil = carregar_perfil(PERFIL)
            mascarar = perfil["relatorio"].get("mascarar_documentos", True)
            resultado = auditar(self.arquivo, mascarar_documentos=mascarar)
            pasta = gerar(resultado, self.arquivo.read_bytes(), self.arquivo.resolve().parent, perfil, self.caso)
            self.concluido.emit(resultado, pasta)
        except Exception as e:
            self.falhou.emit(f"{type(e).__name__}: {e}")


class AreaArquivo(QFrame):
    escolhido = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setObjectName("area")
        self._estilo(False)
        layout = QVBoxLayout(self)
        self.rotulo = QLabel("Arraste o PDF do contrato para cá\nou clique para escolher")
        self.rotulo.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.rotulo)

    def _estilo(self, ativo: bool):
        cor = "#1f3a5f" if ativo else "#9aa4b2"
        self.setStyleSheet(f"#area {{ border: 2px dashed {cor}; border-radius: 8px; background: #f7f8fa; }}"
                           "QLabel { color: #4a5566; font-size: 13px; }")

    def mousePressEvent(self, evento):
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolher PDF", str(Path.home()), "PDF (*.pdf)")
        if caminho:
            self.escolhido.emit(Path(caminho))

    def dragEnterEvent(self, e: QDragEnterEvent):
        if any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self._estilo(True)

    def dragLeaveEvent(self, e):
        self._estilo(False)

    def dropEvent(self, e: QDropEvent):
        self._estilo(False)
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".pdf"):
                self.escolhido.emit(Path(u.toLocalFile()))
                return


class DialogoPerfil(QDialog):
    def __init__(self, pai):
        super().__init__(pai)
        self.setWindowTitle("Meus dados no relatório")
        self.setMinimumWidth(460)
        dados = yaml.safe_load(PERFIL.read_text(encoding="utf-8")) if PERFIL.is_file() else {}
        dados = dados or {}
        self.responsavel = dados.get("responsavel") or {}
        self.relatorio = dados.get("relatorio") or {"mascarar_documentos": True}

        form = QFormLayout(self)
        self.campos = {}
        for chave, rotulo in CAMPOS_PERFIL:
            campo = QLineEdit(str(self.responsavel.get(chave, "") or ""))
            self.campos[chave] = campo
            if chave == "logotipo":
                linha = QHBoxLayout()
                linha.addWidget(campo)
                botao = QPushButton("Escolher…")
                botao.clicked.connect(self._escolher_logo)
                linha.addWidget(botao)
                form.addRow(rotulo, linha)
            else:
                form.addRow(rotulo, campo)
        self.mascarar = QCheckBox("Mostrar CPF dos signatários mascarado (***.456.789-**)")
        self.mascarar.setChecked(bool(self.relatorio.get("mascarar_documentos", True)))
        form.addRow(self.mascarar)
        botoes = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)

    def _escolher_logo(self):
        caminho, _ = QFileDialog.getOpenFileName(self, "Logotipo", str(Path.home()), "Imagens (*.png *.svg *.jpg)")
        if caminho:
            self.campos["logotipo"].setText(caminho)

    def _salvar(self):
        dados = {
            "responsavel": {k: c.text().strip() for k, c in self.campos.items()},
            "relatorio": {**self.relatorio, "mascarar_documentos": self.mascarar.isChecked()},
        }
        PERFIL.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.accept()


class Janela(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Auditoria de Contratos Digitais {__version__}")
        self.setMinimumSize(720, 640)
        self.arquivo: Path | None = None
        self.pasta: Path | None = None
        self.trabalho = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        titulo = QLabel("Relatório Técnico de Integridade Documental")
        titulo.setFont(QFont(titulo.font().family(), 15, QFont.Bold))
        layout.addWidget(titulo)

        self.area = AreaArquivo()
        self.area.escolhido.connect(self._definir_arquivo)
        layout.addWidget(self.area)

        form = QFormLayout()
        self.processo = QLineEdit()
        self.processo.setPlaceholderText("opcional")
        self.referencia = QLineEdit()
        self.referencia.setPlaceholderText("opcional (ex.: Fulano × Banco X)")
        form.addRow("Número do processo", self.processo)
        form.addRow("Referência", self.referencia)
        layout.addLayout(form)

        botoes = QHBoxLayout()
        self.botao_perfil = QPushButton("Meus dados…")
        self.botao_perfil.clicked.connect(lambda: DialogoPerfil(self).exec())
        botoes.addWidget(self.botao_perfil)
        botoes.addStretch()
        self.botao_gerar = QPushButton("Gerar relatório")
        self.botao_gerar.setEnabled(False)
        self.botao_gerar.setMinimumHeight(34)
        self.botao_gerar.clicked.connect(self._gerar)
        botoes.addWidget(self.botao_gerar)
        layout.addLayout(botoes)

        self.selo = QLabel("")
        self.selo.setWordWrap(True)
        self.selo.setVisible(False)
        layout.addWidget(self.selo)

        self.lista = QListWidget()
        self.lista.setWordWrap(True)
        layout.addWidget(self.lista, 1)

        saida = QHBoxLayout()
        saida.addStretch()
        self.botao_pasta = QPushButton("Abrir pasta")
        self.botao_pdf = QPushButton("Abrir relatório")
        for b in (self.botao_pasta, self.botao_pdf):
            b.setEnabled(False)
            saida.addWidget(b)
        self.botao_pasta.clicked.connect(lambda: self._abrir(self.pasta))
        self.botao_pdf.clicked.connect(lambda: self._abrir(self.pasta / "relatorio.pdf"))
        layout.addLayout(saida)

        self.statusBar().showMessage("Escolha um PDF." if PERFIL.is_file()
                                     else "Dica: preencha \"Meus dados\" para o seu nome aparecer no relatório.")

    def _definir_arquivo(self, caminho: Path):
        self.arquivo = caminho
        self.area.rotulo.setText(f"{caminho.name}\n{caminho.parent}")
        self.botao_gerar.setEnabled(True)
        self.statusBar().showMessage("Pronto para gerar o relatório.")

    def _gerar(self):
        if not self.arquivo:
            return
        self.botao_gerar.setEnabled(False)
        self.lista.clear()
        self.selo.setVisible(False)
        self.statusBar().showMessage("Analisando… (documentos com muitas versões podem levar alguns minutos)")
        self.trabalho = Trabalho(self.arquivo, {"processo": self.processo.text().strip(),
                                                "referencia": self.referencia.text().strip()})
        self.trabalho.concluido.connect(self._concluido)
        self.trabalho.falhou.connect(self._falhou)
        self.trabalho.start()

    def _concluido(self, resultado, pasta: Path):
        self.pasta = pasta
        c = resultado.classificacao
        self.selo.setStyleSheet(f"QLabel {{ border: 1px solid {CORES[c.value]}; border-radius: 6px; padding: 10px; }}")
        self.selo.setText(f"<span style='background:{CORES[c.value]}; color:white; font-weight:bold'>"
                          f"&nbsp;{c.value}&nbsp;</span>&nbsp;&nbsp;{c.descricao}")
        self.selo.setVisible(True)
        for x in resultado.achados:
            item = QListWidgetItem(f"[{x.nivel.rotulo}]  {x.regra.titulo} — {x.resumo}")
            if x.nivel.value == "critico":
                item.setForeground(Qt.darkRed)
            elif x.nivel.value == "atencao":
                item.setForeground(Qt.darkYellow)
            elif x.nivel.value == "ok":
                item.setForeground(Qt.darkGreen)
            self.lista.addItem(item)
        self.botao_gerar.setEnabled(True)
        self.botao_pasta.setEnabled(True)
        self.botao_pdf.setEnabled(True)
        self.statusBar().showMessage(f"Relatório gravado em {pasta}")

    def _falhou(self, erro: str):
        self.botao_gerar.setEnabled(True)
        self.statusBar().showMessage("Erro na análise.")
        QMessageBox.critical(self, "Erro", f"Não foi possível gerar o relatório.\n\n{erro}")

    def _abrir(self, caminho: Path | None):
        if caminho:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(caminho)))


def abrir(arquivo: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Auditoria de Contratos Digitais")
    app.setDesktopFileName("auditoria-contratos-digitais")
    app.setWindowIcon(QIcon(str(ICONE)))
    janela = Janela()
    if arquivo is not None and Path(arquivo).is_file():
        janela._definir_arquivo(Path(arquivo).resolve())
    janela.show()
    return app.exec()
