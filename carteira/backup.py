"""Cópia de segurança do banco SQLite.

Uma cópia por dia (carteira-AAAA-MM-DD.db) na pasta configurada em CARTEIRA_BACKUP_DIR
(padrão: pasta "backups" ao lado do banco). Aponte para uma pasta sincronizada (OneDrive,
Google Drive, Dropbox) para ter uma cópia fora do computador. As mais antigas que
CARTEIRA_BACKUP_DIAS (padrão 30) são apagadas.

A cópia usa a API de backup do SQLite: é consistente mesmo com o sistema em uso.
"""
import datetime as dt
import glob
import os
import sqlite3
import threading
import time

PREFIXO = "carteira-"


def pasta_padrao(db_path):
    return os.environ.get("CARTEIRA_BACKUP_DIR") or os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")


def fazer_backup(db_path, pasta=None, manter=None, nome=None):
    pasta = pasta or pasta_padrao(db_path)
    manter = manter or int(os.environ.get("CARTEIRA_BACKUP_DIAS") or 30)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, nome or f"{PREFIXO}{dt.date.today().isoformat()}.db")
    temporario = destino + ".tmp"
    origem = sqlite3.connect(db_path)
    try:
        copia = sqlite3.connect(temporario)
        with copia:
            origem.backup(copia)
        copia.close()
    finally:
        origem.close()
    os.replace(temporario, destino)
    for antigo in listar(pasta)[manter:]:
        os.remove(antigo["caminho"])
    return destino


def listar(pasta):
    arquivos = sorted(glob.glob(os.path.join(pasta, f"{PREFIXO}*.db")), reverse=True)
    return [{"nome": os.path.basename(a), "caminho": a, "tamanho": os.path.getsize(a),
             "modificado": dt.datetime.fromtimestamp(os.path.getmtime(a)).isoformat(timespec="minutes")}
            for a in arquivos]


def iniciar_automatico(db_path, intervalo=3600):
    """Thread que garante uma cópia por dia enquanto o servidor estiver no ar."""
    def laco():
        while True:
            try:
                hoje = os.path.join(pasta_padrao(db_path), f"{PREFIXO}{dt.date.today().isoformat()}.db")
                if not os.path.exists(hoje):
                    fazer_backup(db_path)
            except Exception as e:  # nunca derruba o servidor por causa da cópia
                print(f"[backup] falhou: {e}")
            time.sleep(intervalo)

    t = threading.Thread(target=laco, name="backup-diario", daemon=True)
    t.start()
    return t
