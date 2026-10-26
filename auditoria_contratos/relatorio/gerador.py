"""
Gera o relatório (PDF e HTML), os dados brutos (JSON) e as versões extraídas.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .. import conclusao, formatos
from ..auditoria import Auditoria
from ..modelos import Nivel
from ..regras import catalogo

PASTA = Path(__file__).parent
NUMERACAO = {"achados": 8, "metodologia": 9, "limitacoes": 10, "glossario": 11}

PERFIL_PADRAO = {
    "nome": "Responsável técnico",
    "qualificacao": "",
    "registro": "",
    "escritorio": "",
    "email": "",
    "telefone": "",
    "cidade": "",
    "logotipo": "",
}


def carregar_perfil(caminho: Path | None) -> dict:
    dados = {}
    if caminho and Path(caminho).is_file():
        dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    responsavel = {**PERFIL_PADRAO, **(dados.get("responsavel") or {})}
    if responsavel["logotipo"]:
        logo = Path(responsavel["logotipo"]).expanduser()
        if not logo.is_absolute():
            logo = Path(caminho).parent / logo
        responsavel["logotipo"] = logo.resolve().as_uri() if logo.is_file() else ""
    return {"responsavel": responsavel, "relatorio": dados.get("relatorio") or {}}


def _css_texto(valor) -> str:
    """Texto seguro para uma string CSS (cabeçalho das páginas)."""
    texto = str(valor).replace("\\", "\\\\").replace('"', '\\"').replace("<", "").replace("\n", " ")
    return Markup(texto)  # dentro de <style> entidades HTML não são decodificadas


def _data_pdf(valor) -> str:
    from ..verificacoes.metadados import data_pdf
    d = data_pdf(valor)
    return formatos.data(d) if d else str(valor)


def _evidencia(valor) -> str:
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, (list, tuple)):
        if all(not isinstance(x, (dict, list)) for x in valor):
            return ", ".join(str(x) for x in valor) if valor else "—"
        return "; ".join(_evidencia(x) for x in valor)
    if isinstance(valor, dict):
        return "; ".join(f"{k}: {_evidencia(v)}" for k, v in valor.items() if v is not None)
    return str(valor)


def _ambiente() -> Environment:
    env = Environment(loader=FileSystemLoader(PASTA), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(tamanho=formatos.tamanho, data=formatos.data, data_pdf=_data_pdf, css_texto=_css_texto,
                       data_extenso=formatos.data_extenso,
                       evidencia=_evidencia)
    return env


def _resumo_assinaturas(a: Auditoria) -> str:
    n = len(a.assinaturas)
    if n == 0:
        return "O arquivo não contém assinatura digital embutida."
    icp = sum(1 for s in a.assinaturas if s["cadeia_icp"] or s["politica_icp"])
    texto = f"O arquivo contém {n} assinatura{'s' if n > 1 else ''} digita{'is' if n > 1 else 'l'}"
    if icp == n:
        texto += ", todas com certificado ICP-Brasil." if n > 1 else ", com certificado ICP-Brasil."
    elif icp:
        texto += f", {icp} delas com certificado ICP-Brasil."
    else:
        texto += ", sem certificado ICP-Brasil."
    return texto


def renderizar_html(a: Auditoria, perfil: dict, caso: dict, versoes_exportadas: bool = False) -> str:
    modelo = _ambiente().get_template("modelo.html.j2")
    return modelo.render(
        a=a,
        c=conclusao.montar(a),
        r=perfil["responsavel"],
        caso=caso,
        n=NUMERACAO,
        N=Nivel,
        regras=catalogo(),
        total_regras=len(catalogo()),
        css=(PASTA / "estilo.css").read_text(encoding="utf-8"),
        icone=(PASTA.parent / "recursos" / "icone.svg").as_uri(),
        assinaturas_resumo=_resumo_assinaturas(a),
        versoes_exportadas=versoes_exportadas,
    )


def _conclusao_json(a: Auditoria) -> dict:
    c = conclusao.montar(a)
    c["pontos"] = [{**p, "nivel": p["nivel"].value} for p in c["pontos"]]
    return c


def _nome_pasta(nome_arquivo: str, data_iso: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", Path(nome_arquivo).stem, flags=re.UNICODE).strip("_")[:60] or "documento"
    carimbo = datetime.fromisoformat(data_iso).strftime("%Y%m%d-%H%M%S")
    return f"Relatorio-integridade-{base}-{carimbo}"


def gerar(a: Auditoria, dados_arquivo: bytes, pasta_saida: Path, perfil: dict,
          caso: dict | None = None, formatos=("pdf", "html", "json")) -> Path:
    """Grava os arquivos do relatório numa pasta nova e devolve o caminho dela."""
    from weasyprint import HTML

    caso = caso or {}
    destino = Path(pasta_saida) / _nome_pasta(a.arquivo["nome"], a.metodologia["data_analise"])
    destino.mkdir(parents=True, exist_ok=True)

    exportar_versoes = len(a.versoes) > 1
    if exportar_versoes:
        pasta_versoes = destino / "versoes"
        pasta_versoes.mkdir(exist_ok=True)
        for v in a.versoes[:-1]:
            (pasta_versoes / f"versao-{v['numero']}.pdf").write_bytes(dados_arquivo[: v["tamanho"]])

    html = renderizar_html(a, perfil, caso, versoes_exportadas=exportar_versoes)
    if "html" in formatos:
        (destino / "relatorio.html").write_text(html, encoding="utf-8")
    if "pdf" in formatos:
        HTML(string=html, base_url=str(PASTA)).write_pdf(destino / "relatorio.pdf")
    if "json" in formatos:
        (destino / "dados.json").write_text(
            json.dumps({"caso": caso, "conclusao": _conclusao_json(a), **a.to_dict()},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")

    linhas = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(destino).as_posix()}"
              for p in sorted(destino.rglob("*")) if p.is_file() and p.name != "HASHES-SHA256.txt"]
    linhas.insert(0, f"{a.arquivo['hashes']['sha256']}  {a.arquivo['nome']}  (arquivo analisado)")
    (destino / "HASHES-SHA256.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return destino
