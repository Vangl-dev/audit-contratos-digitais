"""
Conclusão em linguagem simples, para o início do relatório.

Montada por regras fixas a partir dos achados: cada frase corresponde a um
achado verificado e usa apenas dados extraídos do arquivo. Não há texto
gerado por inteligência artificial nem opinião sobre o mérito do caso.
"""

from difflib import SequenceMatcher

from .auditoria import Auditoria
from .modelos import Classificacao, Nivel

SECAO = {"documento": 2, "assinaturas": 3, "versoes": 4, "metadados": 5, "conteudo": 6, "hashes": 7}
MAX_CITACOES = 3
SEMELHANCA_MINIMA = 0.5

RESSALVA = (
    "Esta conclusão resulta apenas de verificações técnicas feitas sobre o arquivo identificado na capa. "
    "Ela não examina sistemas, registros de plataformas nem pessoas, não é laudo pericial e não contém "
    "opinião jurídica. Cada afirmação acima está demonstrada nas seções seguintes."
)


def _lista(itens) -> str:
    itens = [str(i) for i in itens]
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _paginas(numeros) -> str:
    numeros = list(numeros)
    return ("a página " if len(numeros) == 1 else "as páginas ") + _lista(numeros)


def _citar(texto: str, limite: int = 90) -> str:
    texto = " ".join(texto.split())
    return f"“{texto if len(texto) <= limite else texto[:limite - 1] + '…'}”"


def _assinatura(a: Auditoria, rotulo: str) -> dict | None:
    for s in a.assinaturas:
        if f"Assinatura {s['indice']}" == rotulo:
            return s
    return None


def _mudancas_apos(a: Auditoria, contexto: str) -> list[dict]:
    return [v for v in a.versoes if v.get("contexto") == contexto and v.get("mudancas")
            and (v["mudancas"]["paginas_alteradas"] or v["mudancas"]["paginas_acrescentadas"]
                 or v["mudancas"]["paginas_removidas"])]


def _descrever_mudanca(m: dict) -> str:
    partes = []
    alteradas = [p["pagina"] for p in m["paginas_alteradas"]]
    if alteradas:
        partes.append(f"{_paginas(alteradas)} {'foi alterada' if len(alteradas) == 1 else 'foram alteradas'}")
    if m["paginas_acrescentadas"]:
        n = len(m["paginas_acrescentadas"])
        partes.append(f"{'foi acrescentada 1 página' if n == 1 else f'foram acrescentadas {n} páginas'}")
    if m["paginas_removidas"]:
        n = len(m["paginas_removidas"])
        partes.append(f"{'foi removida 1 página' if n == 1 else f'foram removidas {n} páginas'}")
    return _lista(partes)


def _texto_novo(a: Auditoria, contextos: tuple[str, ...]) -> list[tuple[int, str]]:
    """Linhas que passaram a aparecer nas páginas alteradas (até MAX_CITACOES)."""
    linhas = []
    for v in a.versoes:
        if v.get("contexto") in contextos and v.get("mudancas"):
            for p in v["mudancas"]["paginas_alteradas"]:
                for l in p["texto_acrescentado"]:
                    linhas.append((p["pagina"], l))
    return linhas[:MAX_CITACOES]


def _trechos_trocados(a: Auditoria, contextos: tuple[str, ...]) -> list[str]:
    """
    Junta, por página, o texto encoberto e o texto que passou a aparecer.
    Um texto novo é ligado ao encoberto quando os dois são parecidos (mesma frase
    com outro valor, por exemplo); os demais são citados separadamente.
    """
    frases = []
    cobertos = a.conteudo.get("texto_coberto") or []
    novos = _texto_novo(a, contextos) if contextos else []
    usados = set()
    citados = 0
    for t in cobertos:
        if citados >= MAX_CITACOES:
            break
        candidatos = [(SequenceMatcher(None, t["texto"], n).ratio(), i, n)
                      for i, (p, n) in enumerate(novos) if p == t["pagina"] and i not in usados]
        melhor = max(candidatos, default=None)
        if melhor and melhor[0] >= SEMELHANCA_MINIMA:
            usados.add(melhor[1])
            frases.append(f"Na página {t['pagina']}, o texto {_citar(t['texto'])} continua gravado no arquivo, mas "
                          f"foi coberto por um {t['coberto_por']} e não aparece na tela. No lugar dele, aparece "
                          f"hoje {_citar(melhor[2])}.")
        else:
            frases.append(f"Na página {t['pagina']}, o texto {_citar(t['texto'])} continua gravado no arquivo, mas "
                          f"foi coberto por um {t['coberto_por']} e não aparece na tela.")
        citados += 1
    if len(cobertos) > citados:
        frases.append(f"Há mais {len(cobertos) - citados} trecho(s) de texto encoberto(s), listados na seção 6.")
    if cobertos:
        frases.append("Cobrir um trecho e escrever outro por cima é a forma mais comum de alterar um PDF pronto.")
    restantes = [(p, n) for i, (p, n) in enumerate(novos) if i not in usados]
    if restantes:
        frases.append("Na versão final, passou a aparecer: "
                      + "; ".join(f"na página {p}, {_citar(n)}" for p, n in restantes) + ".")
    return frases


def montar(a: Auditoria) -> dict:
    ids = {x.regra.id for x in a.achados}
    achados_por_id: dict[str, list] = {}
    for x in a.achados:
        achados_por_id.setdefault(x.regra.id, []).append(x)
    frases: list[str] = []

    # ── Alteração do conteúdo assinado ──
    for x in achados_por_id.get("ASS-01", []):
        s = _assinatura(a, x.evidencias.get("Assinatura", ""))
        nome = s["signatario"] if s else "o signatário"
        frases.append(
            f"A assinatura digital de {nome} guarda uma “impressão digital” (hash) do conteúdo no momento em "
            "que foi feita. Recalculada agora, essa impressão digital não confere: o conteúdo assinado foi "
            "modificado depois da assinatura.")
    for x in achados_por_id.get("ASS-02", []):
        s = _assinatura(a, x.evidencias.get("Assinatura", ""))
        frases.append(
            f"A assinatura atribuída a {s['signatario'] if s else 'o signatário'} não pôde ser confirmada "
            "matematicamente com o certificado apresentado. Ela não comprova quem assinou.")

    # ── Alterações depois da assinatura ──
    apos = _mudancas_apos(a, "apos_assinatura")
    for x in achados_por_id.get("ASS-03", []):
        s = _assinatura(a, x.evidencias.get("Assinatura", ""))
        nome = s["signatario"] if s else "o signatário"
        versao = s["versao_assinada"] if s else None
        frase = (f"A assinatura digital de {nome} está matematicamente correta, mas cobre apenas uma versão "
                 f"anterior do arquivo{f' (versão {versao})' if versao else ''}. Depois de assinado, o arquivo "
                 "foi modificado")
        posteriores = [v for v in apos if versao is None or v["numero"] > versao]
        if posteriores:
            frase += ": " + "; ".join(_descrever_mudanca(v["mudancas"]) for v in posteriores)
        frase += "."
        if versao and versao < len(a.versoes):
            frase += (f" A versão que foi realmente assinada continua guardada dentro do próprio arquivo e foi "
                      f"extraída para comparação (versao-{versao}.pdf).")
        frases.append(frase)
    if "VER-03" in ids and "ASS-03" not in ids:
        frases.append("Depois da última assinatura, o arquivo foi modificado: "
                      + "; ".join(_descrever_mudanca(v["mudancas"]) for v in apos) + ".")

    # ── Edição sem assinatura ──
    sem = _mudancas_apos(a, "sem_assinatura")
    if sem:
        frases.append(
            "O arquivo foi modificado depois de criado: "
            + "; ".join(f"na versão {v['numero']}, {_descrever_mudanca(v['mudancas'])}" for v in sem)
            + ". Nenhuma assinatura digital cobre essas mudanças, por isso não é possível saber, apenas pelo "
            "arquivo, qual versão corresponde ao que foi contratado.")

    # ── O que foi escondido e o que passou a aparecer ──
    frases.extend(_trechos_trocados(a, ("apos_assinatura", "sem_assinatura") if (apos or sem) else ()))

    # ── Ausência de assinatura ──
    if "ASS-12" in ids:
        frases.append(
            "O arquivo não tem assinatura digital. Aceites feitos em plataformas (clique, senha, SMS, selfie) não "
            "ficam gravados no PDF. Para provar que este é o conteúdo aceito pelo contratante, é preciso a trilha "
            "de auditoria da plataforma e o arquivo original.")

    # ── Certificado ──
    for x in achados_por_id.get("ASS-08", []):
        s = _assinatura(a, x.evidencias.get("Assinatura", ""))
        frases.append(
            f"A assinatura de {s['signatario'] if s else 'o signatário'} usa certificado que não é da ICP-Brasil "
            f"(emitido por {x.evidencias.get('Emissor')}). Por lei, esse tipo de assinatura só tem o valor de uma "
            "assinatura qualificada se for admitido pelas partes ou aceito por quem o documento for oposto.")
    if "ASS-06" in ids:
        frases.append("Não foi possível confirmar, pela cadeia de certificação, quem emitiu o certificado usado na assinatura.")
    if "ASS-09" in ids:
        frases.append("O certificado usado na assinatura estava fora do prazo de validade na data da assinatura.")

    # ── Metadados ──
    if "MET-01" in ids:
        frases.append("As datas gravadas dentro do arquivo são impossíveis: a modificação aparece antes da criação.")
    for x in achados_por_id.get("MET-03", []):
        frases.append(f"Os registros internos mostram que o arquivo passou pelo programa {_lista(x.evidencias.get('Programas', []))}, "
                      "usado para editar PDFs prontos.")
    if "MET-02" in ids and "MET-03" not in ids:
        frases.append("Os dois registros internos de data e programa do arquivo não batem entre si, o que indica que "
                      "ele passou por outro programa depois de gerado.")

    # ── Conteúdo ativo ou oculto ──
    if ids & {"CON-01", "CON-02"}:
        frases.append("O arquivo contém código ou ações automáticas que podem mudar o que aparece na tela "
                      "conforme o programa usado para abri-lo.")
    if ids & {"CON-04", "CON-05"}:
        frases.append("Há conteúdo marcado para não aparecer na tela (camadas ou anotações ocultas).")
    if "CON-03" in ids:
        frases.append("Há arquivos anexados dentro do PDF, que não aparecem nas páginas; eles estão listados no relatório.")

    # ── Pontos positivos ──
    positivos: list[str] = []
    for s in a.assinaturas:
        if s["integra"] and s["valida"] and s["modificacao"] in ("NONE", "LTA_UPDATES", None):
            icp = " com certificado ICP-Brasil," if (s["cadeia_icp"] or s["politica_icp"]) else ""
            positivos.append(f"A assinatura digital de {s['signatario']},{icp} confere com o conteúdo do arquivo e "
                             "não houve alterações depois dela.")
            if s["carimbo"] and s["carimbo"]["integro"] and s["carimbo"]["valido"]:
                positivos.append("Ela tem carimbo do tempo emitido por autoridade independente, que comprova a data.")
    if "VER-01" in ids:
        positivos.append("O arquivo foi gravado de uma só vez, sem versões posteriores.")
    for h in a.hashes_citados:
        if h["confere_com"]:
            positivos.append(f"O hash citado na página {h['pagina']} confere com {h['confere_com']}, o que liga o "
                             "registro da plataforma a esse conteúdo.")
    if "HSH-02" in ids and "HSH-01" not in ids:
        frases.append("O documento cita um hash que não confere com o arquivo nem com suas versões. Para conferir, "
                      "é preciso o arquivo original da plataforma.")

    titulo = _titulo(a.classificacao, ids)

    providencias = []
    for x in a.achados:
        if x.nivel in (Nivel.CRITICO, Nivel.ATENCAO) and x.regra.recomendacao and x.regra.recomendacao not in providencias:
            providencias.append(x.regra.recomendacao)

    pontos = [
        {"nivel": x.nivel, "titulo": x.regra.titulo, "resumo": x.resumo, "regra": x.regra.id,
         "secao": SECAO.get(x.regra.secao)}
        for x in a.achados if x.nivel in (Nivel.CRITICO, Nivel.ATENCAO, Nivel.ERRO)
    ]
    conformes = [
        {"titulo": x.regra.titulo, "resumo": x.resumo, "regra": x.regra.id, "secao": SECAO.get(x.regra.secao)}
        for x in a.achados if x.nivel == Nivel.OK
    ]

    if a.classificacao == Classificacao.VERDE and not frases:
        frases.append("As verificações realizadas não encontraram sinal de alteração no arquivo.")
    if a.classificacao == Classificacao.VERDE:
        positivos.append("Isso não prova, sozinho, que o documento seja autêntico: indica que, nas verificações "
                         "feitas, nada aponta para alteração.")

    return {
        "titulo": titulo,
        "frases": frases,
        "positivos": positivos,
        "pontos": pontos,
        "conformes": conformes,
        "providencias": providencias,
        "ressalva": RESSALVA,
    }


def _titulo(c: Classificacao, ids: set[str]) -> str:
    if c == Classificacao.VERMELHO:
        if "ASS-01" in ids:
            return "O conteúdo assinado foi modificado depois da assinatura."
        if ids & {"ASS-03", "VER-03"}:
            return "O documento foi modificado depois de assinado."
        if "ASS-02" in ids:
            return "A assinatura digital do documento é inválida."
        return "Há evidências técnicas de alteração do documento."
    if c == Classificacao.AMARELO:
        if ids & {"VER-04", "CON-08", "MET-01", "MET-03"}:
            return "Há sinais de que o documento foi editado depois de criado."
        if "ASS-12" in ids:
            return "O documento não tem assinatura digital: sua integridade não pode ser confirmada apenas pelo arquivo."
        return "Não há sinal de alteração, mas há pontos que merecem atenção."
    return "Não foram encontrados sinais de alteração no documento."
