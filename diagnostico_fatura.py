"""Mostra como o sistema lê uma fatura de cartão (para ajustar o leitor ao layout de cada banco).

Uso:
    python diagnostico_fatura.py "C:\\caminho\\fatura.pdf"
    python diagnostico_fatura.py "C:\\caminho\\fatura.pdf" --senha 12345

Os números são mascarados (cada dígito vira 9). Antes de enviar, apague a linha com o seu nome,
para você poder enviar o resultado sem expor valores. Copie tudo o que aparecer e envie.
"""
import re
import sys

from carteira import fatura
from carteira.importacao import ErroImportacao


def mascarar(texto):
    return re.sub(r"\d", "9", str(texto))


def main():
    args = sys.argv[1:]
    senha = None
    if "--senha" in args:
        i = args.index("--senha")
        senha = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        return 1
    caminho = args[0]
    conteudo = open(caminho, "rb").read()
    print(f"Arquivo: {caminho.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1]} ({len(conteudo)} bytes)")
    if caminho.lower().endswith(".pdf"):
        try:
            paginas = fatura._texto_pdf(conteudo, senha)
        except ErroImportacao as e:
            print("Erro ao abrir:", e)
            return 1
        for n, texto in enumerate(paginas, start=1):
            linhas = texto.splitlines()
            print(f"\n=== Página {n}: {len(linhas)} linha(s) ===")
            for k, l in enumerate(linhas[:80], start=1):
                marca = "✓" if fatura.RE_LINHA_PDF.match(l.strip()) else " "
                print(f"{k:>3} {marca} | {mascarar(l)}")
            if len(linhas) > 80:
                print(f"... mais {len(linhas) - 80} linha(s)")
        print("\n(✓ = linha reconhecida como lançamento)")
    print("\n=== Resultado da leitura ===")
    try:
        itens = fatura.ler_fatura(conteudo, caminho, senha)
    except ErroImportacao as e:
        print("Não reconhecido:", mascarar(e))
        return 0
    for i in itens:
        parc = f" · parcela {i['parcela_num']}/{i['parcela_total']}" if i["parcela_total"] else ""
        print(f"  {mascarar(i['data'])} · {i['tipo']:9} · {mascarar(i['valor'])} · {mascarar(i['descricao'][:50])}{parc}")
    print(f"{len(itens)} lançamento(s) lidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
