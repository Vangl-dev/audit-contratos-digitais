"""
Carrega o catálogo de regras (regras.yaml).
"""

from functools import lru_cache
from pathlib import Path

import yaml

from .modelos import Achado, Nivel, Regra

ARQUIVO_REGRAS = Path(__file__).with_name("regras.yaml")


@lru_cache(maxsize=1)
def catalogo() -> dict[str, Regra]:
    dados = yaml.safe_load(ARQUIVO_REGRAS.read_text(encoding="utf-8"))
    regras = {}
    for id_regra, d in dados.items():
        regras[id_regra] = Regra(
            id=id_regra,
            titulo=d["titulo"],
            nivel=Nivel(d["nivel"]),
            secao=d["secao"],
            explicacao=" ".join(d["explicacao"].split()),
            recomendacao=" ".join(d.get("recomendacao", "").split()),
            referencias=d.get("referencias", []),
        )
    return regras


def achado(id_regra: str, resumo: str, nivel: Nivel | None = None, **evidencias) -> Achado:
    """Cria um achado para a regra indicada. O nível padrão é o da regra."""
    regra = catalogo()[id_regra]
    return Achado(regra=regra, nivel=nivel or regra.nivel, resumo=resumo, evidencias=evidencias)
