"""
Modelos de dados da auditoria.

Cada verificação produz Achados. Um Achado sempre aponta a regra aplicada
(catálogo em regras.yaml), o nível e as evidências objetivas que o sustentam.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Nivel(Enum):
    """Nível de um achado, do mais grave para o menos grave."""
    CRITICO = "critico"
    ATENCAO = "atencao"
    ERRO = "erro"
    INFO = "info"
    OK = "ok"

    @property
    def rotulo(self) -> str:
        return {
            "critico": "Crítico",
            "atencao": "Atenção",
            "erro": "Não verificado",
            "info": "Informativo",
            "ok": "Conforme",
        }[self.value]

    @property
    def ordem(self) -> int:
        return list(Nivel).index(self)


class Classificacao(Enum):
    VERDE = "VERDE"
    AMARELO = "AMARELO"
    VERMELHO = "VERMELHO"

    @property
    def descricao(self) -> str:
        return {
            "VERDE": "Nenhuma inconsistência técnica encontrada nas verificações realizadas.",
            "AMARELO": "Foram encontradas inconsistências técnicas que merecem análise.",
            "VERMELHO": "Foram encontradas evidências técnicas objetivas de alteração "
                        "ou de comprometimento da integridade do documento.",
        }[self.value]


@dataclass
class Regra:
    id: str
    titulo: str
    nivel: Nivel
    secao: str
    explicacao: str
    recomendacao: str = ""
    referencias: list[str] = field(default_factory=list)


@dataclass
class Achado:
    regra: Regra
    nivel: Nivel
    resumo: str
    evidencias: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "regra": self.regra.id,
            "titulo": self.regra.titulo,
            "nivel": self.nivel.value,
            "secao": self.regra.secao,
            "resumo": self.resumo,
            "explicacao": self.regra.explicacao,
            "recomendacao": self.regra.recomendacao,
            "referencias": self.regra.referencias,
            "evidencias": self.evidencias,
        }
