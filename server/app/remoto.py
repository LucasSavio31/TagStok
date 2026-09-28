"""Estação RFID do PC: o PC usa o leitor do coletor pela rede, com o servidor no meio.

    PC --comando (ler, parar, gravar)--> servidor <--pergunta a cada 0,4 s-- coletor (tela "Estação PC")
    PC <--leituras e resultados-------- servidor <--leituras e eventos------ coletor

Fica em memória (estado de uma bancada, um coletor por vez).
"""
import threading
import time

from . import db

_trava = threading.Lock()
_comandos: list[dict] = []
_seq_comando = 0
_leituras: dict[str, dict] = {}
_versao = 0
_eventos: list[dict] = []
_seq_evento = 0
_sinal = 0.0
_lendo = False
_dispositivo = None

ONLINE_SEGUNDOS = 3


def comando(acao: str, texto: str | None = None, potencia: int | None = None) -> dict:
    global _seq_comando, _versao, _lendo
    with _trava:
        _seq_comando += 1
        c = {"id": _seq_comando, "acao": acao, "texto": texto, "potencia": potencia, "hora": db.agora()}
        _comandos.append(c)
        del _comandos[:-50]
        if acao == "limpar":
            _leituras.clear()
            _versao += 1
        elif acao == "ler":
            _lendo = True
        elif acao in ("parar", "gravar"):
            _lendo = False
        return c


def comandos_para_coletor(apos: int, dispositivo: str | None = None) -> dict:
    global _sinal, _dispositivo
    with _trava:
        _sinal = time.time()
        _dispositivo = dispositivo or _dispositivo
        novos = [] if apos < 0 else [c for c in _comandos if c["id"] > apos]
        return {"ultimo": _seq_comando, "comandos": novos}


def registrar_leituras(epcs: list[str]) -> int:
    global _sinal, _versao
    agora = db.agora()
    with _trava:
        _sinal = time.time()
        for e in (x.strip().upper() for x in epcs if x and x.strip()):
            r = _leituras.get(e)
            if r:
                r["vezes"] += 1
                r["ultima"] = agora
            else:
                _leituras[e] = {"epc": e, "vezes": 1, "primeira": agora, "ultima": agora}
        _versao += 1
        return len(_leituras)


def remover(epcs: list[str]) -> None:
    global _versao
    with _trava:
        for e in epcs:
            _leituras.pop(e.strip().upper(), None)
        _versao += 1


def registrar_evento(tipo: str, dados: dict) -> None:
    global _seq_evento, _lendo, _sinal
    with _trava:
        _sinal = time.time()
        _seq_evento += 1
        _eventos.append({"id": _seq_evento, "tipo": tipo, "dados": dados, "hora": db.agora()})
        del _eventos[:-50]
        if tipo in ("parou", "gravacao"):
            _lendo = False


def estado(eventos_apos: int = 0) -> dict:
    with _trava:
        sinal_ha = time.time() - _sinal if _sinal else None
        return {
            "online": sinal_ha is not None and sinal_ha < ONLINE_SEGUNDOS,
            "dispositivo": _dispositivo,
            "lendo": _lendo, "versao": _versao,
            "eventos": [e for e in _eventos if e["id"] > eventos_apos],
            "leituras": sorted((dict(r) for r in _leituras.values()), key=lambda r: r["primeira"], reverse=True),
        }
