"""Resposta de um turno do agente — carrega texto + metadados (fotos)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RespostaTurno:
    """Resposta de um turno do agente.

    Comporta-se como string para retrocompatibilidade:
    - print(resposta)        → imprime o texto
    - "pneu" in resposta     → funciona
    - f"2W: {resposta}"      → funciona
    - str(resposta)          → retorna o texto
    - resposta.fotos         → lista de URLs de fotos para enviar
    """

    texto: str
    fotos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.texto

    def __contains__(self, item: str) -> bool:
        return item in self.texto

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.texto == other
        if isinstance(other, RespostaTurno):
            return self.texto == other.texto and self.fotos == other.fotos
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.texto)

    def __repr__(self) -> str:
        fotos_info = f", fotos={len(self.fotos)}" if self.fotos else ""
        return f"RespostaTurno(texto='{self.texto[:60]}...'{fotos_info})"
