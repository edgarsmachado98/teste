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
    # cinto paraquedista / talabarte (NR-35)
    "harness": "harness", "safety_harness": "harness", "fall_arrest": "harness", "fall_protection": "harness",
    "cinto": "harness", "cinturao": "harness", "cinto_paraquedista": "harness",
    "no_harness": "no_harness", "no_safety_harness": "no_harness",
    # botina / calçado de segurança
    "boots": "boots", "boot": "boots", "safety_boots": "boots", "safety_shoes": "boots", "shoes": "boots",
    "botina": "boots", "no_boots": "no_boots", "no_safety_shoes": "no_boots",
    # protetor auricular (concha ou plugue)
    "ear_protection": "ear_protection", "earmuffs": "ear_protection", "ear_muffs": "ear_protection",
    "ear_mufs": "ear_protection", "earplugs": "ear_protection", "ear_plug": "ear_protection",
    "hearing_protection": "ear_protection", "protetor_auricular": "ear_protection",
    "no_ear_protection": "no_ear_protection", "no_earmuffs": "no_ear_protection",
    # protetor facial / viseira
    "face_shield": "face_shield", "faceshield": "face_shield", "face_guard": "face_shield", "viseira": "face_shield",
    "protetor_facial": "face_shield", "no_face_shield": "no_face_shield",
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
