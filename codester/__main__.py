import argparse
import os

from waitress import serve

from codester.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Codester local dashboard")
    parser.add_argument("--host", default=os.environ.get("CODESTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CODESTER_PORT", "8765")))
    args = parser.parse_args()
    print(f"Codester: http://localhost:{args.port} (Ctrl+C to stop)", flush=True)
    serve(create_app(), host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
