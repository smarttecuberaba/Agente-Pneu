"""Extracao de pneu_ids dos resultados JSON retornados pelas tools.

As tools de busca retornam estruturas diferentes (lista plana, dict com
sublistas "pneus"/"compatibilidades", sub-dict "pneu"). Este modulo
normaliza tudo em uma lista de {pneu_id, posicao, preco_venda} usada pelo
auto-enriquecimento de itens no orquestrador.
"""
import json


def extrair_pneus_de_resultado(resultado_json: str) -> list[dict]:
    """Extrai pneu_ids dos resultados de tools de busca.

    Suporta todas as estruturas de retorno das tools:
    - buscar_pneus: {"pneus": [{"pneu_id": ...}]}
    - buscar_pneus_por_moto: {"compatibilidades": [{"pneu_id": ...}]}
    - consultar_estoque: {"pneu": {"id": ...}, "preco_venda": ...}
    - buscar_detalhes_pneu: {"pneu": {"id": ...}}

    Retorna lista de dicts com pneu_id, posicao e preco_venda quando disponiveis.
    """
    try:
        data = json.loads(resultado_json)
    except (json.JSONDecodeError, TypeError):
        return []

    pneus: list[dict] = []
    vistos: set = set()

    def _adicionar(pid: str, posicao=None, preco=None, foto_url=None) -> None:
        if pid and pid not in vistos:
            vistos.add(pid)
            pneus.append({
                "pneu_id": pid,
                "posicao": posicao,
                "preco_venda": preco,
                "foto_url": foto_url,
            })

    def _extrair_item(item: dict, preco_contexto=None) -> None:
        pid = item.get("pneu_id")
        if pid:
            _adicionar(
                str(pid),
                posicao=item.get("posicao") or item.get("pneu_tipo"),
                preco=item.get("preco_venda") or preco_contexto,
                foto_url=item.get("foto_url"),
            )

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _extrair_item(item)
    elif isinstance(data, dict):
        # Sub-listas: "pneus" (buscar_pneus) e "compatibilidades" (buscar_pneus_por_moto)
        for key in ("pneus", "compatibilidades"):
            sub = data.get(key)
            if isinstance(sub, list):
                for item in sub:
                    if isinstance(item, dict):
                        _extrair_item(item)

        # Nivel raiz: pneu_id direto
        _extrair_item(data)

        # Sub-dict "pneu" (consultar_estoque, buscar_detalhes_pneu):
        # essas tools retornam pneu["id"] em vez de pneu_id no topo
        # preco_venda pode estar no root (consultar_estoque) ou dentro
        # de "estoque" (buscar_detalhes_pneu)
        pneu_sub = data.get("pneu")
        if isinstance(pneu_sub, dict):
            pid = pneu_sub.get("id")
            if pid:
                preco_root = data.get("preco_venda")
                estoque_sub = data.get("estoque")
                preco_estoque = (
                    estoque_sub.get("preco_venda")
                    if isinstance(estoque_sub, dict) else None
                )
                # foto_url pode vir de: root, pneu sub-dict, ou primeira foto da lista "fotos"
                foto = data.get("foto_url") or pneu_sub.get("foto_url")
                if not foto:
                    fotos_lista = data.get("fotos")
                    if isinstance(fotos_lista, list) and fotos_lista:
                        foto = fotos_lista[0].get("url") if isinstance(fotos_lista[0], dict) else None
                _adicionar(
                    str(pid),
                    posicao=pneu_sub.get("tipo") or data.get("posicao"),
                    preco=preco_root or preco_estoque,
                    foto_url=foto,
                )

    return pneus
