"""Run with ``python -m api_mode``; credentials stay in the environment."""
import argparse
import os

from aiohttp import web

from .gateway import GatewayConfig, create_app


def main():
    parser = argparse.ArgumentParser(description='Hum_Project text/image API WebSocket gateway')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8006)
    parser.add_argument('--model', default=os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash'))
    parser.add_argument('--thinking', choices=['off', 'low', 'high', 'max'],
                        default=os.environ.get('DEEPSEEK_THINKING', 'low'))
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--max-turns', type=int, default=20,
                        help='human messages retained, including pending input; reaching limit requires explicit reconnect')
    parser.add_argument('--visual-interval', type=float, default=8,
                        help='seconds between automatic image observations after a user goal; 0 disables')
    args = parser.parse_args()
    if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        parser.error('set DEEPSEEK_API_KEY before starting the gateway')
    try:
        config = GatewayConfig(model=args.model, thinking=args.thinking,
                               timeout=args.timeout, max_tokens=args.max_tokens,
                               max_turns=args.max_turns, visual_interval=args.visual_interval)
    except ValueError as exc:
        parser.error(str(exc))
    web.run_app(create_app(config=config), host=args.host, port=args.port, access_log=None)


if __name__ == '__main__':
    main()
