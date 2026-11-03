"""Criptografia das imagens no storage do cliente (AES-256-GCM).

Quem tem acesso ao NAS (ou rouba um disco) vê só dados embaralhados. A chave fica no Edge e uma cópia,
cifrada com a chave da instância, fica na nuvem: se a máquina do Edge for trocada, o Edge novo da mesma
unidade recebe as chaves antigas no cadastro e continua lendo as imagens já gravadas.

Formato do arquivo: b"VGE1" + id da chave (4 bytes) + nonce (12 bytes) + conteúdo cifrado (com etiqueta GCM).
Arquivos sem o prefixo (gravados antes da criptografia) continuam sendo lidos normalmente."""

import base64
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("vigia.edge.crypto")

MAGIC = b"VGE1"


class MediaCipher:
    def __init__(self, keys: dict[str, str], active_kid: str):
        self.keys = {bytes.fromhex(kid): AESGCM(base64.b64decode(key)) for kid, key in keys.items()}
        self.active = bytes.fromhex(active_kid)
        if self.active not in self.keys:
            raise ValueError("chave ativa ausente")

    def seal(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + self.active + nonce + self.keys[self.active].encrypt(nonce, data, None)

    def open(self, blob: bytes) -> bytes | None:
        if not blob.startswith(MAGIC):
            return blob  # arquivo antigo, sem criptografia
        kid, nonce, body = blob[4:8], blob[8:20], blob[20:]
        aes = self.keys.get(kid)
        if aes is None:
            log.error("arquivo cifrado com chave desconhecida %s", kid.hex())
            return None
        try:
            return aes.decrypt(nonce, body, None)
        except InvalidTag:
            log.error("arquivo cifrado adulterado ou corrompido")
            return None


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(MAGIC)
