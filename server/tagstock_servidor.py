"""Inicia o servidor TagStock e abre a tela no navegador (vira o TagStock-Servidor.exe).

Porta 8100 (outra porta: set TAGSTOCK_PORTA=8200 antes de abrir).
"""
import os
import socket
import sys
import threading
import webbrowser

import uvicorn

from app import db
from app.main import app

PORTA = int(os.environ.get("TAGSTOCK_PORTA", "8100"))


def porta_livre(porta: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", porta))
        return True
    except OSError:
        return False
    finally:
        s.close()


def sair(mensagem: str) -> None:
    print()
    print(mensagem)
    input("Pressione ENTER para fechar...")
    sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    ip = db.ip_da_rede()
    print("=" * 64)
    print(" TAGSTOCK RFID - SERVIDOR")
    print(f" Tela do PC ...........: http://localhost:{PORTA}")
    print(f" Endereço no coletor ..: http://{ip}:{PORTA}")
    try:
        db.inicializar()
    except Exception as e:  # noqa: BLE001
        sair(f"Não foi possível abrir o banco de dados: {e}")
    print(f" Banco de dados .......: {db.DB_PATH}")
    print(" Primeiro acesso ......: usuário admin, senha admin")
    print(" (o app TagStock do coletor acha o servidor sozinho)")
    print(" Para desligar, feche esta janela.")
    print("=" * 64)
    if not porta_livre(PORTA):
        sair(f"A porta {PORTA} já está em uso: o TagStock já está aberto em outra janela?")
    if not os.environ.get("TAGSTOCK_SEM_NAVEGADOR"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORTA}")).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=PORTA, log_level="warning")
    except Exception as e:  # noqa: BLE001
        sair(f"O servidor parou com erro: {e}")
