"""
Hashes citados no texto do documento.

Plataformas de assinatura costumam imprimir, na página de trilha de
auditoria, o hash do arquivo assinado. Aqui esses valores são procurados no
texto e conferidos com o arquivo, com cada uma de suas versões e com os
arquivos anexados.
"""

import re

import pymupdf

from ..documento import Documento, calcular_hashes, ALGORITMOS_CITACAO
from ..modelos import Achado
from ..regras import achado

TAMANHOS = {32: "MD5", 40: "SHA-1", 64: "SHA-256", 128: "SHA-512"}
NOME_ALG = {"md5": "MD5", "sha1": "SHA-1", "sha256": "SHA-256", "sha512": "SHA-512"}

# Hash quebrado em duas linhas: junta pedaços hexadecimais separados por quebra de linha
QUEBRA_HEX = re.compile(r"(?<=[0-9a-fA-F]{8})[ \t]*\r?\n[ \t]*(?=[0-9a-fA-F]{8})")
HEX = re.compile(r"(?<![0-9a-zA-Z])([0-9a-fA-F]{32,128})(?![0-9a-zA-Z])")


def _candidatos(texto: str) -> list[tuple[str, str]]:
    texto = QUEBRA_HEX.sub("", texto)
    achados = []
    for m in HEX.finditer(texto):
        valor = m.group(1)
        if len(valor) not in TAMANHOS or valor.isdigit():
            continue
        antes = texto[max(0, m.start() - 80): m.start()]
        contexto = " ".join(antes.split()[-8:])
        achados.append((valor.lower(), contexto))
    return achados


def verificar(doc: Documento, anexos: list[dict]) -> tuple[list[Achado], list[dict]]:
    achados: list[Achado] = []
    try:
        with pymupdf.open(stream=doc.dados, filetype="pdf") as d:
            paginas = [(p.number + 1, p.get_text()) for p in d]
    except Exception:
        return achados, []

    referencias = {}
    for v in doc.versoes:
        descricao = "o arquivo analisado" if v.numero == len(doc.versoes) else f"a versão {v.numero} do arquivo"
        for alg, valor in calcular_hashes(doc.dados_da_versao(v.numero), ALGORITMOS_CITACAO).items():
            referencias.setdefault(valor, (descricao, alg))
    for anexo in anexos:
        for alg, valor in anexo["hashes"].items():
            referencias.setdefault(valor, (f"o anexo \"{anexo['nome']}\"", alg))

    resultado = []
    vistos = set()
    for pagina, texto in paginas:
        for valor, contexto in _candidatos(texto):
            if valor in vistos:
                continue
            vistos.add(valor)
            confere = referencias.get(valor)
            item = {
                "pagina": pagina,
                "valor": valor,
                "tipo_provavel": TAMANHOS[len(valor)],
                "contexto": contexto,
                "confere_com": confere[0] if confere else None,
                "algoritmo": NOME_ALG[confere[1]] if confere else None,
            }
            resultado.append(item)
            ev = {"Página": pagina, "Hash citado": valor, "Texto antes do hash": contexto}
            if confere:
                achados.append(achado("HSH-01", f"O hash {TAMANHOS[len(valor)]} citado na página {pagina} "
                                                f"confere com {confere[0]}.", **ev))
            else:
                achados.append(achado("HSH-02", f"O hash citado na página {pagina} não confere com o arquivo, "
                                                f"suas versões ou anexos.", **ev))
    return achados, resultado
