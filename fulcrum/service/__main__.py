"""python -m fulcrum.service --port 8766"""

import argparse
import multiprocessing


def main():
    from ..product import PROJECT
    parser = argparse.ArgumentParser(description=f"{PROJECT['englishShortName']} local development service")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    from .app import create_app
    import uvicorn
    origins = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (args.port, 5173)]
    app = create_app(args.data_dir, allowed_origins=origins)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
