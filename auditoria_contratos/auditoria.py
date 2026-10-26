"""
Executa todas as verificações sobre um arquivo e reúne o resultado.
"""

import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import __version__, confianca
from .documento import Documento
from .modelos import Achado, Classificacao, Nivel
from .regras import achado
from .verificacoes import assinaturas, conteudo, hashes, metadados, versoes

BIBLIOTECAS = ("pyhanko", "pyhanko-certvalidator", "pikepdf", "pymupdf", "weasyprint")


@dataclass
class Auditoria:
    arquivo: dict
    achados: list[Achado]
    classificacao: Classificacao
    assinaturas: list[dict] = field(default_factory=list)
    versoes: list[dict] = field(default_factory=list)
    metadados: dict = field(default_factory=dict)
    conteudo: dict = field(default_factory=dict)
    hashes_citados: list[dict] = field(default_factory=list)
    metodologia: dict = field(default_factory=dict)

    def achados_por_nivel(self, *niveis: Nivel) -> list[Achado]:
        return [a for a in self.achados if a.nivel in niveis]

    def achados_da_secao(self, secao: str) -> list[Achado]:
        return [a for a in self.achados if a.regra.secao == secao]

    def to_dict(self) -> dict:
        versoes_sem_imagens = []
        for v in self.versoes:
            v = dict(v)
            if v.get("mudancas"):
                m = dict(v["mudancas"])
                m["paginas_alteradas"] = [
                    {k: x for k, x in p.items() if not k.startswith("imagem_")}
                    for p in m["paginas_alteradas"]
                ]
                v["mudancas"] = m
            versoes_sem_imagens.append(v)
        return {
            "arquivo": self.arquivo,
            "classificacao": self.classificacao.value,
            "achados": [a.to_dict() for a in self.achados],
            "assinaturas": self.assinaturas,
            "versoes": versoes_sem_imagens,
            "metadados": self.metadados,
            "conteudo": self.conteudo,
            "hashes_citados": self.hashes_citados,
            "metodologia": self.metodologia,
        }


def classificar(achados: list[Achado]) -> Classificacao:
    if any(a.nivel == Nivel.CRITICO for a in achados):
        return Classificacao.VERMELHO
    if any(a.nivel == Nivel.ATENCAO for a in achados):
        return Classificacao.AMARELO
    return Classificacao.VERDE


def _versao(pacote: str) -> str:
    try:
        return version(pacote)
    except PackageNotFoundError:
        return "não instalada"


def auditar(caminho: Path, pasta_confianca: Path | None = None, mascarar_documentos: bool = True) -> Auditoria:
    inicio = time.monotonic()
    agora = datetime.now().astimezone()
    doc = Documento(caminho)
    conf = confianca.carregar(pasta_confianca or confianca.PASTA_CONFIANCA)

    achados: list[Achado] = []
    resultado = dict(assinaturas=[], versoes=[], metadados={}, conteudo={}, hashes_citados=[])

    paginas = None
    if doc.leitor is None:
        achados.append(achado("DOC-01", "O arquivo não pôde ser lido como PDF.", Erro=doc.erro_leitura))
    else:
        a, resultado["assinaturas"] = assinaturas.verificar(doc, conf, mascarar_documentos)
        achados += a
        a, resultado["versoes"] = versoes.verificar(doc, resultado["assinaturas"])
        achados += a
        a, resultado["metadados"] = metadados.verificar(doc)
        achados += a
        a, resultado["conteudo"] = conteudo.verificar(doc)
        achados += a
        a, resultado["hashes_citados"] = hashes.verificar(doc, resultado["conteudo"].get("anexos", []))
        achados += a
        if resultado["versoes"]:
            paginas = resultado["versoes"][-1]["paginas"]

    achados.sort(key=lambda x: (x.nivel.ordem, x.regra.id))

    arquivo = {
        "nome": doc.nome,
        "tamanho": doc.tamanho,
        "paginas": paginas,
        "versao_pdf": resultado["metadados"].get("versao_pdf"),
        "hashes": doc.hashes,
    }
    metodologia = {
        "programa": "audit-contratos-digitais",
        "versao_programa": __version__,
        "data_analise": agora.isoformat(timespec="seconds"),
        "duracao_segundos": round(time.monotonic() - inicio, 2),
        "python": platform.python_version(),
        "sistema": f"{platform.system()} {platform.release()}",
        "bibliotecas": {b: _versao(b) for b in BIBLIOTECAS},
        "raizes_confianca": conf.descricao_raizes(),
        "intermediarios_confianca": len(conf.intermediarios),
        "consulta_revogacao": False,
        "documentos_mascarados": mascarar_documentos,
    }
    return Auditoria(
        arquivo=arquivo,
        achados=achados,
        classificacao=classificar(achados),
        metodologia=metodologia,
        **resultado,
    )
