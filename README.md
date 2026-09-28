# TagStock RFID — controle de estoque por etiqueta RFID (no estilo iTAG)

Sistema completo e independente: **servidor no PC** (Windows), **tela no navegador** e **app do coletor**
Zebra MC3300R / MC3390R, com etiquetas **RFID UHF EPC Gen2** no padrão **GS1**.

| Parte | Arquivo | Detalhe |
|---|---|---|
| Servidor + tela do PC | `downloads/TagStock-Servidor.exe` | porta **8100**, banco em `AppData\Local\TagStock\tagstock.db` |
| App do coletor | `downloads/TagStock.apk` | pacote `br.curso.tagstock`, perfil DataWedge `TAGSTOCK` |

## Como o iTAG funciona (e o que foi reproduzido)

Pesquisa feita no site da iTAG, nos vídeos oficiais e na página do app **Itag Monitor** (Play Store):

| iTAG | TagStock |
|---|---|
| **OF** (ordem de fabricação) com a grade de produtos cor × tamanho | **OF · Emissão**: grade de produtos e quantidades |
| **iPRINT**: gera EPC Gen2 **SGTIN-96 (GS1)** serializado e imprime na impressora RFID | Um EPC SGTIN-96 por peça (série nunca repete); impressão **ZPL** em Zebra RFID (rede 9100 ou fila do Windows), arquivo `.zpl`, reimpressão. Sem impressora RFID: **Gravar OF** no coletor |
| Finalização da OF por RFID (confere quantidades e dá entrada) | **Finalizar OF**: lê as peças, mostra lidas × previstas por item, divergências; as lidas entram no estoque |
| Consolidação de kit (trocar o produto de destino dentro da OF, para a cor/tamanho inteira) | **Consolidação de kit** na OF |
| Inventário RFID e arquivo da contagem | **Inventário** total, por local ou por grupo; esperado × lido, acuracidade, faltas, sobras, peça em outro local, baixada encontrada, desconhecida (decodifica o GTIN do EPC). Finaliza com ajuste. Arquivo da contagem (CSV) no PC e na pasta **Download/TagStock** do coletor |
| Conferência de embarque / separação | **Expedição**: pedido de venda (baixa) ou transferência; cada peça validada (local, produto, quantidade) |
| ALERTi / antifurto | **Antifurto**: peça ainda no estoque passando na saída = sirene + alerta; "Conferido" tira da lista |
| iTAG Monitor (hardware) | **Monitor**: coletores (online, bateria, RFID, tela) e teste das impressoras |
| iTAG Análise (gráficos) | **Análise**: estoque por local/grupo, entradas × baixas 14 dias, abaixo do mínimo, acuracidade |
| Localizador | **Localizar** (quente/frio, bipe e LED) |
| Login | Usuários com senha, perfis ADMIN/OPERADOR, token na API |
| Integração ERP | API REST (`/docs`) com o mesmo login (cabeçalho `X-Token`), importação/exportação CSV |

Além disso: **Vincular** (etiqueta com EPC qualquer vira uma peça), **Entrada**, **Baixa** com motivo e estorno,
**Transferência**, **Rastreio** de cada etiqueta (histórico completo), **Alertas**, **Estação RFID** (o PC usa o
coletor como leitor/gravador pela rede, ou um leitor USB que "digita" o EPC).

## Etiquetas NFC (NTAG213/215/216)

Além das etiquetas RFID UHF (lidas pelo gatilho, a metros), o app lê **etiquetas NFC** pela antena NFC do
Android: basta **encostar** a etiqueta no coletor (1 a 4 cm, uma por vez), em qualquer tela. O UID da NTAG vira o
identificador da peça, no formato de um EPC: `4E4643` ("NFC") + UID — ex.: UID `04A1B2C3D4E5F6` →
`4E4643000004A1B2C3D4E5F6`. Assim a NTAG funciona em tudo (vincular, entrada, baixa, expedição, inventário,
consulta). As telas mostram **NFC** e o UID; *Ler etiqueta* mostra o chip (NTAG213/215/216). NFC não é gravada nem
localizada (quente/frio): isso é só para RFID.

## Ciclo da etiqueta

```
 OF / Vincular ─► EMITIDA ─(finalizar OF / entrada)─► ESTOQUE ─(baixa / expedição)─► BAIXADA
                     │                                   │   ▲                          │
                     └─────────(cancelar)─► CANCELADA ◄──┘   └──────(estorno)───────────┘
```

Cada mudança gera um movimento (data/hora do servidor, usuário, coletor, documento).

## EPC (padrão GS1)

- Produto **com GTIN/EAN**: **SGTIN-96** = header 30 · filtro · partição · prefixo da empresa · referência · série (38 bits).
  Em *Configurações*: quantos dígitos tem o prefixo GS1 da empresa (6 a 12) e o filtro (1 = item de venda).
- Produto **sem GTIN**: **GID-96** (gerente · id do produto · série).
- Conferido com o vetor oficial da GS1: `3074257BF7194E4000001A85` = `urn:epc:tag:sgtin-96:3.0614141.812345.6789`.
- *Configurações → Calculadora EPC* gera e decodifica.

## Impressão (Zebra RFID)

Layout em ZPL editável em *Configurações* (padrão 100 × 50 mm, 203 dpi). A linha `^RFW,H,,,A^FD{EPC}^FS` grava o
chip; a impressora marca VOID e repete se a gravação falhar (`^RS8,,,3`). Campos: `{EPC} {DESCRICAO} {SKU} {COR}
{TAMANHO} {PRECO} {CODIGO_BARRAS} {GTIN} {OF} {SERIAL} {EMPRESA} {GRUPO}`. *Impressoras → Etiqueta de teste* imprime o
layout sem gravar RFID.

## Usar

1. PC: rode `downloads/TagStock-Servidor.exe` (libere no Firewall). Abre `http://localhost:8100`. Login **admin / admin**.
2. Coletor: instale `downloads/TagStock.apk`. O app acha o servidor na rede sozinho. Login com o mesmo usuário.
3. Config do coletor: ⚙ + PIN **1234** (volume, potência por operação, servidor, trocar usuário).
4. RFID não lê com o coletor no cabo USB (carregando). Para instalar sem cabo: `adb tcpip 5555` e `adb connect IP:5555`.

Liberar no AppCenter sem abrir a área do admin (o AppCenter é debug, então aceita `run-as`):
```
adb shell run-as br.curso.appcenter cat shared_prefs/appcenter.xml      (ver a lista)
```
ou, no coletor: 5 toques + PIN 1234 → marcar **TagStock**.

## Desenvolvimento

```
cd server
pip install -r requirements-dev.txt
pytest                      (14 testes: EPC, OF, kit, gravação, vincular/baixa/estorno, inventário, expedição, antifurto...)
python tagstock_servidor.py
```
APK: `cd coletor && gradlew assembleDebug` (JDK 17, Android SDK 34, `app/libs/API3_LIB-release.aar` do Zebra RFID SDK).
O `.github/workflows/build.yml` gera o `.exe` e o `.apk` sozinho no GitHub.

| Arquivo | O que tem |
|---|---|
| `server/app/epc.py` | SGTIN-96 / GID-96: gerar e decodificar, dígito GTIN |
| `server/app/regras.py` | Todas as regras (OF, emissão, vincular, entrada, baixa, transferência, inventário, expedição, antifurto) |
| `server/app/impressao.py` | ZPL, envio para impressora de rede (9100) e do Windows (RAW) |
| `server/app/main.py` | API e login |
| `server/app/static/index.html`, `pc-*.js` | Tela do PC |
| `server/app/static/m.html` | Tela do coletor (também vai dentro do APK para o modo sem servidor) |
| `coletor/app/.../Rfid.kt` | Leitor RFID Zebra (SDK API3): conectar, gatilho, potência, leitura, gravação, localizar |
| `coletor/app/.../MainActivity.kt` | WebView, ponte `ColetorApp`, DataWedge `TAGSTOCK`, bipe nativo, arquivo da contagem, botão de desligar |
