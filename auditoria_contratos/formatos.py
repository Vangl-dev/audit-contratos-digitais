"""
Formatação de datas e tamanhos no padrão brasileiro.
"""

from datetime import datetime

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def data(valor) -> str:
    """26/10/2026 15:10:40 (UTC-3h). Aceita datetime ou texto ISO 8601."""
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        d = valor
    else:
        try:
            d = datetime.fromisoformat(str(valor))
        except ValueError:
            return str(valor)
    if d.hour == d.minute == d.second == 0 and d.tzinfo is None:
        return d.strftime("%d/%m/%Y")
    texto = d.strftime("%d/%m/%Y %H:%M:%S")
    if d.tzinfo is not None:
        horas = d.utcoffset().total_seconds() / 3600
        texto += " (UTC)" if horas == 0 else f" (UTC{horas:+g}h)"
    return texto


def data_extenso(valor) -> str:
    d = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor))
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def tamanho(n: int | None) -> str:
    if n is None:
        return "—"
    em_bytes = f"{n:,}".replace(",", ".")
    for unidade, fator in (("MB", 1024 ** 2), ("KB", 1024)):
        if n >= fator:
            valor = f"{n / fator:.1f}".replace(".", ",")
            return f"{valor} {unidade} ({em_bytes} bytes)"
    return f"{em_bytes} bytes"
