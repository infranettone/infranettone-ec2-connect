"""Sesiones de SSM: terminal, reenvío de puertos y Escritorio remoto por el túnel.

Todo va con `aws ssm start-session` + session-manager-plugin en una ventana de terminal. Los argumentos se pasan
como lista, nunca por un shell, y se validan antes.
"""

import re
import shutil
import socket
import subprocess
import sys
import time

from .inventory import Instance

ID_RE = re.compile(r"^(i|mi)-[0-9a-f]{8,17}$")
NAME_RE = re.compile(r"^[\w.@+=,-]+$")  # perfiles y regiones
RDP_CLIENTS = ("xfreerdp3", "xfreerdp", "sdl-freerdp3")


def _check(i: Instance) -> None:
    if not ID_RE.match(i.id) or not NAME_RE.match(i.profile) or not NAME_RE.match(i.region):
        raise ValueError(f"Datos de instancia no válidos: {i.profile} {i.region} {i.id}")


def missing_tools() -> list[str]:
    return [t for t in ("aws", "session-manager-plugin") if not shutil.which(t)]


def _terminal(cmd: list[str], title: str) -> None:
    if shutil.which("ptyxis"):
        argv = ["ptyxis", "--new-window", "--", *cmd]
    elif shutil.which("gnome-terminal"):
        argv = ["gnome-terminal", f"--title={title}", "--", *cmd]
    elif shutil.which("kgx"):
        argv = ["kgx", f"--title={title}", "--", *cmd]
    elif shutil.which("x-terminal-emulator"):
        argv = ["x-terminal-emulator", "-e", *cmd]
    else:
        raise RuntimeError("No encuentro ninguna terminal (ptyxis, gnome-terminal…)")
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def shell_command(i: Instance) -> list[str]:
    _check(i)
    return ["aws", "ssm", "start-session", "--profile", i.profile, "--region", i.region, "--target", i.id]


def forward_command(i: Instance, remote_port: int, local_port: int, host: str = "") -> list[str]:
    """Reenvío de un puerto de la instancia (o, con host, de otro equipo al que llega la instancia: RDS…)."""
    _check(i)
    if host and not re.match(r"^[\w.-]+$", host):
        raise ValueError(f"Host no válido: {host}")
    doc = "AWS-StartPortForwardingSessionToRemoteHost" if host else "AWS-StartPortForwardingSession"
    params = f"portNumber={remote_port},localPortNumber={local_port}" + (f",host={host}" if host else "")
    return [*shell_command(i), "--document-name", doc, "--parameters", params]


def login_command(profile: str) -> list[str]:
    if not NAME_RE.match(profile):
        raise ValueError(f"Perfil no válido: {profile}")
    return ["aws", "sso", "login", "--profile", profile]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_shell(i: Instance) -> None:
    _terminal(shell_command(i), f"SSM {i.name or i.id}")


def open_forward(i: Instance, remote_port: int, local_port: int, host: str = "") -> None:
    _terminal(forward_command(i, remote_port, local_port, host), f"Puerto {local_port} → {i.name or i.id}")


def open_login(profile: str) -> None:
    _terminal(login_command(profile), f"SSO {profile}")


def open_rdp(i: Instance, user: str = "") -> None:
    """En la terminal corre `--rdp`: el túnel y, cuando está listo, xfreerdp. Al cerrar la ventana se cierra todo."""
    _check(i)
    if user and not re.match(r"^[\w.@\\-]+$", user):
        raise ValueError(f"Usuario no válido: {user}")
    _terminal([sys.executable, "-m", "ec2_connect", "--rdp", i.id, "--profile", i.profile, "--region", i.region,
               *(["--user", user] if user else [])], f"Escritorio remoto {i.name or i.id}")


def rdp(i: Instance, user: str = "") -> int:
    """Túnel al 3389 y xfreerdp contra localhost; se ejecuta dentro de la terminal (o desde la línea de órdenes)."""
    client = next((c for c in RDP_CLIENTS if shutil.which(c)), None)
    if not client:
        raise RuntimeError("Falta FreeRDP: sudo apt install freerdp-x11")
    port = free_port()
    tunnel = subprocess.Popen(forward_command(i, 3389, port))
    try:
        # El plugin tarda unos segundos en abrir el puerto local.
        for _ in range(60):
            if tunnel.poll() is not None:
                raise RuntimeError("El túnel de SSM se ha cerrado (¿agente desconectado o sin permisos?)")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("El túnel no ha abierto el puerto local")
        # /cert:ignore: el certificado es de la instancia, pero el nombre es localhost y cambia el puerto cada vez.
        cmd = [client, f"/v:127.0.0.1:{port}", "+dynamic-resolution", "/size:85%", "/cert:ignore",
               f"/t:{i.name or i.id}"]
        if user:
            domain, sep, name = user.rpartition("\\")
            cmd += [f"/u:{name}"] + ([f"/d:{domain}"] if sep else [])
        return subprocess.run(cmd).returncode
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
