"""
Leitura do arquivo analisado: bytes, hashes e versões (revisões).

Um PDF com atualizações incrementais guarda todas as versões anteriores.
A versão N é exatamente o início do arquivo até o fim da N-ésima seção de
referências cruzadas (marcador %%EOF). Cada versão pode ser extraída e
reaberta sozinha.
"""

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

ALGORITMOS = ("sha256", "sha512")
ALGORITMOS_CITACAO = ("md5", "sha1", "sha256", "sha512")

# A biblioteca de assinaturas registra avisos detalhados que não interessam ao relatório
logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)


def calcular_hashes(dados: bytes, algoritmos=ALGORITMOS) -> dict[str, str]:
    return {alg: hashlib.new(alg, dados).hexdigest() for alg in algoritmos}


@dataclass
class Versao:
    numero: int
    fim: int
    hashes: dict[str, str]
    assinaturas: list[str] = field(default_factory=list)

    @property
    def tamanho(self) -> int:
        return self.fim


class Documento:
    """O arquivo em análise. Carrega os bytes uma única vez."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.dados = self.caminho.read_bytes()
        self.hashes = calcular_hashes(self.dados)
        self.erro_leitura: str | None = None

    @property
    def nome(self) -> str:
        return self.caminho.name

    @property
    def tamanho(self) -> int:
        return len(self.dados)

    @cached_property
    def leitor(self):
        """Leitor do pyHanko (estrutura e assinaturas). None se o PDF não abrir."""
        from pyhanko.pdf_utils.reader import PdfFileReader
        try:
            return PdfFileReader(io.BytesIO(self.dados), strict=False)
        except Exception as e:
            self.erro_leitura = str(e)
            return None

    @cached_property
    def versoes(self) -> list[Versao]:
        fins = self._fins_de_versao()
        return [
            Versao(numero=i + 1, fim=fim, hashes=calcular_hashes(self.dados[:fim]))
            for i, fim in enumerate(fins)
        ]

    def dados_da_versao(self, numero: int) -> bytes:
        return self.dados[: self.versoes[numero - 1].fim]

    def _fins_de_versao(self) -> list[int]:
        fins = []
        leitor = self.leitor
        if leitor is not None:
            try:
                xrefs = leitor.xrefs
                for rev in range(xrefs.total_revisions):
                    info = xrefs.get_xref_container_info(rev)
                    fins.append(self._fim_apos(info.end_location))
            except Exception:
                fins = []
        if not fins:
            fins = [m.end() for m in re.finditer(rb"%%EOF[\r\n]*", self.dados)]
        if not fins:
            fins = [len(self.dados)]
        fins[-1] = len(self.dados)
        return sorted(set(fins))

    def _fim_apos(self, posicao: int) -> int:
        """Fim da versão: logo depois do %%EOF que segue a posição dada."""
        m = re.compile(rb"%%EOF(\r\n|\r|\n)?").search(self.dados, posicao)
        return m.end() if m else len(self.dados)
