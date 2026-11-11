"""Conferência do patrimônio do sistema com os relatórios de posição importados.

Junta o último relatório de cada origem (B3, Banco do Brasil, Tesouro Direto...) pelas mesmas
regras da importação (a B3 prevalece nos ativos de bolsa e Tesouro) e compara ativo a ativo
com a posição calculada pelo sistema, explicando de onde vem cada diferença.
"""
from collections import defaultdict

from .importacao import mesclar_posicoes

TOLERANCIA_QTD = 1e-6


def _tolerancia_valor(valor):
    """Diferença de valor considerada "confere": R$ 1 ou 0,5%."""
    return max(1.0, abs(valor) * 0.005)


def ultimos_por_origem(relatorios):
    """Mantém só o relatório mais recente de cada origem (e todos os arquivos daquela importação)."""
    if any(r["origem"].startswith("Tesouro Direto ·") for r in relatorios):
        # versões antigas gravavam todos os extratos do Tesouro como "Tesouro Direto": substituídos
        relatorios = [r for r in relatorios if r["origem"] != "Tesouro Direto"]
    mais_recente = {}
    for r in relatorios:
        if r["importado_em"] > mais_recente.get(r["origem"], ""):
            mais_recente[r["origem"]] = r["importado_em"]
    return [r for r in relatorios if r["importado_em"] == mais_recente[r["origem"]]]


def conferir(relatorios, linhas_sistema, rotulos_classe):
    """relatorios: [{origem, nome, importado_em, itens}]; linhas_sistema: linhas do resumo da carteira."""
    relatorios = ultimos_por_origem(relatorios)
    esperado, conflitos = mesclar_posicoes([(r["nome"], r["origem"], r["itens"]) for r in relatorios])
    no_rel = {p["ticker"]: p for p in esperado}
    no_sis = {l["ticker"]: l for l in linhas_sistema if l["quantidade"] > TOLERANCIA_QTD}

    itens = []
    for t in sorted(set(no_rel) | set(no_sis)):
        r, s = no_rel.get(t), no_sis.get(t)
        classe = (s or {}).get("classe") or (r or {}).get("classe") or "outro"
        q_rel, v_rel = (r["quantidade"], r.get("valor_atual") or 0.0) if r else (0.0, 0.0)
        q_sis, v_sis = (s["quantidade"], s["valor"]) if s else (0.0, 0.0)
        if r and s:
            mesma_qtd = abs(q_rel - q_sis) <= TOLERANCIA_QTD * max(1.0, q_rel) or (r.get("sem_quantidade") and q_sis == 1)
            if not mesma_qtd:
                situacao = "quantidade"
            elif abs(v_sis - v_rel) <= _tolerancia_valor(v_rel) or not v_rel:
                situacao = "confere"
            else:
                situacao = "cotacao"
        else:
            situacao = "so_sistema" if s else "so_relatorio"
        itens.append({"ticker": t, "classe": classe, "rotulo_classe": rotulos_classe.get(classe, classe),
                      "origem": (r or {}).get("origem"), "qtd_relatorio": q_rel, "qtd_sistema": q_sis,
                      "valor_relatorio": v_rel, "valor_sistema": v_sis, "diferenca": v_sis - v_rel,
                      "situacao": situacao, "dica": None})

    # Renda fixa só no sistema com valor parecido a um título do relatório: provável nome diferente
    rf_rel = [i for i in itens if i["situacao"] in ("confere", "cotacao", "quantidade")
              and i["classe"] not in ("acao", "fii", "etf", "bdr")]
    for i in itens:
        if i["situacao"] != "so_sistema" or i["classe"] in ("acao", "fii", "etf", "bdr"):
            continue
        parecido = min(rf_rel, key=lambda x: abs(x["valor_relatorio"] - i["valor_sistema"]), default=None)
        if parecido and abs(parecido["valor_relatorio"] - i["valor_sistema"]) <= max(50.0, i["valor_sistema"] * 0.03):
            i["dica"] = (f"Valor parecido com {parecido['ticker']} ({parecido['origem']}): pode ser o mesmo "
                         "título com outro nome, contado duas vezes.")
        else:
            i["dica"] = "Não está nos relatórios: confira se é de outra instituição ou se foi resgatado."

    por_situacao = defaultdict(float)
    for i in itens:
        por_situacao[i["situacao"]] += i["diferenca"]
    categorias = defaultdict(lambda: {"valor_relatorio": 0.0, "valor_sistema": 0.0})
    for i in itens:
        c = categorias[i["rotulo_classe"]]
        c["valor_relatorio"] += i["valor_relatorio"]
        c["valor_sistema"] += i["valor_sistema"]
    total_rel = sum(i["valor_relatorio"] for i in itens)
    total_sis = sum(i["valor_sistema"] for i in itens)
    return {
        "relatorios": [{"origem": r["origem"], "nome": r["nome"], "importado_em": r["importado_em"],
                        "total": sum(x.get("valor_atual") or 0.0 for x in r["itens"]), "ativos": len(r["itens"])}
                       for r in relatorios],
        "total_relatorios": total_rel, "total_sistema": total_sis, "diferenca": total_sis - total_rel,
        "explicacao": {k: por_situacao.get(k, 0.0) for k in ("cotacao", "quantidade", "so_sistema", "so_relatorio")},
        "categorias": sorted(({"categoria": k, **v, "diferenca": v["valor_sistema"] - v["valor_relatorio"]}
                              for k, v in categorias.items()), key=lambda x: -x["valor_sistema"]),
        "itens": itens,
        "sobrepostos": [c for c in conflitos if c["acao"] == "usada a posição da B3"],
    }
