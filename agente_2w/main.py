"""Ponto de entrada CLI para testes manuais do agente 2W Pneus."""

import argparse
import logging
import sys
from uuid import UUID

from agente_2w.config import SUPABASE_URL, OPENAI_MODEL
from agente_2w.db import sessao_repo
from agente_2w.enums.enums import EtapaFluxo, StatusSessao
from agente_2w.schemas.sessao_chat import SessaoChatCreate
from agente_2w.engine.orquestrador import processar_turno


def main():
    parser = argparse.ArgumentParser(description="Agente 2W Pneus — CLI")
    parser.add_argument("--sessao", type=str, help="UUID de sessao existente para retomar")
    parser.add_argument("--contato", type=str, default="5521999999999", help="Contato externo (telefone)")
    parser.add_argument("--debug", action="store_true", help="Ativar logs de debug")
    args = parser.parse_args()

    # Configurar logging
    nivel = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("  Agente 2W Pneus — Modo CLI")
    print("=" * 50)
    print(f"  Supabase: {SUPABASE_URL[:40]}...")
    print(f"  Modelo:   {OPENAI_MODEL}")
    print()

    # Criar ou retomar sessao
    if args.sessao:
        sessao_id = UUID(args.sessao)
        sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
        if sessao is None:
            print(f"  [ERRO] Sessao {sessao_id} nao encontrada.")
            sys.exit(1)
        print(f"  Sessao:   {sessao.id}")
        print(f"  Etapa:    {sessao.etapa_atual.value}")
        print(f"  Status:   {sessao.status_sessao.value}")
        print(f"  Contato:  {sessao.contato_externo}")
    else:
        sessao = sessao_repo.criar_sessao(SessaoChatCreate(
            canal="cli",
            contato_externo=args.contato,
            etapa_atual=EtapaFluxo.identificacao,
            status_sessao=StatusSessao.ativa,
        ))
        sessao_id = sessao.id
        print(f"  Nova sessao: {sessao_id}")
        print(f"  Contato:     {args.contato}")

    print()
    print("  Digite 'sair' para encerrar.")
    print("  Digite 'status' para ver o estado da sessao.")
    print("=" * 50)
    print()

    # Loop de conversa
    while True:
        try:
            mensagem = input("Voce: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nEncerrando.")
            break

        if not mensagem:
            continue

        if mensagem.lower() in ("sair", "exit", "quit"):
            print("\nEncerrando conversa.")
            break

        if mensagem.lower() == "status":
            sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
            if sessao:
                print(f"\n  Etapa:  {sessao.etapa_atual.value}")
                print(f"  Status: {sessao.status_sessao.value}")
                if sessao.cliente_id:
                    print(f"  Cliente: {sessao.cliente_id}")
                if sessao.codigo_motivo:
                    print(f"  Bloqueio: {sessao.codigo_motivo} — {sessao.mensagem_motivo}")
            print()
            continue

        try:
            resposta = processar_turno(sessao_id, mensagem)
            if resposta.fotos:
                print(f"\n2W Pneus: {resposta}")
                for foto in resposta.fotos:
                    print(f"  [foto: {foto}]")
                print()
            else:
                print(f"\n2W Pneus: {resposta}\n")
        except Exception as e:
            print(f"\n[ERRO] {e}\n")

    # Estado final
    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao:
        print(f"\nEstado final — Etapa: {sessao.etapa_atual.value} | Status: {sessao.status_sessao.value}")
        print(f"Sessao ID: {sessao_id}")


if __name__ == "__main__":
    main()
