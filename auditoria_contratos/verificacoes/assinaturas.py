"""
Assinaturas digitais embutidas no PDF.

Para cada assinatura:
  - integridade: o hash do conteúdo coberto confere com o registrado na assinatura?
  - validade criptográfica: a assinatura confere com a chave do certificado?
  - alterações posteriores: o que foi acrescentado ao arquivo depois dela?
  - cadeia: o certificado leva a uma raiz confiável (ICP-Brasil)?
  - tempo: data declarada, carimbo do tempo e validade do certificado nessa data.

A validação é feita offline, só com os certificados da pasta confianca/.
A situação de revogação dos certificados não é consultada.
"""

import re
from datetime import datetime

from asn1crypto import x509

from .. import confianca, formatos
from ..documento import Documento
from ..modelos import Achado, Nivel
from ..regras import achado

OID_POLITICAS_ICP = "2.16.76.1.2."
OID_DADOS_PF = "2.16.76.1.3.1"
OID_CNPJ = "2.16.76.1.3.3"

NOMES_SUBFILTRO = {
    "/adbe.pkcs7.detached": "PKCS#7 destacada",
    "/adbe.pkcs7.sha1": "PKCS#7 com SHA-1",
    "/ETSI.CAdES.detached": "PAdES (CAdES destacada)",
    "/ETSI.RFC3161": "Carimbo do tempo do documento",
}

NOMES_COBERTURA = {
    "ENTIRE_FILE": "o arquivo inteiro",
    "ENTIRE_REVISION": "a versão em que foi feita (há versões posteriores)",
    "CONTIGUOUS_BLOCK_FROM_START": "um trecho inicial do arquivo",
    "UNCLEAR": "uma região indefinida do arquivo",
}

NOMES_MODIFICACAO = {
    "NONE": "nenhuma",
    "LTA_UPDATES": "apenas dados de validação ou carimbos do tempo",
    "FORM_FILLING": "preenchimento de campos de formulário ou novas assinaturas",
    "ANNOTATIONS": "anotações (comentários, carimbos, desenhos)",
    "OTHER": "alterações de conteúdo não permitidas",
}


def mascarar_cpf(cpf: str) -> str:
    if len(cpf) != 11 or not cpf.isdigit():
        return cpf
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**"


ROTULOS_NOME = {
    "common_name": "Nome",
    "organization_name": "Organização",
    "organizational_unit_name": "Unidade",
    "country_name": "País",
    "state_or_province_name": "Estado",
    "locality_name": "Cidade",
    "email_address": "E-mail",
    "serial_number": "Número de série",
}


SUFIXO_DOCUMENTO = re.compile(r":(\d{11}|\d{14})\b")


def _sem_documento(texto: str) -> str:
    """'FULANO DE TAL:12345678900' -> 'FULANO DE TAL' (certificados ICP-Brasil gravam o CPF no nome)."""
    return SUFIXO_DOCUMENTO.sub("", texto).strip()


def _mascarar_no_texto(texto: str) -> str:
    return SUFIXO_DOCUMENTO.sub(lambda m: ":" + (mascarar_cpf(m.group(1)) if len(m.group(1)) == 11 else m.group(1)), texto)


def _nome(nome: x509.Name) -> str:
    return nome.native.get("common_name") or _nome_completo(nome)


def _nome_completo(nome: x509.Name) -> str:
    partes = []
    for rdn in reversed(nome.chosen):
        for atributo in rdn:
            tipo = atributo["type"].native
            valor = atributo["value"].native
            partes.append(f"{ROTULOS_NOME.get(tipo, tipo)}: {valor}")
    return " · ".join(partes)


def _objetos_alterados(diff) -> list[int]:
    """Números dos objetos do PDF que o pyHanko apontou como alterados sem justificativa."""
    return sorted({int(n) for n in re.findall(r"idnum=(\d+)", str(diff))})


def _politicas(cert: x509.Certificate) -> list[str]:
    try:
        valor = cert.certificate_policies_value
        return [p["policy_identifier"].dotted for p in valor] if valor else []
    except Exception:
        return []


def _documentos_titular(cert: x509.Certificate, mascarar: bool) -> dict:
    """CPF e CNPJ gravados no certificado ICP-Brasil (campo otherName)."""
    docs = {}
    try:
        san = cert.subject_alt_name_value
    except Exception:
        san = None
    for nome in san or []:
        if nome.name != "other_name":
            continue
        try:
            tipo = nome.chosen["type_id"].dotted
            bruto = nome.chosen["value"].parsed.native
            texto = bruto.decode("latin-1") if isinstance(bruto, bytes) else str(bruto)
        except Exception:
            continue
        if tipo == OID_DADOS_PF and len(texto) >= 19:
            cpf = texto[8:19]
            docs["cpf"] = mascarar_cpf(cpf) if mascarar else cpf
        elif tipo == OID_CNPJ:
            cnpj = texto.strip()
            docs["cnpj"] = (f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
                            if len(cnpj) == 14 and cnpj.isdigit() else cnpj)
    return docs


def _data(valor) -> str | None:
    return valor.isoformat() if isinstance(valor, datetime) else None


def _contexto(conf: confianca.Confianca, momento: datetime | None = None):
    from pyhanko_certvalidator import ValidationContext
    kwargs = dict(
        trust_roots=conf.raizes,
        other_certs=conf.intermediarios,
        allow_fetching=False,
        revocation_mode="soft-fail",
    )
    if momento is not None:
        kwargs["moment"] = momento
    return ValidationContext(**kwargs)


def _validar(assinatura, conf, momento=None):
    from pyhanko.sign.validation import validate_pdf_signature
    return validate_pdf_signature(
        assinatura,
        signer_validation_context=_contexto(conf, momento),
        ts_validation_context=_contexto(conf, momento),
    )


def verificar(doc: Documento, conf: confianca.Confianca, mascarar_documentos: bool = True
              ) -> tuple[list[Achado], list[dict]]:
    achados: list[Achado] = []
    dados: list[dict] = []
    leitor = doc.leitor
    if leitor is None:
        return achados, dados

    assinaturas = list(leitor.embedded_regular_signatures)
    carimbos_documento = list(leitor.embedded_timestamp_signatures)

    if not assinaturas:
        achados.append(achado(
            "ASS-12",
            "Nenhuma assinatura digital foi encontrada no arquivo." + (
                f" Há {len(carimbos_documento)} carimbo(s) do tempo de documento."
                if carimbos_documento else ""),
        ))

    for indice, assinatura in enumerate(assinaturas, start=1):
        rotulo = f"Assinatura {indice}"
        try:
            info = _analisar(doc, assinatura, indice, conf, mascarar_documentos)
        except Exception as e:
            achados.append(achado("ASS-13", f"{rotulo}: erro ao validar.", erro=str(e)))
            continue
        dados.append(info)
        achados.extend(_achados_da_assinatura(rotulo, info))

    return achados, dados


def _analisar(doc, assinatura, indice, conf, mascarar) -> dict:
    status = _validar(assinatura, conf)
    cert = status.signing_cert

    data_declarada = status.signer_reported_dt
    carimbo = status.timestamp_validity
    data_carimbo = carimbo.timestamp if carimbo is not None else None
    carimbo_ok = bool(carimbo and carimbo.intact and carimbo.valid)
    melhor_data = data_carimbo if carimbo_ok else data_declarada

    validade_inicio = cert.not_valid_before
    validade_fim = cert.not_valid_after
    dentro_validade = None
    if melhor_data is not None:
        dentro_validade = validade_inicio <= melhor_data <= validade_fim

    # Sem consulta online, a cadeia é validada na data da assinatura. Se o
    # certificado venceu depois disso, a validação "na data de hoje" falharia
    # por um motivo que não diz nada sobre a assinatura.
    validado_em = "data atual"
    if not status.trusted and melhor_data is not None and dentro_validade:
        try:
            status_na_data = _validar(assinatura, conf, momento=melhor_data)
            if status_na_data.trusted:
                status = status_na_data
                validado_em = ("data do carimbo do tempo" if carimbo_ok
                               else "data declarada da assinatura")
        except Exception:
            pass

    cadeia = []
    if status.validation_path is not None:
        try:
            cadeia = [_nome(c.subject) for c in status.validation_path.iter_certs(include_root=True)]
            if mascarar:
                cadeia = [_mascarar_no_texto(c) for c in cadeia]
        except Exception:
            cadeia = []
    raiz = None
    if status.validation_path is not None:
        try:
            raiz_cert = status.validation_path.trust_anchor.authority.certificate
            raiz = raiz_cert
        except Exception:
            raiz = None

    politicas = _politicas(cert)
    politica_icp = [p for p in politicas if p.startswith(OID_POLITICAS_ICP)]
    cadeia_icp = bool(status.trusted and raiz is not None and conf.e_raiz_icp(raiz))

    sig_obj = assinatura.sig_object
    byte_range = [int(x) for x in sig_obj.get("/ByteRange", [])]
    versao = assinatura.signed_revision + 1
    if 0 < versao <= len(doc.versoes):
        doc.versoes[versao - 1].assinaturas.append(f"Assinatura {indice}")

    modificacao = status.modification_level.name if status.modification_level else None
    diff = status.diff_result
    detalhe_diff = str(diff) if isinstance(diff, Exception) else None
    objetos_alterados = _objetos_alterados(diff) if detalhe_diff else []

    return {
        "indice": indice,
        "campo": assinatura.field_name,
        "signatario": _sem_documento(_nome(cert.subject)),
        "signatario_completo": (_mascarar_no_texto if mascarar else str)(_nome_completo(cert.subject)),
        **_documentos_titular(cert, mascarar),
        "emissor": _nome(cert.issuer),
        "numero_serie": format(cert.serial_number, "X"),
        "validade_inicio": _data(validade_inicio),
        "validade_fim": _data(validade_fim),
        "politicas": politicas,
        "politica_icp": politica_icp,
        "cadeia": cadeia,
        "cadeia_confirmada": bool(status.trusted),
        "cadeia_icp": cadeia_icp,
        "validado_em": validado_em,
        "problema_confianca": status.trust_problem_indic.name if status.trust_problem_indic else None,
        "integra": bool(status.intact),
        "valida": bool(status.valid),
        "cobertura": status.coverage.name if status.coverage else None,
        "cobertura_texto": NOMES_COBERTURA.get(status.coverage.name, "") if status.coverage else "",
        "modificacao": modificacao,
        "modificacao_texto": NOMES_MODIFICACAO.get(modificacao, "") if modificacao else "",
        "docmdp_ok": status.docmdp_ok,
        "detalhe_modificacao": detalhe_diff,
        "objetos_alterados": objetos_alterados,
        "versao_assinada": versao,
        "byte_range": byte_range,
        "data_declarada": _data(data_declarada),
        "carimbo": None if carimbo is None else {
            "data": _data(data_carimbo),
            "integro": bool(carimbo.intact),
            "valido": bool(carimbo.valid),
            "confiavel": bool(carimbo.trusted),
            "emissor": _nome(carimbo.signing_cert.subject) if carimbo.signing_cert else None,
        },
        "dentro_validade": dentro_validade,
        "algoritmo_hash": status.md_algorithm,
        "mecanismo": status.pkcs7_signature_mechanism,
        "formato": NOMES_SUBFILTRO.get(str(sig_obj.get("/SubFilter", "")), str(sig_obj.get("/SubFilter", ""))),
        "motivo": str(sig_obj.get("/Reason", "")) or None,
        "local": str(sig_obj.get("/Location", "")) or None,
    }


def _achados_da_assinatura(rotulo: str, info: dict) -> list[Achado]:
    a = []
    ev = {
        "Assinatura": rotulo,
        "Signatário": info["signatario"],
        "Versão assinada": info["versao_assinada"],
        "Faixa de bytes assinada (ByteRange)": info["byte_range"],
    }

    if not info["integra"]:
        a.append(achado("ASS-01", f"{rotulo} ({info['signatario']}): o hash do conteúdo assinado não confere.", **ev))
    elif not info["valida"]:
        a.append(achado("ASS-02", f"{rotulo} ({info['signatario']}): assinatura inválida.", **ev))
    else:
        mod = info["modificacao"]
        if mod == "OTHER" or info["docmdp_ok"] is False:
            a.append(achado(
                "ASS-03",
                f"{rotulo} ({info['signatario']}): o arquivo recebeu alterações de conteúdo "
                f"depois desta assinatura, que cobre apenas a versão {info['versao_assinada']}.",
                **ev, **({"Objetos do PDF alterados sem justificativa": info["objetos_alterados"]}
                         if info["objetos_alterados"] else {}),
            ))
        elif mod in ("FORM_FILLING", "ANNOTATIONS"):
            a.append(achado(
                "ASS-04",
                f"{rotulo} ({info['signatario']}): depois desta assinatura houve "
                f"{info['modificacao_texto']}.",
                **ev,
            ))
        else:
            a.append(achado("ASS-05", f"{rotulo} ({info['signatario']}): íntegra e sem alterações posteriores.", **ev))

    if info["cadeia_icp"] or info["politica_icp"]:
        origem = []
        if info["cadeia_icp"]:
            origem.append("cadeia confirmada até a AC Raiz da ICP-Brasil")
        if info["politica_icp"]:
            origem.append("política de certificação ICP-Brasil " + ", ".join(info["politica_icp"]))
        a.append(achado("ASS-07", f"{rotulo}: certificado ICP-Brasil ({'; '.join(origem)}).",
                        Emissor=info["emissor"], Cadeia=info["cadeia"]))
    elif info["integra"] and info["valida"]:
        # Com a assinatura comprometida a cadeia nem chega a ser avaliada: não dá para afirmar a origem.
        a.append(achado("ASS-08", f"{rotulo}: certificado emitido por {info['emissor']}, fora da ICP-Brasil.",
                        Assinatura=rotulo, Emissor=info["emissor"]))

    if not info["cadeia_confirmada"] and info["integra"] and info["valida"]:
        a.append(achado("ASS-06", f"{rotulo}: não foi possível ligar o certificado a uma raiz confiável.",
                        Emissor=info["emissor"], Motivo=info["problema_confianca"]))

    carimbo = info["carimbo"]
    if carimbo is None:
        a.append(achado("ASS-10", f"{rotulo}: sem carimbo do tempo; data declarada {formatos.data(info['data_declarada']) if info['data_declarada'] else 'ausente'}.",
                        **{"Data declarada": formatos.data(info["data_declarada"])}))
    elif carimbo["integro"] and carimbo["valido"]:
        a.append(achado("ASS-11", f"{rotulo}: carimbo do tempo de {formatos.data(carimbo['data'])}, emitido por {carimbo['emissor']}.",
                        **{"Data do carimbo": formatos.data(carimbo["data"]), "Autoridade": carimbo["emissor"],
                           "Autoridade reconhecida": "sim" if carimbo["confiavel"] else "não"}))
    else:
        nivel = Nivel.CRITICO if not carimbo["integro"] else None
        a.append(achado("ASS-14", f"{rotulo}: o carimbo do tempo não pôde ser confirmado.", nivel=nivel,
                        **{"Íntegro": carimbo["integro"], "Válido": carimbo["valido"]}))

    if info["dentro_validade"] is False:
        a.append(achado("ASS-09", f"{rotulo}: a data da assinatura está fora da validade do certificado.",
                        **{"Data considerada": formatos.data((carimbo or {}).get("data") or info["data_declarada"]),
                           "Válido de": formatos.data(info["validade_inicio"]),
                           "Válido até": formatos.data(info["validade_fim"])}))
    return a
