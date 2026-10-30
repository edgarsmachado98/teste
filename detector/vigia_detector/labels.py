"""Converte os rótulos de cada modelo para os nomes canônicos usados pelas regras.

Datasets públicos de EPI usam nomes variados ("Hardhat", "NO-Hardhat", "Safety Vest"...).
Ajuste ou acrescente via variável de ambiente LABEL_MAP='{"capacete": "helmet"}'."""

import json
import os

ALIASES = {
    "person": "person", "worker": "person", "pessoa": "person",
    "helmet": "helmet", "hardhat": "helmet", "hard_hat": "helmet", "capacete": "helmet",
    "no_helmet": "no_helmet", "no_hardhat": "no_helmet", "without_helmet": "no_helmet", "head": "no_helmet",
    "vest": "vest", "safety_vest": "vest", "reflective_vest": "vest", "colete": "vest",
    "no_vest": "no_vest", "no_safety_vest": "no_vest",
    "glasses": "glasses", "goggles": "glasses", "safety_glasses": "glasses",
    "no_glasses": "no_glasses", "no_goggles": "no_glasses",
    "gloves": "gloves", "glove": "gloves", "no_gloves": "no_gloves", "no_glove": "no_gloves",
    "mask": "mask", "face_mask": "mask", "no_mask": "no_mask",
    "fire": "fire", "flame": "fire", "fogo": "fire",
    "smoke": "smoke", "fumaca": "smoke",
}


def _normalize(label: str) -> str:
    return label.strip().lower().replace("-", "_").replace(" ", "_")


def load_aliases() -> dict[str, str]:
    aliases = dict(ALIASES)
    custom = os.getenv("LABEL_MAP", "").strip()
    if custom:
        aliases.update({_normalize(k): v for k, v in json.loads(custom).items()})
    return aliases


def canonical(label: str, aliases: dict[str, str]) -> str:
    key = _normalize(label)
    return aliases.get(key, key)
