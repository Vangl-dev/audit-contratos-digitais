"""
Uso pela linha de comando:

    python -m auditoria_contratos contrato.pdf
    python -m auditoria_contratos contrato.pdf --processo "1234567-89.2025.8.26.0100" --saida relatorios
    python -m auditoria_contratos contrato.pdf --abrir   (abre o relatório ao terminar)
    python -m auditoria_contratos --janela [contrato.pdf] (abre a janela)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .auditoria import auditar
from .relatorio.gerador import carregar_perfil, gerar

RAIZ = Path(__file__).resolve().parent.parent
ICONE = Path(__file__).resolve().parent / "recursos" / "icone.svg"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="auditoria_contratos", description="Relatório técnico de integridade de contrato em PDF.")
    p.add_argument("arquivo", nargs="?", type=Path, help="PDF a analisar")
    p.add_argument("--saida", type=Path, default=None,
                   help="pasta onde o relatório será criado (padrão: a pasta do próprio PDF)")
    p.add_argument("--perfil", type=Path, default=RAIZ / "perfil.yaml", help="arquivo com seus dados (nome, OAB)")
    p.add_argument("--processo", default="", help="número do processo, para a capa")
    p.add_argument("--referencia", default="", help="outra referência para a capa (ex.: partes)")
    p.add_argument("--confianca", type=Path, default=None, help="pasta de certificados de confiança")
    p.add_argument("--janela", action="store_true", help="abrir a interface gráfica")
    p.add_argument("--abrir", action="store_true", help="abrir o relatório em PDF ao terminar")
    args = p.parse_args(argv)

    if args.janela or args.arquivo is None:
        from .interface import abrir
        return abrir(args.arquivo)

    if not args.arquivo.is_file():
        _avisar(f"Arquivo não encontrado: {args.arquivo}", erro=True, notificar=args.abrir)
        return 2

    try:
        return _gerar(args)
    except Exception as e:
        _avisar(f"Não foi possível gerar o relatório: {type(e).__name__}: {e}", erro=True, notificar=args.abrir)
        return 1


def _avisar(mensagem: str, erro: bool = False, notificar: bool = False):
    print(mensagem, file=sys.stderr if erro else sys.stdout)
    if notificar and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Auditoria de Contratos Digitais", "-i", str(ICONE),
                        "Auditoria de Contratos Digitais", mensagem], check=False)


def _gerar(args) -> int:
    perfil = carregar_perfil(args.perfil)
    mascarar = perfil["relatorio"].get("mascarar_documentos", True)
    resultado = auditar(args.arquivo, args.confianca, mascarar_documentos=mascarar)
    saida = args.saida or args.arquivo.resolve().parent
    pasta = gerar(resultado, args.arquivo.read_bytes(), saida, perfil,
                  {"processo": args.processo, "referencia": args.referencia})

    print(f"Classificação: {resultado.classificacao.value} — {resultado.classificacao.descricao}")
    for x in resultado.achados:
        if x.nivel.value in ("critico", "atencao", "erro"):
            print(f"  [{x.nivel.rotulo}] {x.regra.id} {x.resumo}")
    print(f"\nRelatório gravado em: {pasta}")
    if args.abrir:
        _avisar(f"{resultado.classificacao.value}: {resultado.classificacao.descricao}", notificar=True)
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(pasta / "relatorio.pdf")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
