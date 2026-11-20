"""Diagnóstico da página da NFC-e no portal da Sefaz (estrutura e texto com os números mascarados).

Usado pelo botão "Ver diagnóstico" da leitura de nota e pelo diagnostico_nfce.py, para ajustar o leitor
ao layout de cada estado. Nenhum dado é enviado para fora: o texto é mostrado para o usuário copiar.
"""
import html
import re
from collections import Counter

from . import nfce


def _mostrar(saida, *partes):
    saida.append(" ".join(str(p) for p in partes))


def mascarar(texto):
    return re.sub(r"\d", "9", str(texto))


def resumo_da_pagina(saida, url, pagina):
    mostrar = lambda *p: _mostrar(saida, *p)  # noqa: E731
    mostrar(f"\n=== Página: {mascarar(url.split('?')[0])}  ({len(pagina)} caracteres)")
    titulo = re.search(r"(?is)<title[^>]*>(.*?)</title>", pagina)
    mostrar("Título:", mascarar(titulo.group(1).strip()) if titulo else "—")
    mostrar("Tem os dados no formato conhecido:", "sim" if nfce.tem_dados(pagina) else "não")
    for palavra in ("captcha", "recaptcha", "hcaptcha", "turnstile", "robô", "robo"):
        if palavra in pagina.lower():
            mostrar("Aviso: a página menciona", palavra)
    for destino in nfce.proximos_enderecos(url, pagina):
        mostrar("Leva para:", mascarar(destino.split("?")[0]), "(com parâmetros)" if "?" in destino else "")
    for k, m in enumerate(re.finditer(r"(?is)<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", pagina)):
        codigo = m.group(1).strip()
        if not codigo or k >= 8:
            continue
        enderecos = sorted(set(re.findall(r"""["'](https?://[^"'\s]+|/[A-Za-z][^"'\s]{3,})["']""", codigo)))
        mostrar(f"Script interno {k + 1} ({len(codigo)} caracteres):", mascarar(re.sub(r"\s+", " ", codigo)[:300]))
        if enderecos:
            mostrar("   endereços no script:", ", ".join(mascarar(e.split("?")[0]) for e in enderecos)[:500])
    for m in re.finditer(r"(?is)<form[^>]*>", pagina):
        mostrar("Formulário:", mascarar(re.sub(r"\s+", " ", m.group(0))[:200]))
    nomes = re.findall(r"""(?i)<input[^>]+name=["']([^"']+)["']""", pagina)
    if nomes:
        mostrar("Campos:", ", ".join(sorted(set(nomes)))[:500])
    scripts = re.findall(r"""(?i)<script[^>]+src=["']([^"']+)["']""", pagina)
    if scripts:
        mostrar("Scripts:", ", ".join(s.split("?")[0] for s in scripts)[:600])
    classes = Counter(c for grupo in re.findall(r"""class=["']([^"']+)["']""", pagina) for c in grupo.split())
    mostrar("Classes mais usadas:", ", ".join(f"{c}({n})" for c, n in classes.most_common(40)))
    ids = re.findall(r"""\sid=["']([^"']+)["']""", pagina)
    mostrar("Ids:", ", ".join(dict.fromkeys(ids))[:600])
    texto = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", pagina)
    texto = re.sub(r"<[^>]+>", "\n", texto)
    linhas = [re.sub(r"\s+", " ", html.unescape(l)).strip() for l in texto.splitlines()]
    linhas = [l for l in linhas if l]
    mostrar(f"Texto da página ({len(linhas)} linhas, números mascarados):")
    for l in linhas[:150]:
        mostrar("   ", mascarar(l)[:160])


def diagnosticar(texto, abrir=None):
    """Texto do diagnóstico (números mascarados) da página da nota no portal da Sefaz."""
    abrir = abrir or nfce._abrir
    saida = []
    mostrar = lambda *p: _mostrar(saida, *p)  # noqa: E731
    texto = (texto or "").strip()
    try:
        dados = nfce.ler_qrcode(texto)
    except nfce.ErroNota as e:
        mostrar("QR Code não reconhecido:", e)
        return "\n".join(saida)
    mostrar("Estado da nota:", dados["uf"], "| modelo", dados["modelo"], "| versão do QR", dados.get("versao"))
    url = dados.get("url")
    if not url:
        mostrar("Só a chave foi informada: use o link completo do QR Code.")
        return "\n".join(saida)
    try:
        pagina = abrir(url)
        resumo_da_pagina(saida, url, pagina)
        visitados = {url}
        for _ in range(3):
            proximos = [u for u in nfce.proximos_enderecos(url, pagina) if u not in visitados]
            if nfce.tem_dados(pagina) or not proximos:
                break
            url = proximos[0]
            visitados.add(url)
            pagina = abrir(url)
            resumo_da_pagina(saida, url, pagina)
    except Exception as e:  # noqa: BLE001 - mostra qualquer falha de rede ou do portal
        mostrar("Falha ao abrir o portal:", e.__class__.__name__, mascarar(e))
    for alt in nfce.enderecos_alternativos(dados):
        try:
            resumo_da_pagina(saida, alt, abrir(alt))
        except Exception as e:  # noqa: BLE001
            mostrar("Falha ao abrir", mascarar(alt.split("?")[0]), e.__class__.__name__, mascarar(e))
    mostrar("\n=== Resultado da leitura")
    try:
        n = nfce.consultar(texto, abrir)
        mostrar("Loja:", "encontrada" if n.get("emitente") else "não encontrada", "| itens:", len(n.get("itens") or []),
                "| total:", "encontrado" if n.get("total") else "não encontrado", "| aviso:", n.get("aviso") or "—")
    except nfce.ErroNota as e:
        mostrar("Erro:", e)
    return "\n".join(saida)
