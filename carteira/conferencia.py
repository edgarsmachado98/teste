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


CLASSES_BOLSA = ("acao", "fii", "etf", "bdr")
DIAS_LIQUIDACAO = 5  # compras desses últimos dias podem ainda não constar na posição da B3 (liquidação D+2)


def _eh_posicao_inicial(op):
    return (op.get("obs") or "").startswith("posição inicial (") or op.get("ajuste") == "compra"


def _igual(a, b):
    return abs(a - b) <= TOLERANCIA_QTD * max(1.0, abs(a), abs(b))


def sugerir_correcao(item, ops, data_relatorio):
    """Sugestão para um ativo com quantidade diferente do relatório.

    ops: lançamentos do sistema para o ativo (aportes, sem eventos). Retorna {acao, texto, ids?, quantidade?}:
      excluir   um lançamento de posição inicial/ajuste com exatamente a quantidade que sobra (em dobro)
      nada      compras dos últimos dias explicam a sobra (ainda não liquidadas na data do relatório)
      ajustar   lança um ajuste para igualar ao relatório (baixa sem resultado ou compra)
    """
    excesso = round(item["qtd_sistema"] - item["qtd_relatorio"], 8)
    if abs(excesso) <= TOLERANCIA_QTD:
        return None
    def dmy(d):
        return "/".join(reversed(d.split("-")))
    if excesso > 0:
        iniciais = sorted((o for o in ops if o.get("tipo", "compra") == "compra" and _eh_posicao_inicial(o)),
                          key=lambda o: o["data"])
        iguais = [o for o in iniciais if _igual(float(o["quantidade"]), excesso)]
        if iguais and (len(iniciais) > 1 or len(iguais) == len(iniciais)):
            o = iguais[0]  # a mais antiga: em geral sobra de uma importação anterior
            return {"acao": "excluir", "ids": [o["id"]],
                    "texto": f"Sobram {excesso:g} e há uma posição inicial de {float(o['quantidade']):g} em "
                             f"{dmy(o['data'])} ({o.get('obs') or 'ajuste'}): parece lançada em dobro."}
        if data_relatorio:
            limite = data_relatorio[:10]
            recentes = [o for o in ops if o.get("tipo", "compra") == "compra" and o["data"] >= _menos_dias(limite)]
            if recentes and _igual(sum(float(o["quantidade"]) for o in recentes), excesso):
                return {"acao": "nada",
                        "texto": "Compra recente (" + ", ".join(dmy(o["data"]) for o in recentes) + ") ainda não "
                                 "liquidada na data do relatório: o sistema está certo, nada a fazer."}
        return {"acao": "ajustar", "quantidade": -excesso,
                "texto": f"O sistema tem {excesso:g} a mais. Confira no app da corretora; se o relatório estiver "
                         "certo, ajuste com uma baixa sem resultado (sai pelo preço médio, fora do IR)."}
    return {"acao": "ajustar", "quantidade": -excesso,
            "texto": f"Faltam {-excesso:g} no sistema. Importe a negociação do período ou ajuste com uma compra "
                     "pelo valor do relatório."}


def _menos_dias(data_iso, dias=DIAS_LIQUIDACAO):
    import datetime as dt
    return (dt.date.fromisoformat(data_iso) - dt.timedelta(days=dias)).isoformat()


def conferir(relatorios, linhas_sistema, rotulos_classe, operacoes=()):
    """relatorios: [{origem, nome, importado_em, itens}]; linhas_sistema: linhas do resumo da carteira;
    operacoes: aportes da carteira (para sugerir correções nas diferenças de quantidade)."""
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

    # Sugestões de correção para diferenças de quantidade (ativos de bolsa)
    data_por_origem = {r["origem"]: r["importado_em"] for r in relatorios}
    data_geral = max(data_por_origem.values(), default=None)
    ops_por_ticker = defaultdict(list)
    for o in operacoes:
        if o.get("tipo") != "evento":
            ops_por_ticker[o["ticker"]].append(o)
    for i in itens:
        i["sugestao"] = None
        if i["situacao"] in ("quantidade", "so_sistema", "so_relatorio") and i["classe"] in CLASSES_BOLSA:
            data_ref = data_por_origem.get((i["origem"] or "").split(" + ")[0]) or data_geral
            i["sugestao"] = sugerir_correcao(i, ops_por_ticker.get(i["ticker"], []), data_ref)
            ref = no_rel.get(i["ticker"]) or {}
            i["preco_relatorio"] = ref.get("preco_atual") or (
                ref.get("valor_atual") / ref["quantidade"] if ref.get("valor_atual") and ref.get("quantidade") else None)
            if i["situacao"] == "so_sistema" and i["sugestao"]:
                i["dica"] = None
        i["lancamentos"] = [{k: o.get(k) for k in ("id", "data", "tipo", "quantidade", "preco", "obs", "ajuste")}
                            for o in sorted(ops_por_ticker.get(i["ticker"], []), key=lambda o: o["data"])
                            ] if i["situacao"] in ("quantidade", "so_sistema") else []

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
