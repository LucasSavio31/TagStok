"""Codificação EPC (padrão GS1 EPC Tag Data Standard) para etiquetas UHF Gen2.

SGTIN-96 (produto com GTIN / EAN)  — é o padrão do varejo:
    header 8 bits (0x30) | filtro 3 | partição 3 | prefixo da empresa 20..40 | referência do item 24..4 | serial 38

GID-96 (produto sem GTIN: código interno):
    header 8 bits (0x35) | gerente 28 bits | classe (id do produto) 24 bits | serial 36 bits

Cada etiqueta recebe um número de série único para o GTIN, então duas peças iguais
têm EPCs diferentes (é isso que permite contar cada peça pelo RFID).
"""
from dataclasses import dataclass

HEADER_SGTIN96 = 0x30
HEADER_GID96 = 0x35
SERIAL_MAX_SGTIN = (1 << 38) - 1
SERIAL_MAX_GID = (1 << 36) - 1

# partição -> (bits do prefixo, dígitos do prefixo, bits da referência, dígitos da referência)
PARTICOES = {
    0: (40, 12, 4, 1),
    1: (37, 11, 7, 2),
    2: (34, 10, 10, 3),
    3: (30, 9, 14, 4),
    4: (27, 8, 17, 5),
    5: (24, 7, 20, 6),
    6: (20, 6, 24, 7),
}


class ErroEpc(ValueError):
    pass


def digito_gtin(sem_digito: str) -> str:
    """Dígito verificador GS1 (módulo 10) de um GTIN sem o último dígito."""
    soma = 0
    for i, c in enumerate(reversed(sem_digito)):
        soma += int(c) * (3 if i % 2 == 0 else 1)
    return str((10 - soma % 10) % 10)


def gtin_valido(gtin: str) -> bool:
    g = (gtin or "").strip()
    return g.isdigit() and len(g) in (8, 12, 13, 14) and digito_gtin(g[:-1]) == g[-1]


def gtin14(gtin: str) -> str:
    g = (gtin or "").strip()
    if not gtin_valido(g):
        raise ErroEpc(f"GTIN/EAN inválido: {gtin!r} (confira o dígito verificador)")
    return g.zfill(14)


def sgtin96(gtin: str, serial: int, prefixo_digitos: int = 7, filtro: int = 1) -> str:
    """Gera o EPC SGTIN-96 (24 caracteres hexadecimais).

    prefixo_digitos: tamanho do prefixo da empresa na GS1 (6 a 12; no Brasil costuma ser 7 a 9,
    ex.: 789 + código da empresa). filtro 1 = item de venda (ponto de venda).
    """
    g = gtin14(gtin)
    if not 6 <= prefixo_digitos <= 12:
        raise ErroEpc("O prefixo da empresa tem de 6 a 12 dígitos")
    if not 0 <= serial <= SERIAL_MAX_SGTIN:
        raise ErroEpc("Número de série fora do limite do SGTIN-96")
    if not 0 <= filtro <= 7:
        raise ErroEpc("Filtro vai de 0 a 7")
    particao = 12 - prefixo_digitos
    bits_cp, dig_cp, bits_ir, dig_ir = PARTICOES[particao]
    empresa = int(g[1:1 + dig_cp])
    item = int(g[0] + g[1 + dig_cp:13])          # indicador + referência do item
    valor = HEADER_SGTIN96
    valor = (valor << 3) | filtro
    valor = (valor << 3) | particao
    valor = (valor << bits_cp) | empresa
    valor = (valor << bits_ir) | item
    valor = (valor << 38) | serial
    return f"{valor:024X}"


def gid96(gerente: int, classe: int, serial: int) -> str:
    if not 0 <= gerente < (1 << 28):
        raise ErroEpc("Código do gerente GID fora do limite")
    if not 0 <= classe < (1 << 24):
        raise ErroEpc("Classe GID fora do limite")
    if not 0 <= serial <= SERIAL_MAX_GID:
        raise ErroEpc("Número de série fora do limite do GID-96")
    valor = (((HEADER_GID96 << 28 | gerente) << 24 | classe) << 36) | serial
    return f"{valor:024X}"


@dataclass
class EpcDecodificado:
    esquema: str                 # SGTIN-96 | GID-96 | OUTRO
    epc: str
    gtin: str | None = None
    serial: int | None = None
    filtro: int | None = None
    prefixo: str | None = None
    gerente: int | None = None
    classe: int | None = None
    uri: str | None = None

    def dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def normalizar(epc: str) -> str:
    return (epc or "").strip().upper().replace(" ", "")


def eh_epc(texto: str) -> bool:
    t = normalizar(texto)
    return len(t) >= 8 and len(t) % 4 == 0 and all(c in "0123456789ABCDEF" for c in t)


def decodificar(epc: str) -> EpcDecodificado:
    """Lê o que está dentro do EPC (GTIN e série para SGTIN-96; gerente/classe para GID-96)."""
    h = normalizar(epc)
    if len(h) != 24 or not eh_epc(h):
        return EpcDecodificado("OUTRO", h)
    valor = int(h, 16)
    header = valor >> 88
    if header == HEADER_SGTIN96:
        filtro = (valor >> 85) & 0x7
        particao = (valor >> 82) & 0x7
        if particao not in PARTICOES:
            return EpcDecodificado("OUTRO", h)
        bits_cp, dig_cp, bits_ir, dig_ir = PARTICOES[particao]
        empresa = (valor >> (38 + bits_ir)) & ((1 << bits_cp) - 1)
        item = (valor >> 38) & ((1 << bits_ir) - 1)
        serial = valor & SERIAL_MAX_SGTIN
        cp = str(empresa).zfill(dig_cp)
        ir = str(item).zfill(dig_ir)
        if len(cp) != dig_cp or len(ir) != dig_ir:
            return EpcDecodificado("OUTRO", h)
        sem_dv = ir[0] + cp + ir[1:]
        gtin = sem_dv + digito_gtin(sem_dv)
        return EpcDecodificado("SGTIN-96", h, gtin=gtin, serial=serial, filtro=filtro, prefixo=cp,
                               uri=f"urn:epc:tag:sgtin-96:{filtro}.{cp}.{ir}.{serial}")
    if header == HEADER_GID96:
        gerente = (valor >> 60) & ((1 << 28) - 1)
        classe = (valor >> 36) & ((1 << 24) - 1)
        serial = valor & SERIAL_MAX_GID
        return EpcDecodificado("GID-96", h, gerente=gerente, classe=classe, serial=serial,
                               uri=f"urn:epc:tag:gid-96:{gerente}.{classe}.{serial}")
    return EpcDecodificado("OUTRO", h)
