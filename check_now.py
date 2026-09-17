"""
Script CLI para disparar a verificação imediata da OLX via terminal.
Uso:
    python check_now.py
    python check_now.py --url "https://www.olx.com.br/imoveis/venda/casas/estado-sp/sao-paulo"
"""
import argparse
import asyncio
import sys

# Garante suporte a UTF-8 no terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.database import init_db
from app.services import run_sync_routine


async def main():
    parser = argparse.ArgumentParser(description="Dispara verificação e extração de anúncios da OLX imediatamente.")
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="URL customizada de busca da OLX (opcional)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("[OLX Monitor] Iniciando verificacao sob demanda...")
    print("=" * 60)

    # Inicializa o banco de dados se necessário
    await init_db()

    # Executa a rotina de sincronização
    result = await run_sync_routine(custom_url=args.url)

    print("\n" + "=" * 60)
    print(f"Resultado: {result.get('status', '').upper()}")
    print(f"Mensagem: {result.get('message')}")
    print(f"Total analisados: {result.get('found_count', 0)}")
    print(f"Novos cadastrados: {result.get('new_count', 0)}")
    print(f"Alertas enviados no Telegram: {result.get('notified_count', 0)}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperacao cancelada pelo usuario.")
        sys.exit(0)
