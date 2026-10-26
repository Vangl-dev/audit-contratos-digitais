"""
Conteúdo ativo, oculto ou anexado: JavaScript, ações automáticas, arquivos
incorporados, camadas e anotações ocultas, formulários XFA e páginas sem texto.
"""

import pikepdf
import pymupdf

from ..documento import Documento, calcular_hashes, ALGORITMOS_CITACAO
from ..modelos import Achado
from ..regras import achado

ACOES_PERIGOSAS = {
    "/Launch": "abrir outro programa ou arquivo",
    "/SubmitForm": "enviar dados do formulário para um endereço",
    "/ImportData": "importar dados de fora do arquivo",
    "/GoToR": "abrir outro arquivo PDF",
    "/GoToE": "abrir um arquivo incorporado",
    "/RichMedia": "executar conteúdo multimídia",
}

SINAL_OCULTO = 0x02
SINAL_NAO_EXIBIR = 0x20
COBERTURA_MINIMA = 0.8
MAX_TEXTOS_COBERTOS = 40


def _area(r: pymupdf.Rect) -> float:
    return max(0.0, r.width) * max(0.0, r.height)


def _descrever_cor(cor) -> str:
    if not cor:
        return ""
    if all(c > 0.95 for c in cor):
        return "branco"
    if all(c < 0.05 for c in cor):
        return "preto"
    return "colorido (RGB " + ", ".join(str(round(c * 255)) for c in cor) + ")"


def texto_coberto(pagina) -> list[dict]:
    """
    Trechos de texto sobre os quais algo opaco foi desenhado depois (retângulo
    preenchido ou imagem). O texto continua no arquivo, mas não aparece na tela.
    A ordem de desenho é a ordem dos comandos no conteúdo da página.
    """
    log = pagina.get_bboxlog()
    coberturas = []
    retangulos = {d["seqno"]: d for d in pagina.get_drawings()
                  if "f" in d.get("type", "") and (d.get("fill_opacity") or 1) >= 0.99
                  and all(item[0] in ("re", "qu") for item in d["items"])}
    for seq, (tipo, caixa) in enumerate(log):
        if tipo == "fill-image":
            coberturas.append((seq, pymupdf.Rect(caixa), "imagem"))
        elif tipo == "fill-path" and seq in retangulos:
            cor = _descrever_cor(retangulos[seq].get("fill"))
            coberturas.append((seq, pymupdf.Rect(caixa), f"retângulo{' ' + cor if cor else ''}"))
    if not coberturas:
        return []

    encontrados = []
    for trecho in pagina.get_texttrace():
        if trecho.get("type") == 3 or trecho.get("opacity", 1) == 0:
            continue  # texto invisível de propósito (camada de OCR), tratado à parte
        texto = "".join(chr(c[0]) for c in trecho["chars"]).strip()
        if not texto:
            continue
        caixa = pymupdf.Rect(trecho["bbox"])
        if _area(caixa) == 0:
            continue
        for seq, cobertura, descricao in coberturas:
            if seq > trecho["seqno"] and _area(caixa & cobertura) / _area(caixa) >= COBERTURA_MINIMA:
                encontrados.append({"texto": texto, "coberto_por": descricao,
                                    "posicao": [round(x) for x in caixa]})
                break
    return encontrados


def _nome_arquivo(filespec) -> str:
    for chave in ("/UF", "/F", "/DOS", "/Unix"):
        if chave in filespec:
            try:
                return str(filespec[chave])
            except Exception:
                continue
    return "(sem nome)"


def verificar(doc: Documento) -> tuple[list[Achado], dict]:
    achados: list[Achado] = []
    dados = {"javascript": [], "acoes": [], "anexos": [], "camadas_ocultas": [],
             "anotacoes_ocultas": [], "xfa": False, "paginas_sem_texto": [], "texto_coberto": []}
    try:
        pdf = pikepdf.open(doc.caminho)
    except Exception:
        return achados, dados

    with pdf:
        vistos_anexos = set()
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            try:
                ref = f"objeto {obj.objgen[0]}" if obj.is_indirect else "objeto direto"
                tipo_acao = str(obj.get("/S", "")) if "/S" in obj else ""
                if tipo_acao == "/JavaScript" or "/JS" in obj:
                    dados["javascript"].append(ref)
                if tipo_acao in ACOES_PERIGOSAS:
                    dados["acoes"].append({"tipo": tipo_acao[1:], "efeito": ACOES_PERIGOSAS[tipo_acao], "local": ref})
                if "/EF" in obj and obj.objgen not in vistos_anexos:
                    vistos_anexos.add(obj.objgen)
                    fluxo = obj["/EF"].get("/F") or obj["/EF"].get("/UF")
                    conteudo = fluxo.read_bytes() if fluxo is not None else b""
                    dados["anexos"].append({
                        "nome": _nome_arquivo(obj),
                        "tamanho": len(conteudo),
                        "hashes": calcular_hashes(conteudo, ALGORITMOS_CITACAO),
                    })
            except Exception:
                continue

        try:
            nomes = pdf.Root.get("/Names")
            if nomes is not None and "/JavaScript" in nomes:
                dados["javascript"].append("árvore de nomes /JavaScript do documento")
        except Exception:
            pass

        try:
            ocp = pdf.Root.get("/OCProperties")
            desligadas = ocp["/D"].get("/OFF", []) if ocp is not None and "/D" in ocp else []
            for camada in desligadas:
                dados["camadas_ocultas"].append(str(camada.get("/Name", "(sem nome)")))
        except Exception:
            pass

        try:
            acroform = pdf.Root.get("/AcroForm")
            dados["xfa"] = bool(acroform is not None and "/XFA" in acroform)
        except Exception:
            pass

        for n, pagina in enumerate(pdf.pages, start=1):
            try:
                for anot in pagina.get("/Annots", []):
                    sinais = int(anot.get("/F", 0))
                    if not sinais & (SINAL_OCULTO | SINAL_NAO_EXIBIR):
                        continue
                    if str(anot.get("/FT", "")) == "/Sig":
                        continue  # campo de assinatura invisível: normal
                    dados["anotacoes_ocultas"].append({
                        "pagina": n,
                        "tipo": str(anot.get("/Subtype", ""))[1:],
                        "conteudo": str(anot.get("/Contents", ""))[:200] or None,
                    })
            except Exception:
                continue

    try:
        with pymupdf.open(stream=doc.dados, filetype="pdf") as d:
            for pagina in d:
                if not pagina.get_text().strip() and pagina.get_images():
                    dados["paginas_sem_texto"].append(pagina.number + 1)
                if len(dados["texto_coberto"]) < MAX_TEXTOS_COBERTOS:
                    for item in texto_coberto(pagina):
                        dados["texto_coberto"].append({"pagina": pagina.number + 1, **item})
    except Exception:
        pass

    if dados["javascript"]:
        achados.append(achado("CON-01", f"Código JavaScript encontrado em {len(dados['javascript'])} ponto(s).",
                              Locais=dados["javascript"]))
    if dados["acoes"]:
        tipos = sorted({a["efeito"] for a in dados["acoes"]})
        achados.append(achado("CON-02", "Ações encontradas: " + "; ".join(tipos) + ".", Ações=dados["acoes"]))
    if dados["anexos"]:
        nomes = [a["nome"] for a in dados["anexos"]]
        achados.append(achado("CON-03", f"{len(nomes)} arquivo(s) anexado(s): " + ", ".join(nomes) + ".",
                              Anexos=[{"nome": a["nome"], "tamanho": a["tamanho"],
                                       "sha256": a["hashes"]["sha256"]} for a in dados["anexos"]]))
    if dados["camadas_ocultas"]:
        achados.append(achado("CON-04", "Camadas desligadas: " + ", ".join(dados["camadas_ocultas"]) + ".",
                              Camadas=dados["camadas_ocultas"]))
    if dados["anotacoes_ocultas"]:
        achados.append(achado("CON-05", f"{len(dados['anotacoes_ocultas'])} anotação(ões) oculta(s).",
                              Anotações=dados["anotacoes_ocultas"]))
    if dados["texto_coberto"]:
        paginas = sorted({t["pagina"] for t in dados["texto_coberto"]})
        achados.append(achado(
            "CON-08",
            f"{len(dados['texto_coberto'])} trecho(s) de texto coberto(s) por outro elemento, "
            f"na(s) página(s) {', '.join(map(str, paginas))}.",
            **{"Trechos encobertos": [f"página {t['pagina']}: “{t['texto']}” (sob {t['coberto_por']})"
                                      for t in dados["texto_coberto"]]}))
    if dados["xfa"]:
        achados.append(achado("CON-06", "O formulário do arquivo usa XFA."))
    if dados["paginas_sem_texto"]:
        achados.append(achado("CON-07", "Páginas só com imagem: " + ", ".join(map(str, dados["paginas_sem_texto"])) + ".",
                              Páginas=dados["paginas_sem_texto"]))
    return achados, dados
