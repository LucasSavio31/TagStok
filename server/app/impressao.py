"""Impressão das etiquetas RFID (como o iPRINT): ZPL para impressoras Zebra RFID
(ZD621R, ZT411 RFID, ZT231R...). A impressora imprime o texto/código de barras e
grava o EPC no chip na mesma passada (comando ^RFW). Se a gravação falhar, a própria
impressora marca a etiqueta como VOID e tenta a próxima.

Envio:
  - REDE: direto na porta 9100 da impressora (TCP "raw").
  - WINDOWS: pela fila de impressão do Windows em modo RAW (impressora USB instalada com o driver ZDesigner).
"""
import socket
import subprocess
import sys

# Etiqueta 100 x 50 mm em 203 dpi (8 pontos por mm). Campos entre chaves são trocados por dados da peça.
MODELO_PADRAO = """^XA
^CI28
^PW800
^LL400
^RS8,,,3
^RFW,H,,,A^FD{EPC}^FS
^FO30,25^A0N,34,34^FB740,1,0,L^FD{DESCRICAO}^FS
^FO30,70^A0N,28,28^FDRef: {SKU}^FS
^FO30,105^A0N,28,28^FDCor: {COR}   Tam: {TAMANHO}^FS
^FO520,70^A0N,48,48^FD{PRECO}^FS
^FO30,150^BY2^BCN,80,Y,N,N^FD{CODIGO_BARRAS}^FS
^FO30,280^A0N,22,22^FD{OF}   Serie {SERIAL}^FS
^FO30,310^A0N,20,20^FDEPC {EPC}^FS
^FO30,345^A0N,22,22^FD{EMPRESA}^FS
^PQ1
^XZ
"""

CAMPOS = ("EPC", "DESCRICAO", "SKU", "COR", "TAMANHO", "PRECO", "CODIGO_BARRAS", "GTIN", "OF", "SERIAL", "EMPRESA", "GRUPO")


def _zpl_texto(v) -> str:
    """Texto seguro para o ZPL (^ e ~ são comandos)."""
    return ("" if v is None else str(v)).replace("^", " ").replace("~", " ")


def preco_br(valor) -> str:
    if not valor:
        return ""
    return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def zpl_etiqueta(modelo: str, t: dict, empresa: str = "") -> str:
    dados = {
        "EPC": t["epc"], "DESCRICAO": t.get("descricao"), "SKU": t.get("sku"), "COR": t.get("cor") or "-",
        "TAMANHO": t.get("tamanho") or "-", "PRECO": preco_br(t.get("preco")), "GTIN": t.get("gtin") or "",
        "CODIGO_BARRAS": t.get("gtin") or t.get("sku"), "OF": t.get("ordem") or "", "SERIAL": t.get("serial") or "",
        "EMPRESA": empresa, "GRUPO": t.get("grupo") or "",
    }
    saida = modelo or MODELO_PADRAO
    for k in CAMPOS:
        saida = saida.replace("{" + k + "}", _zpl_texto(dados[k]))
    return saida


def zpl_lote(modelo: str, etiquetas: list[dict], empresa: str = "") -> str:
    return "".join(zpl_etiqueta(modelo, t, empresa) for t in etiquetas)


class ErroImpressao(Exception):
    pass


def enviar(impressora: dict, dados: str) -> None:
    bruto = dados.encode("utf-8")
    if impressora["tipo"] == "REDE":
        try:
            with socket.create_connection((impressora["endereco"], int(impressora["porta"] or 9100)), timeout=6) as s:
                s.sendall(bruto)
        except OSError as e:
            raise ErroImpressao(f"Não conectou na impressora {impressora['endereco']}:{impressora['porta']} ({e})") from e
    elif impressora["tipo"] == "WINDOWS":
        enviar_windows(impressora["endereco"], bruto)
    else:
        raise ErroImpressao("Tipo de impressora desconhecido")


def testar(impressora: dict) -> str:
    if impressora["tipo"] == "REDE":
        try:
            with socket.create_connection((impressora["endereco"], int(impressora["porta"] or 9100)), timeout=3):
                return "Impressora respondeu na rede"
        except OSError as e:
            raise ErroImpressao(f"Sem resposta de {impressora['endereco']}:{impressora['porta']} ({e})") from e
    if impressora["endereco"] not in impressoras_windows():
        raise ErroImpressao("Essa impressora não está instalada neste Windows")
    return "Impressora instalada no Windows"


def impressoras_windows() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                           capture_output=True, text=True, timeout=15, creationflags=0x08000000)
        return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        return []


def enviar_windows(nome: str, bruto: bytes) -> None:
    """Manda os bytes sem conversão (RAW) para a fila da impressora no Windows (winspool)."""
    if sys.platform != "win32":
        raise ErroImpressao("Impressão pela fila do Windows só funciona no Windows")
    import ctypes
    from ctypes import wintypes

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    ws = ctypes.WinDLL("winspool.drv", use_last_error=True)
    ws.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    ws.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
    ws.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    for f in ("StartPagePrinter", "EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
        getattr(ws, f).argtypes = [wintypes.HANDLE]
    h = wintypes.HANDLE()
    if not ws.OpenPrinterW(nome, ctypes.byref(h), None):
        raise ErroImpressao(f"Impressora '{nome}' não encontrada no Windows")
    try:
        doc = DOC_INFO_1("TagStock etiquetas RFID", None, "RAW")
        if not ws.StartDocPrinterW(h, 1, ctypes.byref(doc)):
            raise ErroImpressao("O Windows recusou o trabalho de impressão")
        try:
            ws.StartPagePrinter(h)
            escrito = wintypes.DWORD()
            buf = ctypes.create_string_buffer(bruto, len(bruto))
            if not ws.WritePrinter(h, buf, len(bruto), ctypes.byref(escrito)) or escrito.value != len(bruto):
                raise ErroImpressao("Falha ao enviar os dados para a impressora")
            ws.EndPagePrinter(h)
        finally:
            ws.EndDocPrinter(h)
    finally:
        ws.ClosePrinter(h)
