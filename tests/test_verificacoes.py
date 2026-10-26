import fabrica_pdfs as f
from auditoria_contratos.auditoria import auditar
from auditoria_contratos.modelos import Classificacao


def ids(resultado):
    return {a.regra.id for a in resultado.achados}


def test_contrato_sem_assinatura(contrato, confianca_teste):
    r = auditar(contrato, confianca_teste)
    assert "ASS-12" in ids(r)
    assert "VER-01" in ids(r)
    assert r.classificacao == Classificacao.AMARELO


def test_assinatura_integra(assinado, confianca_teste):
    r = auditar(assinado, confianca_teste)
    assert {"ASS-05", "VER-05"} <= ids(r)
    assert not ids(r) & {"ASS-01", "ASS-02", "ASS-03", "ASS-06", "VER-03"}
    s = r.assinaturas[0]
    assert s["integra"] and s["valida"] and s["cadeia_confirmada"]
    assert s["cobertura"] == "ENTIRE_FILE"
    assert s["cadeia"] == ["AC Raiz de Testes", "FULANO DE TAL:***.000.000-**"]
    assert s["signatario"] == "FULANO DE TAL"


def test_cadeia_sem_raiz_confiavel(assinado, tmp_path):
    r = auditar(assinado, tmp_path)  # pasta vazia: nenhuma raiz
    assert "ASS-06" in ids(r)


def test_alteracao_depois_da_assinatura(pasta, assinado, confianca_teste):
    alterado = f.alterar_depois(assinado, pasta / "alterado.pdf")
    r = auditar(alterado, confianca_teste)
    assert {"ASS-03", "VER-03", "CON-08"} <= ids(r)
    assert r.classificacao == Classificacao.VERMELHO
    final = r.versoes[-1]
    assert final["contexto"] == "apos_assinatura"
    pagina = final["mudancas"]["paginas_alteradas"][0]
    assert pagina["pagina"] == 1
    assert "Valor emprestado: R$ 9.000,00" in pagina["texto_acrescentado"]
    assert pagina["imagem_antes"] and pagina["imagem_depois"]
    encoberto = r.conteudo["texto_coberto"][0]
    assert encoberto["texto"] == "Valor emprestado: R$ 1.000,00"
    assert "branco" in encoberto["coberto_por"]


def test_byte_alterado_no_conteudo_assinado(pasta, assinado, confianca_teste):
    adulterado = f.alterar_byte_assinado(assinado, pasta / "byte.pdf")
    r = auditar(adulterado, confianca_teste)
    assert "ASS-01" in ids(r)
    assert "ASS-06" not in ids(r)  # com o conteúdo violado a cadeia nem é avaliada
    assert r.classificacao == Classificacao.VERMELHO


def test_edicao_em_contrato_sem_assinatura(pasta, contrato, confianca_teste):
    editado = f.editar_sem_assinatura(contrato, pasta / "editado.pdf")
    r = auditar(editado, confianca_teste)
    assert {"VER-02", "VER-04", "CON-08"} <= ids(r)
    assert "VER-03" not in ids(r)
    assert r.versoes[-1]["contexto"] == "sem_assinatura"


def test_versoes_extraidas_conferem(pasta, assinado):
    alterado = f.alterar_depois(assinado, pasta / "alterado2.pdf")
    r = auditar(alterado)
    import hashlib
    dados = alterado.read_bytes()
    for v in r.versoes:
        assert hashlib.sha256(dados[: v["tamanho"]]).hexdigest() == v["hashes"]["sha256"]
    # a versão assinada termina exatamente onde termina a faixa de bytes da assinatura
    br = r.assinaturas[0]["byte_range"]
    assert r.versoes[r.assinaturas[0]["versao_assinada"] - 1]["tamanho"] == br[2] + br[3]


def test_metadados_incoerentes(pasta, contrato):
    pdf = f.com_metadados(contrato, pasta / "meta.pdf",
                          creationDate="D:20250110100000-03'00'", modDate="D:20240101100000-03'00'",
                          producer="iLovePDF")
    r = auditar(pdf)
    assert {"MET-01", "MET-03"} <= ids(r)


def test_anexo_e_javascript(pasta, contrato):
    pdf = f.com_anexo_e_javascript(contrato, pasta / "ativo.pdf")
    r = auditar(pdf)
    assert {"CON-01", "CON-03"} <= ids(r)
    assert r.conteudo["anexos"][0]["nome"] == "trilha.txt"


def test_hash_citado_confere_com_versao_original(pasta, contrato):
    pdf, sha = f.com_hash_da_versao_anterior(contrato, pasta / "trilha.pdf")
    r = auditar(pdf)
    citados = {h["valor"]: h for h in r.hashes_citados}
    assert citados[sha]["confere_com"] == "a versão 1 do arquivo"
    assert citados["ab" * 32]["confere_com"] is None
    assert {"HSH-01", "HSH-02"} <= ids(r)
    # página nova acrescentada sem assinatura nenhuma
    assert r.versoes[-1]["mudancas"]["paginas_acrescentadas"] == [3]


def test_pdf_linearizado_nao_conta_como_duas_versoes(pasta, contrato):
    import pikepdf
    destino = pasta / "linear.pdf"
    with pikepdf.open(contrato) as pdf:
        pdf.save(destino, linearize=True)
    r = auditar(destino)
    assert len(r.versoes) == 1


def test_arquivo_que_nao_e_pdf(tmp_path):
    falso = tmp_path / "falso.pdf"
    falso.write_text("isto não é um PDF")
    r = auditar(falso)
    assert "DOC-01" in ids(r)
