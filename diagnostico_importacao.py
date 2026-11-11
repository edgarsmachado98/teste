"""Mostra como o sistema lê um extrato ou relatório (para ajustar o leitor a novos formatos).

Uso:
    python diagnostico_importacao.py "C:\\caminho\\relatorio.pdf"
    python diagnostico_importacao.py "C:\\caminho\\relatorio.pdf" --mostrar-valores

Por padrão os números são mascarados (cada dígito vira 9) e os nomes longos são encurtados, para
você poder compartilhar o resultado sem expor valores. Copie tudo o que aparecer e envie.
"""
import re
import sys

from carteira import importacao


def mascarar(celula, mostrar):
    texto = str(celula) if celula is not None else ""
    if mostrar:
        return texto
    return re.sub(r"\d", "9", texto)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mostrar = "--mostrar-valores" in sys.argv
    if not args:
        print(__doc__)
        return 1
    caminho = args[0]
    conteudo = open(caminho, "rb").read()
    print(f"Arquivo: {caminho} ({len(conteudo)} bytes)")
    try:
        abas = importacao.ler_abas(conteudo, caminho)
    except importacao.ErroImportacao as e:
        print("Erro ao ler:", e)
        return 1
    for nome, linhas in abas:
        print(f"\n=== {nome}: {len(linhas)} linha(s) ===")
        achado = importacao._cabecalho_posicao(linhas)
        if achado:
            i, idx, nomes = achado
            print(f"[cabeçalho de posição na linha {i + 1}, {len(nomes)} colunas: {idx}]")
        for n, linha in enumerate(linhas[:45], start=1):
            celulas = [mascarar(c, mostrar) for c in linha]
            print(f"{n:>3} ({len(celulas)} col.) | " + " | ".join(celulas))
        if len(linhas) > 45:
            print(f"... mais {len(linhas) - 45} linha(s)")
    if caminho.lower().endswith((".xlsx", ".xlsm")) and sum(len(l) for _, l in abas) < 5:
        # poucas linhas: mostra a estrutura interna do arquivo para ajustar o leitor
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(conteudo))
        print("\n=== Estrutura interna do Excel ===")
        for info in z.infolist():
            print(f"  {info.filename} ({info.file_size} bytes)")
        for nome in z.namelist():
            if nome.startswith("xl/worksheets/") and nome.endswith(".xml"):
                xml = z.read(nome).decode("utf-8", "ignore")
                print(f"\n--- {nome} (início) ---")
                print(mascarar(xml[:2500], mostrar))
    print("\n=== Resultado da leitura ===")
    try:
        r = importacao.analisar_extrato(conteudo, caminho)
    except importacao.ErroImportacao as e:
        print("Não reconhecido:", e)
        return 0
    print(f"Tipo: {r['tipo_arquivo']} · posição: {len(r['posicao'])} · operações: {len(r['aportes'])} · "
          f"proventos: {len(r['proventos'])} · ignoradas: {len(r['ignorados'])}")
    for p in r["posicao"]:
        print(f"  ativo: {mascarar(p['ticker'], True)} · classe {p['classe']} · qtd {mascarar(p['quantidade'], mostrar)}")
    for g in r["ignorados"][:15]:
        print(f"  ignorada (linha {g['linha']}): {g['motivo']} -> {mascarar(g['descricao'], mostrar)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
