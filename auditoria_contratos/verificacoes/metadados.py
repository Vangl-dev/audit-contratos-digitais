"""
Metadados do PDF: dicionário de informações (Info) e XMP.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pikepdf

from .. import formatos
from ..documento import Documento
from ..modelos import Achado
from ..regras import achado

# Programas e serviços usados para editar PDFs prontos. A comparação ignora
# maiúsculas e procura o trecho em qualquer parte do campo.
EDITORES_PDF = [
    "ilovepdf", "smallpdf", "sejda", "pdfescape", "pdf-xchange editor",
    "foxit phantompdf", "foxit pdf editor", "nitro pro", "nitro pdf",
    "pdfelement", "wondershare", "soda pdf", "sodapdf", "pdf24", "pdffiller",
    "dochub", "pdf candy", "pdfcandy", "pdf buddy", "lightpdf",
    "inkscape", "master pdf editor", "pdf studio", "able2extract",
]

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "pdf": "http://ns.adobe.com/pdf/1.3/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "stEvt": "http://ns.adobe.com/xap/1.0/sType/ResourceEvent#",
    "dc": "http://purl.org/dc/elements/1.1/",
}

CAMPOS_INFO = {
    "/Title": "Título",
    "/Author": "Autor",
    "/Subject": "Assunto",
    "/Creator": "Programa de origem",
    "/Producer": "Programa gerador do PDF",
    "/CreationDate": "Criado em",
    "/ModDate": "Modificado em",
}


def data_pdf(texto: str | None) -> datetime | None:
    """Converte datas no formato do PDF (D:AAAAMMDDHHmmSS+HH'mm')."""
    if not texto:
        return None
    m = re.match(
        r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?\s*([Zz+\-])?\s*(\d{2})?'?(\d{2})?'?",
        texto.strip())
    if not m:
        return None
    ano, mes, dia, hora, minuto, seg, sinal, tzh, tzm = m.groups()
    try:
        data = datetime(int(ano), int(mes or 1), int(dia or 1), int(hora or 0), int(minuto or 0), int(seg or 0))
    except ValueError:
        return None
    if sinal in ("Z", "z"):
        return data.replace(tzinfo=timezone.utc)
    if sinal in ("+", "-"):
        deslocamento = timedelta(hours=int(tzh or 0), minutes=int(tzm or 0))
        return data.replace(tzinfo=timezone(deslocamento if sinal == "+" else -deslocamento))
    return data


def data_xmp(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _mesmo_instante(a: datetime, b: datetime) -> bool:
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return abs((a - b).total_seconds()) <= 2


def _antes(a: datetime, b: datetime) -> bool:
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return (b - a).total_seconds() > 2


def _ler_xmp(pdf: pikepdf.Pdf) -> tuple[dict, list[dict], str | None]:
    """Campos principais e histórico (xmpMM:History) do XMP."""
    try:
        bruto = bytes(pdf.Root.Metadata.read_bytes())
    except Exception:
        return {}, [], None
    texto = bruto.decode("utf-8", errors="replace")
    try:
        raiz = ET.fromstring(re.sub(rb"<\?xpacket[^>]*\?>", b"", bruto).strip().lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError:
        return {}, [], texto

    def valor(caminho_ns: str, local: str) -> str | None:
        for desc in raiz.iter(f"{{{NS['rdf']}}}Description"):
            attr = desc.get(f"{{{NS[caminho_ns]}}}{local}")
            if attr:
                return attr
            el = desc.find(f"{caminho_ns}:{local}", NS)
            if el is not None:
                li = el.find(".//rdf:li", NS)
                return (li.text if li is not None else el.text or "").strip() or None
        return None

    campos = {
        "Programa de origem": valor("xmp", "CreatorTool"),
        "Programa gerador do PDF": valor("pdf", "Producer"),
        "Criado em": valor("xmp", "CreateDate"),
        "Modificado em": valor("xmp", "ModifyDate"),
        "Metadados alterados em": valor("xmp", "MetadataDate"),
        "Identificador do documento": valor("xmpMM", "DocumentID"),
        "Identificador da instância": valor("xmpMM", "InstanceID"),
    }

    historico = []
    for hist in raiz.iter(f"{{{NS['xmpMM']}}}History"):
        for li in hist.iter(f"{{{NS['rdf']}}}li"):
            def campo(nome):
                v = li.get(f"{{{NS['stEvt']}}}{nome}")
                if v is None:
                    el = li.find(f"stEvt:{nome}", NS)
                    v = el.text if el is not None else None
                return v
            evento = {"acao": campo("action"), "data": campo("when"),
                      "programa": campo("softwareAgent"), "alterado": campo("changed")}
            if any(evento.values()):
                historico.append(evento)
    return {k: v for k, v in campos.items() if v}, historico, texto


def verificar(doc: Documento) -> tuple[list[Achado], dict]:
    achados: list[Achado] = []
    try:
        pdf = pikepdf.open(doc.caminho)
    except Exception:
        return achados, {}

    with pdf:
        info = {}
        try:
            for chave, rotulo in CAMPOS_INFO.items():
                if chave in pdf.docinfo:
                    info[rotulo] = str(pdf.docinfo[chave])
        except Exception:
            pass
        xmp, historico, _ = _ler_xmp(pdf)
        versao_pdf = pdf.pdf_version

    dados = {"info": info, "xmp": xmp, "historico": historico, "versao_pdf": versao_pdf}

    criacao = data_pdf(info.get("Criado em"))
    modificacao = data_pdf(info.get("Modificado em"))
    criacao_xmp = data_xmp(xmp.get("Criado em"))
    modificacao_xmp = data_xmp(xmp.get("Modificado em"))
    dados["datas"] = {
        "criacao": criacao.isoformat() if criacao else None,
        "modificacao": modificacao.isoformat() if modificacao else None,
    }

    for c, m, origem in ((criacao, modificacao, "Info"), (criacao_xmp, modificacao_xmp, "XMP")):
        if c and m and _antes(m, c):
            achados.append(achado(
                "MET-01", f"Nos metadados ({origem}), a modificação ({formatos.data(m)}) é anterior à criação ({formatos.data(c)}).",
                Registro=origem, **{"Criado em": formatos.data(c), "Modificado em": formatos.data(m)}))

    divergencias = {}
    for rotulo, a, b in (("Criado em", criacao, criacao_xmp), ("Modificado em", modificacao, modificacao_xmp)):
        if a and b and not _mesmo_instante(a, b):
            divergencias[rotulo] = {"Info": formatos.data(a), "XMP": formatos.data(b)}
    for rotulo in ("Programa gerador do PDF", "Programa de origem"):
        a, b = info.get(rotulo), xmp.get(rotulo)
        if a and b and a.strip() != b.strip():
            divergencias[rotulo] = {"Info": a, "XMP": b}
    if divergencias:
        achados.append(achado("MET-02", "Os campos " + ", ".join(divergencias) + " divergem entre Info e XMP.",
                              **divergencias))

    programas = {v for k, v in list(info.items()) + list(xmp.items()) if k.startswith("Programa")}
    programas |= {e["programa"] for e in historico if e.get("programa")}
    editores = sorted(p for p in programas if any(ed in p.lower() for ed in EDITORES_PDF))
    if editores:
        achados.append(achado("MET-03", "Programa(s) de edição encontrado(s) nos metadados: " + "; ".join(editores) + ".",
                              Programas=editores))

    if historico:
        achados.append(achado("MET-04", f"O XMP registra {len(historico)} evento(s) de gravação do arquivo.",
                              Eventos=historico))

    if criacao and modificacao and not _mesmo_instante(criacao, modificacao) and not _antes(modificacao, criacao):
        achados.append(achado("MET-05", f"Criado em {formatos.data(criacao)} e modificado em {formatos.data(modificacao)}.",
                              **{"Criado em": formatos.data(criacao), "Modificado em": formatos.data(modificacao)}))

    return achados, dados
