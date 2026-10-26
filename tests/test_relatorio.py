import re
from pathlib import Path

import pymupdf

import fabrica_pdfs as f
from auditoria_contratos.auditoria import auditar
from auditoria_contratos.regras import catalogo
from auditoria_contratos.relatorio.gerador import carregar_perfil, gerar

PACOTE = Path(__file__).resolve().parent.parent / "auditoria_contratos"


def test_toda_regra_usada_no_codigo_existe_no_catalogo():
    usadas = set()
    for arquivo in PACOTE.rglob("*.py"):
        usadas |= set(re.findall(r'achado\(\s*"([A-Z]{3}-\d{2})"', arquivo.read_text(encoding="utf-8")))
    assert usadas, "nenhuma regra encontrada no código"
    assert usadas <= set(catalogo()), usadas - set(catalogo())


def test_gera_relatorio_completo(tmp_path, pasta, assinado, confianca_teste):
    alterado = f.alterar_depois(assinado, pasta / "para_relatorio.pdf")
    perfil_yaml = tmp_path / "perfil.yaml"
    perfil_yaml.write_text("responsavel:\n  nome: Fulana de Teste\n  registro: OAB/SP 000.000\n", encoding="utf-8")
    perfil = carregar_perfil(perfil_yaml)
    r = auditar(alterado, confianca_teste)
    destino = gerar(r, alterado.read_bytes(), tmp_path / "saida", perfil, {"processo": "0000000-00.2026.8.26.0000"})

    for nome in ("relatorio.pdf", "relatorio.html", "dados.json", "HASHES-SHA256.txt",
                 "versoes/versao-1.pdf", "versoes/versao-2.pdf"):
        assert (destino / nome).is_file(), nome

    with pymupdf.open(destino / "relatorio.pdf") as d:
        texto = "".join(p.get_text() for p in d)
        assert d.page_count >= 6
    assert "Fulana de Teste" in texto
    assert "0000000-00.2026.8.26.0000" in texto
    assert "VERMELHO" in texto
    assert r.arquivo["hashes"]["sha256"] in texto.replace("\n", "")

    hashes = (destino / "HASHES-SHA256.txt").read_text(encoding="utf-8")
    assert r.arquivo["hashes"]["sha256"] in hashes
    assert "relatorio.pdf" in hashes
