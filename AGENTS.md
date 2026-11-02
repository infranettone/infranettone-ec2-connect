# Guía para agentes (y humanos con prisa)

App de escritorio para Ubuntu (Python + GTK 4 + libadwaita ≥ 1.5) que lista las instancias de todas las cuentas de
AWS configuradas y conecta a ellas por SSM Session Manager. Uso: [README.md](README.md).

| Módulo | Qué hace |
|---|---|
| `ec2_connect/inventory.py` | Perfiles × regiones en paralelo: cruza `ssm:DescribeInstanceInformation` con `ec2:DescribeInstances`; caché en `~/.cache` |
| `ec2_connect/session.py` | `aws ssm start-session` (terminal, reenvío de puertos, `aws sso login`) en una ventana de terminal; RDP = túnel + xfreerdp |
| `ec2_connect/config.py` | `~/.config/infranettone-ec2-connect/config.json`: perfiles omitidos, regiones, sin agente |
| `ec2_connect/ui.py` | Lista agrupada por perfil, buscador, diálogos de puerto y RDP, preferencias |
| `ec2_connect/__main__.py` | Línea de órdenes (`--scan`, `--list`, `--connect`, `--rdp`) |

## Reglas del proyecto

- **El repositorio es público**: nada de ids de cuenta, nombres de perfiles, instancias, IP ni correos internos en
  código, docs, commits o ejemplos. Los datos reales solo viven en `~/.aws` y en la caché del usuario.
- **Todo en español** (UI, comentarios, commits, docs), con tildes correctas. Identificadores en inglés.
- Comentarios breves que explican el *porqué*. Sin linter: la CI hace `python3 -m compileall -q ec2_connect`.
- Commits: título en español, **sin `Co-authored-by:`** ni ninguna otra línea de atribución. Releases: tag `v*` (SemVer).
- Lo lento va en hilos y vuelve a la UI con `GLib.idle_add`.
- A los procesos se les pasan listas, nunca un shell; perfil, región e id se validan en `session._check`.

## Detalles

- Varios perfiles pueden ser la misma cuenta (roles distintos): se recorre la cuenta una vez, con el primer perfil.
- Las instancias sin `Name` se ven por id; los equipos híbridos (`mi-…`) salen de SSM sin pasar por EC2.
- El RDP se ejecuta dentro de la terminal (`python3 -m ec2_connect --rdp …`): al cerrar la ventana se cierra el túnel.
  `/cert:ignore` porque se conecta a `127.0.0.1` con un puerto distinto cada vez.

## Probar

```bash
python3 -m ec2_connect            # interfaz
python3 -m ec2_connect --scan     # recorrido por terminal
packaging/build-deb.sh 0.1.0      # .deb en dist/
```
