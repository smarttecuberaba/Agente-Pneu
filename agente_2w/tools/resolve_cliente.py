"""Tool de resolução de cliente — chamada pela IA via function calling."""

from agente_2w.db import cliente_repo


def resolver_cliente(telefone: str, nome: str | None = None) -> dict:
    """Busca um cliente pelo telefone. Se não existir, cria um novo.

    Parâmetros:
        telefone: número de telefone do cliente (ex: "11999998888")
        nome: nome do cliente (opcional, usado apenas na criação)

    Retorna dict com dados do cliente e se foi criado agora ou já existia.
    """
    existente = cliente_repo.buscar_cliente_por_telefone(telefone)

    if existente is not None:
        return {
            "cliente": existente.model_dump(mode="json"),
            "ja_existia": True,
        }

    novo = cliente_repo.resolver_ou_criar_cliente(telefone=telefone, nome=nome)
    return {
        "cliente": novo.model_dump(mode="json"),
        "ja_existia": False,
    }
