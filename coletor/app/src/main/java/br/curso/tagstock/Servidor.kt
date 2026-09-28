package br.curso.tagstock

/**
 * Endereço do servidor TagStock no PC (salvo nas preferências pela MainActivity).
 * O app não tem regra nem banco: as telas vêm do servidor (/m) e toda regra fica lá.
 */
object Servidor {
    const val PORTA = 8100
    var url = "http://192.168.0.10:$PORTA"
}
