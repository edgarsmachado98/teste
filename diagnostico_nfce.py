"""Mostra como o portal da Sefaz entrega a página de uma nota fiscal (NFC-e), para ajustar o leitor.

Uso (no computador onde o sistema roda):
    python diagnostico_nfce.py "LINK_DO_QR_CODE"

O link é o texto do QR Code do cupom (abra o QR Code com a câmera do celular e copie o endereço).
Os números da página saem mascarados (cada dígito vira 9) e nenhum dado é enviado para lugar nenhum:
o resultado é salvo em diagnostico_nfce.txt, na pasta do sistema. Confira e envie esse arquivo.
"""
import html
import re
import sys
from collections import Counter

from carteira import nfce

SAIDA = []


def mostrar(*partes):
    texto = " ".join(str(p) for p in partes)
    print(texto)
    SAIDA.append(texto)


def mascarar(texto):
    return re.sub(r"\d", "9", str(texto))


def resumo_da_pagina(url, pagina):
    mostrar(f"\n=== Página: {mascarar(url.split('?')[0])}  ({len(pagina)} caracteres)")
    titulo = re.search(r"(?is)<title[^>]*>(.*?)</title>", pagina)
    mostrar("Título:", mascarar(titulo.group(1).strip()) if titulo else "—")
    mostrar("Tem os dados no formato conhecido:", "sim" if nfce.tem_dados(pagina) else "não")
    for palavra in ("captcha", "recaptcha", "hcaptcha", "turnstile", "robô", "robo"):
        if palavra in pagina.lower():
            mostrar("Aviso: a página menciona", palavra)
    for destino in nfce.proximos_enderecos(url, pagina):
        mostrar("Leva para:", mascarar(destino.split("?")[0]), "(com parâmetros)" if "?" in destino else "")
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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    texto = sys.argv[1].strip()
    try:
        dados = nfce.ler_qrcode(texto)
    except nfce.ErroNota as e:
        mostrar("QR Code não reconhecido:", e)
        return 1
    mostrar("Estado da nota:", dados["uf"], "| modelo", dados["modelo"], "| versão do QR", dados.get("versao"))
    url = dados.get("url")
    if not url:
        mostrar("Só a chave foi informada: use o link completo do QR Code.")
        return 1
    try:
        pagina = nfce._abrir(url)
        resumo_da_pagina(url, pagina)
        visitados = {url}
        for _ in range(3):
            proximos = [u for u in nfce.proximos_enderecos(url, pagina) if u not in visitados]
            if nfce.tem_dados(pagina) or not proximos:
                break
            url = proximos[0]
            visitados.add(url)
            pagina = nfce._abrir(url)
            resumo_da_pagina(url, pagina)
    except Exception as e:  # noqa: BLE001 - mostra qualquer falha de rede ou do portal
        mostrar("Falha ao abrir o portal:", e.__class__.__name__, mascarar(e))
    mostrar("\n=== Resultado da leitura")
    try:
        n = nfce.consultar(texto)
        mostrar("Loja:", "encontrada" if n.get("emitente") else "não encontrada", "| itens:", len(n.get("itens") or []),
                "| total:", "encontrado" if n.get("total") else "não encontrado", "| aviso:", n.get("aviso") or "—")
    except nfce.ErroNota as e:
        mostrar("Erro:", e)
    return 0


if __name__ == "__main__":
    codigo = main()
    with open("diagnostico_nfce.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(SAIDA) + "\n")
    print("\nResultado salvo em diagnostico_nfce.txt")
    sys.exit(codigo)
