"""Módulos adicionais e licença.

O sistema base (carteira de investimentos) é sempre liberado. Módulos adicionais, vendidos à
parte, só aparecem e só respondem na API quando estão ativos nesta instalação.

FASE DE TESTES: sem a variável CARTEIRA_MODULOS, todos os módulos ficam ativos (liberados para
testar e atualizados junto com o sistema). Para restringir, defina CARTEIRA_MODULOS com a lista
(ex.: "planejamento") ou "nenhum". Este é o ponto único de verificação: quando o módulo passar a ser
vendido, troque LIBERADO_EM_TESTE para False e valide aqui a chave de licença, sem mexer nos módulos.
"""
import os

from .market import modo_demo

MODULOS = {
    "planejamento": {
        "nome": "Planejamento financeiro",
        "descricao": "Receitas, despesas, orçamento da família e objetivos financeiros.",
    },
}


LIBERADO_EM_TESTE = True  # período de testes: módulos liberados quando CARTEIRA_MODULOS não está definida


def modulos_ativos():
    """Conjunto com os códigos dos módulos adicionais liberados nesta instalação."""
    valor = os.environ.get("CARTEIRA_MODULOS", "").strip().lower()
    if valor in ("nenhum", "none", "0"):
        return set()
    if modo_demo() or valor in ("todos", "*", "all") or (LIBERADO_EM_TESTE and not valor):
        return set(MODULOS)
    return {m.strip() for m in valor.replace(";", ",").split(",") if m.strip() in MODULOS}


def modulo_ativo(codigo):
    return codigo in modulos_ativos()


def descrever():
    """Lista para a interface: todos os módulos, com a indicação de ativo ou não."""
    ativos = modulos_ativos()
    return [{"codigo": c, **info, "ativo": c in ativos} for c, info in MODULOS.items()]
