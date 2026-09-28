package br.curso.tagstock

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.MifareUltralight
import android.nfc.tech.NfcA
import android.os.Bundle
import android.util.Log
import org.json.JSONObject

/**
 * Etiquetas NFC (13,56 MHz): NTAG213/215/216 e outras, lidas pela antena NFC do Android.
 * (O leitor RFID do gatilho é UHF, 860–960 MHz, e não enxerga NFC.)
 *
 * Com o app na frente, o NFC fica ligado o tempo todo: basta encostar a etiqueta no coletor
 * (1 a 4 cm, uma por vez). Cada etiqueta vira um identificador no formato de um EPC de 24
 * hexadecimais, para as telas e o servidor tratarem igual a uma etiqueta RFID:
 *
 *     4E4643 ("NFC" em ASCII) + UID completado com 0 à esquerda
 *     ex.: UID 04A1B2C3D4E5F6  ->  4E4643000004A1B2C3D4E5F6
 */
object Nfc {
    const val PREFIXO = "4E4643"
    private const val TAG = "TagStock"

    /** Identificador da etiqueta NFC (sempre múltiplo de 4 hexadecimais, como um EPC). */
    fun identificador(uid: ByteArray): String {
        val hex = uid.joinToString("") { "%02X".format(it) }
        var tamanho = 18                                   // 6 do prefixo + 18 = 24 (96 bits)
        while (tamanho < hex.length) tamanho += 4
        return PREFIXO + hex.padStart(tamanho, '0')
    }

    /** Modelo do chip: NTAG213/215/216 pelo GET_VERSION (NXP); senão, pelo tipo do Android. */
    fun modelo(tag: Tag): String {
        try {
            NfcA.get(tag)?.use { a ->
                a.connect()
                val v = a.transceive(byteArrayOf(0x60))       // GET_VERSION
                if (v.size >= 8 && v[1].toInt() == 0x04) {   // fabricante NXP
                    val nome = when (v[6].toInt() and 0xFF) {
                        0x0F -> "NTAG213 (144 bytes)"
                        0x11 -> "NTAG215 (504 bytes)"
                        0x13 -> "NTAG216 (888 bytes)"
                        0x0B -> "MIFARE Ultralight EV1 (48 bytes)"
                        0x0E -> "MIFARE Ultralight EV1 (128 bytes)"
                        else -> null
                    }
                    if (nome != null) return nome
                }
            }
        } catch (e: Throwable) {
            Log.i(TAG, "NFC: sem GET_VERSION (${e.message})")
        }
        try {
            MifareUltralight.get(tag)?.use { u ->
                u.connect()
                return if (u.type == MifareUltralight.TYPE_ULTRALIGHT_C) "MIFARE Ultralight C" else "NFC Tipo 2 (Ultralight/NTAG)"
            }
        } catch (e: Throwable) {
        }
        return tag.techList.joinToString(", ") { it.substringAfterLast('.') }
    }

    /**
     * Liga a leitura NFC enquanto a tela está na frente. aoLer(identificador, detalhes em JSON).
     * Devolve a situação para mostrar na tela ("" = NFC ligado).
     */
    fun ligar(tela: Activity, aoLer: (String, String) -> Unit): String {
        val nfc = NfcAdapter.getDefaultAdapter(tela) ?: return "Este coletor não tem NFC"
        if (!nfc.isEnabled) return "NFC desligado nas configurações do Android"
        val opcoes = Bundle().apply { putInt(NfcAdapter.EXTRA_READER_PRESENCE_CHECK_DELAY, 250) }
        nfc.enableReaderMode(tela, { tag ->
            try {
                val id = identificador(tag.id)
                val uid = tag.id.joinToString("") { "%02X".format(it) }
                val json = JSONObject().put("id", id).put("uid", uid).put("modelo", modelo(tag))
                    .put("tecnologias", tag.techList.joinToString(", ") { it.substringAfterLast('.') })
                Log.i(TAG, "NFC: $json")
                aoLer(id, json.toString())
            } catch (e: Throwable) {
                Log.w(TAG, "NFC: erro na leitura (${e.message})")
            }
        }, NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or NfcAdapter.FLAG_READER_NFC_F or
            NfcAdapter.FLAG_READER_NFC_V or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK or NfcAdapter.FLAG_READER_NO_PLATFORM_SOUNDS,
            opcoes)
        return ""
    }

    fun desligar(tela: Activity) {
        try {
            NfcAdapter.getDefaultAdapter(tela)?.disableReaderMode(tela)
        } catch (e: Throwable) {
        }
    }
}
