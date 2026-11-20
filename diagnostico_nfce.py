"""Mostra como o portal da Sefaz entrega a página de uma nota fiscal (NFC-e), para ajustar o leitor.

Uso (no computador onde o sistema roda):
    python diagnostico_nfce.py "LINK_DO_QR_CODE"

O mesmo diagnóstico está no botão "Ver diagnóstico" da leitura de nota, quando ela vem sem os itens.
Os números saem mascarados (cada dígito vira 9); o resultado é salvo em diagnostico_nfce.txt.
"""
import sys

from carteira.nfce_diag import diagnosticar

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    texto = diagnosticar(sys.argv[1])
    print(texto)
    with open("diagnostico_nfce.txt", "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("\nResultado salvo em diagnostico_nfce.txt")
