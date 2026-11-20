"""Envio de alertas por Telegram (opcional).

Configuração no .env:
    TELEGRAM_BOT_TOKEN   token do bot (crie com o @BotFather no Telegram)
    TELEGRAM_CHAT_ID     id da conversa ou grupo da família que recebe os alertas
Com o servidor no ar, os alertas de cada carteira são verificados a cada hora e só os novos são
enviados (cada alerta uma única vez).
"""
import datetime as dt
import html
import os
import threading
import time

import requests


def configurado():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def enviar_telegram(texto):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no arquivo .env.")
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=15,
                         json={"chat_id": chat, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True})
    resp.raise_for_status()


def formatar(carteira, alerta):
    icone = "⚠️" if alerta["nivel"] == "alerta" else "ℹ️"
    return (f"{icone} <b>{html.escape(alerta['titulo'])}</b>\n{html.escape(alerta['texto'])}\n"
            f"<i>{html.escape(carteira)}</i>")


def verificar_e_enviar(app, enviar=enviar_telegram):
    """Calcula os alertas de todas as carteiras e envia os que ainda não foram enviados."""
    conn = app.config["conn"]
    calcular = app.config["calcular_alertas"]
    enviados = 0
    with app.app_context():
        for c in conn.execute("SELECT id, nome FROM carteiras ORDER BY id").fetchall():
            for alerta in calcular([c["id"]]):
                if conn.execute("SELECT 1 FROM alertas_enviados WHERE chave = ?", (alerta["chave"],)).fetchone():
                    continue
                enviar(formatar(c["nome"], alerta))
                conn.execute("INSERT INTO alertas_enviados (chave, enviado_em) VALUES (?, ?)",
                             (alerta["chave"], dt.datetime.now().isoformat(timespec="minutes")))
                conn.commit()
                enviados += 1
        conn.close()
    return enviados


def iniciar_automatico(app, intervalo=3600):
    def laco():
        time.sleep(30)  # deixa o servidor subir
        while True:
            try:
                if configurado():
                    verificar_e_enviar(app)
            except Exception as e:  # nunca derruba o servidor por causa de uma notificação
                print(f"[alertas] falhou: {e}")
            time.sleep(intervalo)

    t = threading.Thread(target=laco, name="alertas-telegram", daemon=True)
    t.start()
    return t
