import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import fabrica_pdfs as f  # noqa: E402


@pytest.fixture(scope="session")
def pasta(tmp_path_factory):
    return tmp_path_factory.mktemp("pdfs")


@pytest.fixture(scope="session")
def contrato(pasta):
    return f.criar_contrato(pasta / "contrato.pdf")


@pytest.fixture(scope="session")
def assinado(pasta, contrato):
    return f.assinar(contrato, pasta / "assinado.pdf", pasta)


@pytest.fixture(scope="session")
def confianca_teste(pasta, assinado):
    """Pasta de confiança só com a AC de testes que assinou o contrato."""
    conf = pasta / "confianca"
    (conf / "adicionais").mkdir(parents=True, exist_ok=True)
    shutil.copy(pasta / "raiz.pem", conf / "adicionais" / "raiz.pem")
    return conf
