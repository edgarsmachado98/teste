"""Módulos adicionais e licença.

O sistema base (carteira de investimentos) é sempre liberado. Módulos adicionais, vendidos à
parte, só aparecem e só respondem na API quando estão ativos nesta instalação.

Hoje a ativação é feita pela variável de ambiente CARTEIRA_MODULOS (ex.: "planejamento" ou
"todos") e, no modo demonstração, todos os módulos ficam ativos. Este é o ponto único de
verificação: quando houver chave de licença (assinada pelo fornecedor), basta trocar
`modulos_ativos` para validá-la, sem mexer nos módulos.
"""
import os

from .market import modo_demo

MODULOS = {
    "planejamento": {
        "nome": "Planejamento financeiro",
        "descricao": "Receitas, despesas, orçamento da família e objetivos financeiros.",
    },
}


def modulos_ativos():
    """Conjunto com os códigos dos módulos adicionais liberados nesta instalação."""
    valor = os.environ.get("CARTEIRA_MODULOS", "").strip().lower()
    if modo_demo() or valor in ("todos", "*", "all"):
        return set(MODULOS)
    return {m.strip() for m in valor.replace(";", ",").split(",") if m.strip() in MODULOS}


def modulo_ativo(codigo):
    return codigo in modulos_ativos()


def descrever():
    """Lista para a interface: todos os módulos, com a indicação de ativo ou não."""
    ativos = modulos_ativos()
    return [{"codigo": c, **info, "ativo": c in ativos} for c, info in MODULOS.items()]
