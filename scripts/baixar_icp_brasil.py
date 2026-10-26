"""
Baixa os certificados da ICP-Brasil do repositório oficial do ITI e grava em
confianca/icp-brasil/.

    python scripts/baixar_icp_brasil.py

  - As raízes (AC Raiz v1 a v13) são baixadas uma a uma por HTTPS verificado.
  - As ACs intermediárias vêm do pacote compactado, que o ITI só publica por
    HTTP. Isso não compromete a validação: um certificado intermediário só
    ganha confiança se tiver sido assinado por uma das raízes verificadas.
  - As raízes que também estão no pacote são conferidas byte a byte com as
    baixadas por HTTPS. Qualquer divergência interrompe o script.

O servidor do ITI não envia o certificado intermediário do seu próprio HTTPS.
O script o obtém pelo endereço indicado no certificado do servidor (AIA) e
valida a conexão normalmente contra as raízes do sistema operacional.
"""

import hashlib
import io
import socket
import ssl
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from asn1crypto import pem, x509

SERVIDOR = "acraiz.icpbrasil.gov.br"
URL_PACOTE = f"http://{SERVIDOR}/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.zip"
URL_RAIZ = f"https://{SERVIDOR}/credenciadas/RAIZ/ICP-Brasil{{}}.crt"
VERSOES_RAIZ = ["", "v2", "v4", "v5", "v6", "v7", "v10", "v11", "v12", "v13"]
DESTINO = Path(__file__).resolve().parent.parent / "confianca" / "icp-brasil"


def _der(dados: bytes) -> bytes:
    return pem.unarmor(dados)[2] if pem.detect(dados) else dados


def _contexto_https() -> ssl.SSLContext:
    """Contexto TLS com as raízes do sistema mais o intermediário que o servidor deixa de enviar."""
    contexto = ssl.create_default_context()
    sem_verificacao = ssl._create_unverified_context()
    with socket.create_connection((SERVIDOR, 443), timeout=30) as s:
        with sem_verificacao.wrap_socket(s, server_hostname=SERVIDOR) as tls:
            cert_servidor = x509.Certificate.load(tls.getpeercert(binary_form=True))
    urls = []
    aia = cert_servidor.authority_information_access_value
    for descricao in aia or []:
        if descricao["access_method"].native == "ca_issuers":
            urls.append(descricao["access_location"].native)
    for url in urls:
        with urllib.request.urlopen(url, timeout=30) as r:
            intermediario = _der(r.read())
        contexto.load_verify_locations(cadata=pem.armor("CERTIFICATE", intermediario).decode())
    return contexto


def baixar_raizes() -> dict[str, tuple[bytes, x509.Certificate]]:
    contexto = _contexto_https()
    raizes = {}
    for v in VERSOES_RAIZ:
        url = URL_RAIZ.format(v)
        with urllib.request.urlopen(url, timeout=60, context=contexto) as r:
            dados = r.read()
        cert = x509.Certificate.load(_der(dados))
        if cert.self_signed not in ("yes", "maybe"):
            raise SystemExit(f"{url} não é um certificado raiz autoassinado.")
        raizes[f"ICP-Brasil{v or 'v1'}.crt"] = (dados, cert)
        print(f"  raiz {cert.subject.native.get('common_name')}")
    return raizes


def main() -> int:
    print("Baixando raízes por HTTPS ...")
    raizes = baixar_raizes()
    hashes_raizes = {c.sha256 for _, c in raizes.values()}

    print(f"Baixando pacote de ACs intermediárias ({URL_PACOTE}) ...")
    with urllib.request.urlopen(URL_PACOTE, timeout=120) as r:
        pacote = r.read()

    intermediarios = {}
    with zipfile.ZipFile(io.BytesIO(pacote)) as z:
        for nome in sorted(z.namelist()):
            if nome.endswith("/"):
                continue
            dados = z.read(nome)
            try:
                cert = x509.Certificate.load(_der(dados))
                cert.subject
            except Exception:
                continue
            if cert.self_signed in ("yes", "maybe"):
                if cert.sha256 not in hashes_raizes:
                    raise SystemExit(f"A raiz {nome} do pacote não confere com nenhuma raiz baixada por HTTPS. "
                                     "Nada foi gravado.")
                continue
            intermediarios[Path(nome).name] = dados

    DESTINO.mkdir(parents=True, exist_ok=True)
    antigos = [p for p in DESTINO.iterdir() if p.is_file()]
    if antigos:
        arquivo = DESTINO.parent / f"icp-brasil-anterior-{datetime.now():%Y%m%d-%H%M%S}"
        arquivo.mkdir()
        for p in antigos:
            p.rename(arquivo / p.name)
        print(f"Certificados anteriores guardados em {arquivo}")

    for nome, (dados, _) in raizes.items():
        (DESTINO / nome).write_bytes(dados)
    for nome, dados in intermediarios.items():
        (DESTINO / nome).write_bytes(dados)

    linhas = [
        "Certificados da ICP-Brasil",
        f"Baixado em: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Raízes: {URL_RAIZ.format('<versão>')} (HTTPS verificado)",
        f"ACs intermediárias: {URL_PACOTE}",
        f"SHA-256 do pacote: {hashlib.sha256(pacote).hexdigest()}",
        f"Intermediárias gravadas: {len(intermediarios)}",
        "",
        "Raízes (SHA-256 do certificado · válida até):",
    ]
    for nome, (_, c) in sorted(raizes.items(), key=lambda x: x[1][1].not_valid_before):
        linhas.append(f"  {c.sha256.hex()}  {c.subject.native.get('common_name')} · {c.not_valid_after.date()}")
    (DESTINO / "MANIFESTO.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
