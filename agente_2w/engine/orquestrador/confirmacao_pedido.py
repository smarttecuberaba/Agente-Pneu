"""Montagem da mensagem de confirmacao de pedido e calculo de prazo.

Usa dados reais do banco (catalogo_repo, pedido_repo) para compor o texto
final enviado ao cliente apos o pedido ser promovido. Mantem o formato
'anti-alucinacao': nada vem da IA, tudo vem do backend.
"""
import logging
from datetime import timedelta

from agente_2w.db import pedido_repo, catalogo_repo
from agente_2w.enums.enums import TipoEntrega

logger = logging.getLogger(__name__)


_DIAS_PT = {
    0: "segunda-feira",
    1: "terça-feira",
    2: "quarta-feira",
    3: "quinta-feira",
    4: "sexta-feira",
    5: "sábado",
    6: "domingo",
}

_MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr",
    5: "mai", 6: "jun", 7: "jul", 8: "ago",
    9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _calcular_prazo_entrega(criado_em) -> str:
    """Calcula a data real de entrega (proximo dia util apos criado_em).

    Regras da 2W Pneus:
    - Entrega no dia seguinte ao pedido confirmado
    - Sabado: entrega normal
    - Domingo: nao entregamos — avanca para segunda-feira
    """
    # Garante timezone-aware em UTC-3 (horario de Brasilia)
    try:
        from zoneinfo import ZoneInfo
        tz_br = ZoneInfo("America/Sao_Paulo")
    except Exception:
        tz_br = None

    agora = criado_em
    if tz_br and agora.tzinfo is not None:
        agora = agora.astimezone(tz_br)

    entrega = agora.date() + timedelta(days=1)

    # Domingo (weekday=6) → segunda-feira
    if entrega.weekday() == 6:
        entrega = entrega + timedelta(days=1)

    dia_semana = _DIAS_PT[entrega.weekday()]
    mes = _MESES_PT[entrega.month]
    return f"📦 Chega na {dia_semana}, {entrega.day:02d}/{mes}"


def _montar_confirmacao_pedido(pedido) -> str:
    """Monta mensagem de confirmacao formatada com dados reais do pedido.

    Usa dados do banco — sem risco de alucinacao da IA.
    Em caso de qualquer erro, retorna mensagem minima com numero e total.
    """
    try:
        # Itens do pedido com nomes reais do catalogo
        itens = pedido_repo.listar_itens_pedido(pedido.id)
        linhas_itens = []
        for item in itens:
            pneu = catalogo_repo.buscar_pneu_por_id(item.pneu_id)
            nome = pneu.descricao_comercial if pneu else "Pneu"
            posicao = f" {item.posicao.value}" if item.posicao else ""
            linhas_itens.append(
                f"• {item.quantidade}x {nome}{posicao} — R${item.preco_unitario:.2f}"
            )
        itens_texto = "\n".join(linhas_itens) if linhas_itens else "• item confirmado"

        # Entrega ou retirada
        if pedido.tipo_entrega == TipoEntrega.entrega:
            endereco = ""
            if pedido.endereco_entrega_json:
                end = pedido.endereco_entrega_json
                if isinstance(end, dict):
                    partes = [
                        end.get("logradouro", ""),
                        end.get("numero", ""),
                        end.get("bairro", ""),
                    ]
                    endereco = ", ".join(p for p in partes if p)
                else:
                    endereco = str(end.get("endereco", end) if isinstance(end, dict) else end)
            entrega_texto = f"🚚 Entrega: {endereco}" if endereco else "🚚 Entrega a combinar"
            if pedido.valor_frete and pedido.valor_frete > 0:
                entrega_texto += f"\n   Frete: R${pedido.valor_frete:.2f}"
        else:
            entrega_texto = "🏪 Retirada na loja"

        # Forma de pagamento legivel
        _pagamento_label = {
            "pix": "PIX",
            "dinheiro": "Dinheiro",
            "cartao": "Cartao",
            "transferencia": "Transferencia",
        }
        pagamento = _pagamento_label.get(
            pedido.forma_pagamento.value, pedido.forma_pagamento.value
        )

        # Prazo com data real calculada
        if pedido.tipo_entrega == TipoEntrega.retirada:
            prazo_texto = "Nos avise quando vier buscar!"
        else:
            prazo_texto = _calcular_prazo_entrega(pedido.criado_em)

        linhas = [
            f"✅ Pedido #{pedido.numero_pedido} confirmado!",
            "",
            "📋 Resumo:",
            itens_texto,
            "",
            entrega_texto,
            "",
            f"💰 Total: R${pedido.valor_total:.2f}",
            f"💳 Pagamento: {pagamento}",
        ]
        if prazo_texto:
            # retirada nao tem emoji de caixa — entrega ja vem com 📦 da funcao
            prefixo = "" if prazo_texto.startswith("📦") else "📦 "
            linhas.extend(["", f"{prefixo}{prazo_texto}"])

        return "\n".join(linhas)

    except Exception:
        logger.exception("Falha ao montar confirmacao do pedido #%s", pedido.numero_pedido)
        return (
            f"✅ Pedido #{pedido.numero_pedido} confirmado!\n"
            f"💰 Total: R${pedido.valor_total:.2f}"
        )
