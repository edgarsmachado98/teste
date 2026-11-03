"""Atualização remota: só pacote assinado pelo fornecedor, íntegro e sem caminhos maliciosos."""

import base64
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]


def load_vendor_tool():
    spec = importlib.util.spec_from_file_location("fornecedor", ROOT / "deploy" / "assinatura" / "fornecedor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def vendor(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "fornecedor.key"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    pub = tmp_path / "fornecedor.pub"
    pub.write_text(base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                                  serialization.PublicFormat.Raw)).decode())
    monkeypatch.setenv("EDGE_FORNECEDOR_PUB", str(pub))
    return key, key_file


def test_signed_package_installs(vendor, tmp_path):
    from vigia_edge.updater import verify_and_extract
    tool = load_vendor_tool()
    z, s = tool.build_package("1.4.2", vendor[1], tmp_path / "pacotes")
    version, folder = verify_and_extract(z.read_bytes(), s.read_text(), tmp_path / "versoes")
    assert version == "1.4.2" and (folder / "vigia_detector" / "main.py").exists()
    assert '__version__ = "1.4.2"' in (folder / "vigia_edge" / "__init__.py").read_text()
    assert (folder / "requirements-edge.txt").exists()


def test_rejects_tampering_foreign_signature_and_traversal(vendor, tmp_path):
    from vigia_edge.updater import UpdateError, verify_and_extract
    tool = load_vendor_tool()
    z, s = tool.build_package("1.5.0", vendor[1], tmp_path / "pacotes")
    # arquivo alterado depois de assinado
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(z.read_bytes())) as src, zipfile.ZipFile(buf, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            dst.writestr(name, data + b"\n# malicioso" if name == "vigia_edge/app.py" else data)
    with pytest.raises(UpdateError, match="arquivo alterado"):
        verify_and_extract(buf.getvalue(), s.read_text(), tmp_path / "v1")
    # assinado por outra chave (ex.: quem invadiu a nuvem)
    other = Ed25519PrivateKey.generate()
    manifest = zipfile.ZipFile(io.BytesIO(z.read_bytes())).read("manifest.json")
    with pytest.raises(UpdateError, match="assinatura inválida"):
        verify_and_extract(z.read_bytes(), base64.b64encode(other.sign(manifest)).decode(), tmp_path / "v2")
    # caminho fora da pasta, mesmo assinado
    evil = b"print('x')"
    man = json.dumps({"app": "vigia-edge", "version": "9.9.9",
                      "files": {"../../fora.py": hashlib.sha256(evil).hexdigest()}}, sort_keys=True).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", man)
        zf.writestr("../../fora.py", evil)
    with pytest.raises(UpdateError, match="caminho inválido"):
        verify_and_extract(buf.getvalue(), base64.b64encode(vendor[0].sign(man)).decode(), tmp_path / "v3")
    assert not (tmp_path / "fora.py").exists()


def test_without_vendor_key_updates_are_disabled(tmp_path, monkeypatch):
    from vigia_edge.updater import UpdateError, verify_and_extract
    monkeypatch.setenv("EDGE_FORNECEDOR_PUB", str(tmp_path / "nao-existe.pub"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", b"{}")
    with pytest.raises(UpdateError, match="desativada"):
        verify_and_extract(buf.getvalue(), "AAAA", tmp_path)


def test_launcher_rollback_rules_and_versioned_launch(tmp_path):
    sys.path.insert(0, str(ROOT / "edge"))
    import planta
    state = {"current": "1.0.0", "pending": "1.1.0"}
    assert planta.plan(state) == ("1.1.0", True)
    assert planta.promote(state) == {"current": "1.1.0", "previous": "1.0.0", "pending": None}
    rolled = planta.rollback(state)
    assert rolled["pending"] is None and rolled["current"] == "1.0.0" and rolled["failed"] == ["1.1.0"]
    assert planta.plan(rolled) == ("1.0.0", False)
    assert planta.plan({}) == (None, False)
    # o comando usa o código da pasta da versão, não o da instalação
    vdir = tmp_path / "1.1.0" / "vigia_edge"
    vdir.mkdir(parents=True)
    (vdir / "__init__.py").write_text("")
    (vdir / "__main__.py").write_text("import sys, vigia_edge; print(vigia_edge.__file__, sys.argv[1:])")
    cmd, _cwd = planta.launch_cmds(tmp_path / "1.1.0")["edge"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    assert str(tmp_path / "1.1.0") in out and "['run']" in out
