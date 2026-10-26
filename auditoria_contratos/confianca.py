"""
Certificados de confiança usados para validar a cadeia das assinaturas.

Ficam em confianca/ na raiz do projeto:
  confianca/icp-brasil/   certificados das ACs da ICP-Brasil (scripts/baixar_icp_brasil.py)
  confianca/adicionais/   outros certificados que você queira reconhecer como raiz

Certificados autoassinados viram raízes de confiança; os demais servem só para
completar a cadeia. O relatório lista as raízes usadas, com o hash de cada uma,
para que a validação possa ser refeita com exatamente os mesmos certificados.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from asn1crypto import pem, x509

PASTA_CONFIANCA = Path(__file__).resolve().parent.parent / "confianca"


@dataclass
class Confianca:
    raizes: list[x509.Certificate] = field(default_factory=list)
    intermediarios: list[x509.Certificate] = field(default_factory=list)
    raizes_icp: set[bytes] = field(default_factory=set)

    def descricao_raizes(self) -> list[dict]:
        return [
            {
                "nome": c.subject.native.get("common_name", c.subject.human_friendly),
                "sha256": c.sha256.hex(),
                "validade": c.not_valid_after.date().isoformat(),
                "icp_brasil": c.sha256 in self.raizes_icp,
            }
            for c in self.raizes
        ]

    def e_raiz_icp(self, cert: x509.Certificate) -> bool:
        return cert.sha256 in self.raizes_icp


def _ler_certificados(pasta: Path) -> list[x509.Certificate]:
    certs = []
    if not pasta.is_dir():
        return certs
    for arquivo in sorted(pasta.rglob("*")):
        if not arquivo.is_file() or arquivo.suffix.lower() not in (".crt", ".cer", ".pem", ".der"):
            continue
        dados = arquivo.read_bytes()
        blocos = [d for _, _, d in pem.unarmor(dados, multiple=True)] if pem.detect(dados) else [dados]
        for der in blocos:
            try:
                cert = x509.Certificate.load(der)
                cert.subject  # força a leitura
                certs.append(cert)
            except Exception:
                continue
    return certs


def _autoassinado(cert: x509.Certificate) -> bool:
    return cert.self_signed in ("yes", "maybe")


@lru_cache(maxsize=4)
def carregar(pasta: Path = PASTA_CONFIANCA) -> Confianca:
    conf = Confianca()
    vistos = set()
    for subpasta in ("icp-brasil", "adicionais"):
        for cert in _ler_certificados(pasta / subpasta):
            if cert.sha256 in vistos:
                continue
            vistos.add(cert.sha256)
            if _autoassinado(cert):
                conf.raizes.append(cert)
                if subpasta == "icp-brasil":
                    conf.raizes_icp.add(cert.sha256)
            else:
                conf.intermediarios.append(cert)
    conf.raizes.sort(key=lambda c: c.subject.human_friendly)
    return conf
