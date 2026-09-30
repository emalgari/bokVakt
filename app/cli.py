"""Firmabok CLI.

    firma serve              # start uvicorn on 127.0.0.1:8000
    firma init               # create/migrate the database
    firma seed               # load sample/demo data
    firma backup             # timestamped backup (DB + uploads)
    firma backup-list
    firma restore <name>
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"

    if cmd == "serve":
        import socket

        import uvicorn
        from . import config
        host = config.HOST
        port = config.PORT
        if "--port" in argv:
            port = int(argv[argv.index("--port") + 1])
        if "--host" in argv:
            host = argv[argv.index("--host") + 1]

        probe = socket.socket()
        try:
            probe.bind((host, port))
        except OSError:
            print(f"Port {port} är redan upptagen (address already in use).")
            print("En tidigare serverprocess kör fortfarande. Antingen:")
            print('  1) stoppa den:   pkill -f "uvicorn app.main"   (eller: pgrep -af uvicorn)' )
            print(f"  2) välj ny port: FIRMA_PORT={port + 1} firma serve   "
                  f"(eller: uvicorn app.main:app --reload --port {port + 1})")
            return 1
        finally:
            probe.close()

        print(f"Firmabok körs på http://{host}:{port}  (Ctrl-C stoppar)")
        uvicorn.run("app.main:app", host=host, port=port, reload=False)
        return 0

    if cmd == "init":
        from .main import run_migrations, seed_reference_data
        from .db import get_session_factory
        run_migrations()
        db = get_session_factory()()
        try:
            seed_reference_data(db)
        finally:
            db.close()
        print("Databas skapad/migrerad.")
        return 0

    if cmd == "seed":
        from .seed import main as seed_main
        seed_main([])
        return 0

    if cmd == "backup":
        from .backup import create_backup
        print(f"Backup skapad: {create_backup()}")
        return 0

    if cmd == "backup-list":
        from .backup import list_backups
        for b in list_backups():
            print(f"{b['name']}  ({b['created_at']}, {b['total_bytes']/1e6:.1f} MB)")
        return 0

    if cmd == "restore":
        if len(argv) < 2:
            print("Ange backup-namn: firma restore <name>")
            return 2
        from .backup import restore_backup
        safety = restore_backup(argv[1])
        print(f"Återställd. Föregående data sparad i {safety}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
