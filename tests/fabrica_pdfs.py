"""
Gera PDFs sintéticos para os testes: contrato simples, contrato assinado
e contrato assinado e alterado depois. Nenhum dado real é usado.
"""

import datetime as dt
from pathlib import Path

import pymupdf
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

TEXTO_CONTRATO = [
    "CONTRATO DE EMPRÉSTIMO PESSOAL (FICTÍCIO)",
    "Contratante: FULANO DE TAL",
    "Valor emprestado: R$ 1.000,00",
    "Parcelas: 10 x R$ 120,00",
]


def criar_contrato(caminho: Path, paginas: int = 2) -> Path:
    doc = pymupdf.open()
    for n in range(paginas):
        pagina = doc.new_page()
        y = 72
        for linha in TEXTO_CONTRATO:
            pagina.insert_text((72, y), linha, fontsize=12)
            y += 20
        pagina.insert_text((72, 760), f"Página {n + 1}", fontsize=9)
    doc.set_metadata({
        "producer": "Gerador de testes",
        "creator": "Gerador de testes",
        "creationDate": "D:20250110100000-03'00'",
        "modDate": "D:20250110100000-03'00'",
    })
    doc.save(str(caminho))
    doc.close()
    return caminho


def criar_certificados(pasta: Path, nome: str = "FULANO DE TAL:00000000000",
                       validade_dias: int = 365) -> tuple[Path, Path, Path]:
    """Cria uma AC raiz de teste e um certificado de signatário."""
    agora = dt.datetime.now(dt.timezone.utc)

    chave_ac = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome_ac = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AC de Testes"),
        x509.NameAttribute(NameOID.COMMON_NAME, "AC Raiz de Testes"),
    ])
    cert_ac = (
        x509.CertificateBuilder()
        .subject_name(nome_ac).issuer_name(nome_ac)
        .public_key(chave_ac.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(days=1))
        .not_valid_after(agora + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .sign(chave_ac, hashes.SHA256())
    )

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.COMMON_NAME, nome),
        ]))
        .issuer_name(nome_ac)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(days=1))
        .not_valid_after(agora + dt.timedelta(days=validade_dias))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(chave_ac, hashes.SHA256())
    )

    pem = serialization.Encoding.PEM
    raiz = pasta / "raiz.pem"
    raiz.write_bytes(cert_ac.public_bytes(pem))
    cert_path = pasta / "signatario.pem"
    cert_path.write_bytes(cert.public_bytes(pem))
    chave_path = pasta / "signatario.key"
    chave_path.write_bytes(chave.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return raiz, cert_path, chave_path


def assinar(origem: Path, destino: Path, pasta_certs: Path) -> Path:
    from pyhanko.sign import signers
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    raiz, cert, chave = criar_certificados(pasta_certs)
    signer = signers.SimpleSigner.load(
        str(chave), str(cert), ca_chain_files=(str(raiz),))
    with open(origem, "rb") as entrada, open(destino, "wb") as saida:
        writer = IncrementalPdfFileWriter(entrada)
        signers.sign_pdf(
            writer,
            signers.PdfSignatureMetadata(field_name="Assinatura1"),
            signer=signer,
            output=saida,
        )
    return destino


def alterar_depois(origem: Path, destino: Path, texto: str = "Valor emprestado: R$ 9.000,00") -> Path:
    """Simula adulteração: escreve texto novo na página 1 em atualização incremental."""
    destino.write_bytes(origem.read_bytes())
    doc = pymupdf.open(str(destino))
    pagina = doc[0]
    pagina.draw_rect(pymupdf.Rect(70, 100, 400, 118), color=(1, 1, 1), fill=(1, 1, 1))
    pagina.insert_text((72, 112), texto, fontsize=12, fontname="cour")
    doc.saveIncr()
    doc.close()
    return destino


def editar_sem_assinatura(origem: Path, destino: Path) -> Path:
    """Edição incremental em contrato sem assinatura (troca o valor das parcelas)."""
    return alterar_depois(origem, destino, "Parcelas: 10 x R$ 990,00")


def alterar_byte_assinado(origem: Path, destino: Path) -> Path:
    """Troca um único byte dentro da região coberta pela assinatura."""
    dados = bytearray(origem.read_bytes())
    pos = dados.find(b"R$ 1.000,00")
    if pos == -1:
        # o texto fica comprimido no fluxo da página: altera o metadado Producer
        pos = dados.find(b"Gerador de testes")
    dados[pos] = ord("X")
    destino.write_bytes(bytes(dados))
    return destino


def com_metadados(origem: Path, destino: Path, **campos) -> Path:
    doc = pymupdf.open(str(origem))
    meta = doc.metadata
    meta.update(campos)
    doc.set_metadata(meta)
    doc.save(str(destino))
    doc.close()
    return destino


def com_anexo_e_javascript(origem: Path, destino: Path) -> Path:
    import pikepdf
    with pikepdf.open(origem) as pdf:
        pdf.attachments["trilha.txt"] = pikepdf.AttachedFileSpec(pdf, b"registro da plataforma")
        acao = pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)")))
        pdf.Root.OpenAction = acao
        pdf.save(destino)
    return destino


def com_hash_da_versao_anterior(origem: Path, destino: Path) -> tuple[Path, str]:
    """Acrescenta, numa nova versão, uma página de 'trilha' que cita o SHA-256 da versão original."""
    import hashlib
    sha = hashlib.sha256(origem.read_bytes()).hexdigest()
    destino.write_bytes(origem.read_bytes())
    doc = pymupdf.open(str(destino))
    pagina = doc.new_page()
    pagina.insert_text((72, 72), "TRILHA DE AUDITORIA (FICTÍCIA)", fontsize=12)
    pagina.insert_text((72, 100), "Hash do documento original (SHA-256):", fontsize=9)
    pagina.insert_text((72, 114), sha[:32], fontsize=9, fontname="cour")
    pagina.insert_text((72, 126), sha[32:], fontsize=9, fontname="cour")
    pagina.insert_text((72, 150), "Hash qualquer: " + "ab" * 32, fontsize=9, fontname="cour")
    doc.saveIncr()
    doc.close()
    return destino, sha
