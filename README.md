# EC2 por SSM

App de escritorio para Ubuntu (GTK4 + libadwaita) que recorre **todos los perfiles de `~/.aws/config`** y todas sus
regiones, lista las instancias EC2 (y los equipos híbridos `mi-…`) con el agente de **SSM** en línea y abre con un
botón una terminal, un reenvío de puertos o un escritorio remoto por **Session Manager**. Sin SSH, sin puertos
abiertos y sin claves.

Documentación para desarrollar: [AGENTS.md](AGENTS.md).

## Requisitos

- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) y
  [session-manager-plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).
- Perfiles en `~/.aws/config` (claves, roles o SSO).
- Para Escritorio remoto: FreeRDP 3 (`sudo apt install freerdp-x11`).

## Instalar

1. Baja `infranettone-ec2-connect_<versión>_all.deb` de la última
   [release](https://github.com/infranettone/infranettone-ec2-connect/releases).
2. `sudo apt install ./infranettone-ec2-connect_*_all.deb`
3. Abre **EC2 por SSM** desde el menú.

## Uso

- Al abrir se ve la última lista guardada y se recorre AWS en segundo plano (botón ⟳ para repetir).
- El **buscador** filtra por nombre, id, IP, tipo, cuenta, perfil o región; escribir en la ventana ya busca.
- Por fila: **terminal** (`aws ssm start-session`), **Escritorio remoto** en las Windows (túnel al 3389 y
  FreeRDP contra `localhost`) y en el menú ⋯ **reenviar un puerto** (de la instancia o de otro equipo al que llegue,
  p. ej. una RDS), copiar la orden, el id o las IP y abrir la instancia en la consola.
- Los perfiles sin credenciales válidas salen arriba; los de SSO con **Iniciar sesión** (`aws sso login`).
- **Preferencias**: qué perfiles se recorren, regiones fijas (vacío = todas las habilitadas en cada cuenta) y ver
  también las instancias sin agente. Si varios perfiles son la misma cuenta, se recorre solo el primero.

Por terminal:

```bash
infranettone-ec2-connect --scan               # recorre AWS y lista
infranettone-ec2-connect --list [FILTRO]      # de la caché
infranettone-ec2-connect --connect web-01     # terminal por SSM (id, nombre o texto que case con una sola)
infranettone-ec2-connect --rdp i-0123… --user Administrator
```

## Permisos de IAM

`sts:GetCallerIdentity`, `ec2:DescribeRegions`, `ec2:DescribeInstances`, `ssm:DescribeInstanceInformation`,
`ssm:StartSession` y `ssm:TerminateSession`. Las instancias necesitan el agente de SSM y un rol con
`AmazonSSMManagedInstanceCore`.

## Ficheros

- `~/.config/infranettone-ec2-connect/config.json`: preferencias.
- `~/.cache/infranettone-ec2-connect/instances.json`: última lista (no sale del equipo).
