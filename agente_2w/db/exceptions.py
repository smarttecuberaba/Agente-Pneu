"""Excecoes tipadas para a camada de banco de dados."""


class RepositoryError(Exception):
    """Erro generico de operacao no repositorio."""

    def __init__(self, operacao: str, tabela: str, detalhe: str = ""):
        self.operacao = operacao
        self.tabela = tabela
        self.detalhe = detalhe
        msg = f"[{tabela}] {operacao} falhou"
        if detalhe:
            msg += f": {detalhe}"
        super().__init__(msg)


class RegistroNaoEncontrado(RepositoryError):
    """Registro esperado nao foi encontrado."""

    def __init__(self, tabela: str, identificador: str = ""):
        super().__init__("busca", tabela, f"registro nao encontrado ({identificador})")


class ErroDeInsercao(RepositoryError):
    """Falha ao inserir registro."""

    def __init__(self, tabela: str, detalhe: str = ""):
        super().__init__("insercao", tabela, detalhe)


class ErroDeAtualizacao(RepositoryError):
    """Falha ao atualizar registro."""

    def __init__(self, tabela: str, detalhe: str = ""):
        super().__init__("atualizacao", tabela, detalhe)
