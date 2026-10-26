"""
Versões do arquivo (atualizações incrementais) e o que mudou em cada uma.

Cada versão é reaberta sozinha e suas páginas são renderizadas como imagem.
Duas versões consecutivas são comparadas pixel a pixel e pelo texto extraído.
As regiões diferentes são marcadas em vermelho nas imagens do relatório.
"""

import base64
import difflib
import io
from collections import deque

import pymupdf
from PIL import Image, ImageChops, ImageDraw

from ..documento import Documento
from ..modelos import Achado
from ..regras import achado

ZOOM_COMPARACAO = 1.0
ZOOM_IMAGEM = 1.4
ZOOM_DETALHE = 2.6
MARGEM_DETALHE = 24
LIMIAR_PIXEL = 24
TAMANHO_CELULA = 10
MAX_PAGINAS_COM_IMAGEM = 20
MAX_LINHAS_TEXTO = 25


def _abrir(dados: bytes):
    return pymupdf.open(stream=dados, filetype="pdf")


def _renderizar(pagina, zoom: float) -> Image.Image:
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _linhas(pagina) -> list[str]:
    return [l.strip() for l in pagina.get_text("text").splitlines() if l.strip()]


def regioes_diferentes(antes: Image.Image, depois: Image.Image) -> list[tuple[int, int, int, int]]:
    """Retângulos (x0, y0, x1, y1) que cobrem as áreas diferentes entre duas imagens."""
    if antes.size != depois.size:
        return [(0, 0, depois.width, depois.height)]
    mascara = ImageChops.difference(antes, depois).convert("L").point(
        lambda p: 255 if p > LIMIAR_PIXEL else 0)
    if mascara.getbbox() is None:
        return []

    t = TAMANHO_CELULA
    colunas, linhas = (depois.width + t - 1) // t, (depois.height + t - 1) // t
    marcadas = set()
    for cy in range(linhas):
        for cx in range(colunas):
            caixa = (cx * t, cy * t, min((cx + 1) * t, depois.width), min((cy + 1) * t, depois.height))
            if mascara.crop(caixa).getbbox() is not None:
                marcadas.add((cx, cy))

    regioes = []
    while marcadas:
        inicio = marcadas.pop()
        fila = deque([inicio])
        xs, ys = [inicio[0]], [inicio[1]]
        while fila:
            cx, cy = fila.popleft()
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    viz = (cx + dx, cy + dy)
                    if viz in marcadas:
                        marcadas.remove(viz)
                        fila.append(viz)
                        xs.append(viz[0])
                        ys.append(viz[1])
        regioes.append((min(xs) * t, min(ys) * t,
                        min((max(xs) + 1) * t, depois.width), min((max(ys) + 1) * t, depois.height)))
    return sorted(regioes, key=lambda r: (r[1], r[0]))


def _marcar(imagem: Image.Image, regioes, escala: float) -> Image.Image:
    img = imagem.convert("RGBA")
    camada = Image.new("RGBA", img.size, (0, 0, 0, 0))
    desenho = ImageDraw.Draw(camada)
    for x0, y0, x1, y1 in regioes:
        caixa = [x0 * escala - 4, y0 * escala - 4, x1 * escala + 4, y1 * escala + 4]
        desenho.rectangle(caixa, fill=(214, 40, 40, 40), outline=(200, 30, 30, 255), width=3)
    return Image.alpha_composite(img, camada).convert("RGB")


def _detalhe(pagina, regioes, zoom_base: float) -> tuple[Image.Image, list]:
    """Recorte ampliado da área que envolve todas as regiões alteradas."""
    x0 = min(r[0] for r in regioes) - MARGEM_DETALHE
    y0 = min(r[1] for r in regioes) - MARGEM_DETALHE
    x1 = max(r[2] for r in regioes) + MARGEM_DETALHE
    y1 = max(r[3] for r in regioes) + MARGEM_DETALHE
    limite = pagina.rect
    recorte = pymupdf.Rect(x0 / zoom_base, y0 / zoom_base, x1 / zoom_base, y1 / zoom_base) & limite
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(ZOOM_DETALHE, ZOOM_DETALHE), clip=recorte, alpha=False)
    imagem = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    deslocadas = [(r[0] - recorte.x0 * zoom_base, r[1] - recorte.y0 * zoom_base,
                   r[2] - recorte.x0 * zoom_base, r[3] - recorte.y0 * zoom_base) for r in regioes]
    return imagem, deslocadas


def _png_base64(imagem: Image.Image) -> str:
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def comparar(doc_antes, doc_depois, gerar_imagens: bool = True) -> dict:
    """Compara duas versões abertas. Devolve as páginas alteradas, acrescentadas e removidas."""
    n_antes, n_depois = doc_antes.page_count, doc_depois.page_count
    alteradas = []
    imagens_geradas = 0
    for i in range(min(n_antes, n_depois)):
        pa, pd = doc_antes[i], doc_depois[i]
        img_a, img_d = _renderizar(pa, ZOOM_COMPARACAO), _renderizar(pd, ZOOM_COMPARACAO)
        if img_a.size == img_d.size and img_a.tobytes() == img_d.tobytes():
            continue
        regioes = regioes_diferentes(img_a, img_d)
        if not regioes:
            continue
        linhas_a, linhas_d = _linhas(pa), _linhas(pd)
        diff = list(difflib.ndiff(linhas_a, linhas_d))
        removidas = [l[2:] for l in diff if l.startswith("- ")]
        acrescentadas = [l[2:] for l in diff if l.startswith("+ ")]
        item = {
            "pagina": i + 1,
            "regioes": len(regioes),
            "texto_removido": removidas[:MAX_LINHAS_TEXTO],
            "texto_acrescentado": acrescentadas[:MAX_LINHAS_TEXTO],
            "texto_mudou": bool(removidas or acrescentadas),
        }
        if gerar_imagens and imagens_geradas < MAX_PAGINAS_COM_IMAGEM:
            escala = ZOOM_IMAGEM / ZOOM_COMPARACAO
            item["imagem_antes"] = _png_base64(_marcar(_renderizar(pa, ZOOM_IMAGEM), regioes, escala))
            item["imagem_depois"] = _png_base64(_marcar(_renderizar(pd, ZOOM_IMAGEM), regioes, escala))
            if pa.rect == pd.rect:
                escala_detalhe = ZOOM_DETALHE / ZOOM_COMPARACAO
                for nome, pagina in (("detalhe_antes", pa), ("detalhe_depois", pd)):
                    img, desloc = _detalhe(pagina, regioes, ZOOM_COMPARACAO)
                    item[nome] = _png_base64(_marcar(img, desloc, escala_detalhe))
            imagens_geradas += 1
        alteradas.append(item)
    return {
        "paginas_alteradas": alteradas,
        "paginas_acrescentadas": list(range(n_antes + 1, n_depois + 1)),
        "paginas_removidas": list(range(n_depois + 1, n_antes + 1)),
    }


def verificar(doc: Documento, dados_assinaturas: list[dict]) -> tuple[list[Achado], list[dict]]:
    """
    Precisa rodar depois das assinaturas, para saber qual versão cada uma cobre.
    """
    achados: list[Achado] = []
    versoes = doc.versoes
    assinadas = {a["versao_assinada"]: a for a in dados_assinaturas}

    abertos = {}
    for v in versoes:
        try:
            abertos[v.numero] = _abrir(doc.dados_da_versao(v.numero))
        except Exception:
            abertos[v.numero] = None

    resultado = []
    for v in versoes:
        item = {
            "numero": v.numero,
            "tamanho": v.tamanho,
            "hashes": v.hashes,
            "assinaturas": v.assinaturas,
            "paginas": abertos[v.numero].page_count if abertos[v.numero] else None,
            "abre_sozinha": abertos[v.numero] is not None,
            "mudancas": None,
            "contexto": None,
        }
        anterior = abertos.get(v.numero - 1)
        atual = abertos[v.numero]
        if v.numero > 1 and anterior is not None and atual is not None:
            mudancas = comparar(anterior, atual)
            item["mudancas"] = mudancas
            item["contexto"] = _contexto(v.numero, assinadas)
        resultado.append(item)

    for d in abertos.values():
        if d is not None:
            d.close()

    if len(versoes) == 1:
        achados.append(achado("VER-01", "O arquivo tem uma única versão."))
        return achados, resultado

    achados.append(achado(
        "VER-02", f"O arquivo tem {len(versoes)} versões gravadas uma sobre a outra.",
        Versões=len(versoes),
        **{"Versões com assinatura": [n for n, _ in sorted(assinadas.items())] or "nenhuma"},
    ))

    houve_mudanca_visivel = False
    for item in resultado:
        m = item["mudancas"]
        if not m:
            continue
        paginas = [p["pagina"] for p in m["paginas_alteradas"]]
        if not (paginas or m["paginas_acrescentadas"] or m["paginas_removidas"]):
            continue
        houve_mudanca_visivel = True
        descricao = _descrever(item["numero"], m)
        ev = {
            "Versão": item["numero"],
            "Páginas alteradas": paginas or "nenhuma",
            "Páginas acrescentadas": m["paginas_acrescentadas"] or "nenhuma",
            "Páginas removidas": m["paginas_removidas"] or "nenhuma",
            "Hash SHA-256 da versão anterior": versoes[item["numero"] - 2].hashes["sha256"],
            "Hash SHA-256 desta versão": item["hashes"]["sha256"],
        }
        contexto = item["contexto"]
        if contexto == "apos_assinatura":
            assinadas_antes = [n for n in assinadas if n < item["numero"]]
            ev["Última versão assinada antes desta"] = max(assinadas_antes)
            achados.append(achado("VER-03", descricao, **ev))
        elif contexto == "sem_assinatura":
            achados.append(achado("VER-04", descricao, **ev))
        # contexto "assinada": a própria assinatura cobre a mudança (ex.: o carimbo visual
        # da assinatura). A seção de assinaturas já diz se ela é íntegra.

    if not houve_mudanca_visivel:
        achados.append(achado("VER-05", "Nenhuma versão posterior mudou o conteúdo visível das páginas."))

    return achados, resultado


def _contexto(numero: int, assinadas: dict) -> str:
    if numero in assinadas:
        return "assinada"
    if any(n < numero for n in assinadas):
        return "apos_assinatura"
    return "sem_assinatura"


def _descrever(numero: int, m: dict) -> str:
    partes = []
    alteradas = [str(p["pagina"]) for p in m["paginas_alteradas"]]
    if len(alteradas) == 1:
        partes.append(f"a página {alteradas[0]} foi alterada")
    elif alteradas:
        partes.append(f"as páginas {', '.join(alteradas)} foram alteradas")
    if m["paginas_acrescentadas"]:
        partes.append(f"{len(m['paginas_acrescentadas'])} página(s) acrescentada(s)")
    if m["paginas_removidas"]:
        partes.append(f"{len(m['paginas_removidas'])} página(s) removida(s)")
    return f"Na versão {numero}: " + "; ".join(partes) + "."
