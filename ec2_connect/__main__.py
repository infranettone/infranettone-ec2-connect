import argparse
import os
import sys

from . import inventory, session
from .config import Config
from .version import version


def _find(target: str, refresh: bool) -> inventory.Instance:
    """Por id exacto, o por nombre (sin distinguir mayúsculas) si solo hay una que case."""
    pool = inventory.cached()
    if refresh or not pool:
        pool, _ = inventory.scan(Config.load(), lambda m: print(m, file=sys.stderr))
    hits = [i for i in pool if i.id == target] or [i for i in pool if i.name.lower() == target.lower()] \
        or [i for i in pool if i.matches(target)]
    if len(hits) != 1:
        found = "\n".join(f"  {i.id}  {i.name}  ({i.profile} {i.region})" for i in hits[:20])
        raise ValueError(f"{len(hits)} instancias casan con «{target}»" + (f":\n{found}" if found else ""))
    return hits[0]


def main() -> int:
    parser = argparse.ArgumentParser(prog="infranettone-ec2-connect",
                                     description="Conecta por SSM a las instancias de todas las cuentas de AWS")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version()}")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--list", nargs="?", const="", metavar="FILTRO", help="lista las instancias (de la caché)")
    g.add_argument("--scan", action="store_true", help="recorre todas las cuentas y regiones")
    g.add_argument("--connect", metavar="INSTANCIA", help="terminal por SSM (id, nombre o texto)")
    g.add_argument("--rdp", metavar="INSTANCIA", help="Escritorio remoto por un túnel de SSM")
    parser.add_argument("--profile", help="con --rdp/--connect y un id: perfil de AWS (sin buscar)")
    parser.add_argument("--region", help="con --profile: región")
    parser.add_argument("--user", default="", help="con --rdp: usuario (DOMINIO\\usuario)")
    parser.add_argument("--refresh", action="store_true", help="vuelve a recorrer AWS antes de buscar")
    args = parser.parse_args()

    try:
        if args.list is not None or args.scan:
            pool = inventory.scan(Config.load(), lambda m: print(m, file=sys.stderr))[0] if args.scan \
                else inventory.cached()
            for i in pool:
                if not args.list or i.matches(args.list):
                    print(f"{'●' if i.online else '○'} {i.id:20} {i.name[:32]:32} {i.private_ip:15} "
                          f"{i.platform[:8]:8} {i.profile} {i.region}")
        elif args.connect or args.rdp:
            target = args.connect or args.rdp
            if args.profile and args.region:
                inst = inventory.Instance(args.profile, "", args.region, target, "", "", "Online", "")
            else:
                inst = _find(target, args.refresh)
            if args.rdp:
                return session.rdp(inst, args.user)
            cmd = session.shell_command(inst)
            os.execvp(cmd[0], cmd)
        else:
            from .ui import App
            return App().run([sys.argv[0]])
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.rdp:
            input("Pulsa Intro para cerrar…")  # en la terminal que abre la app, para que se lea el error
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
