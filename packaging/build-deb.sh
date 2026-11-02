#!/usr/bin/env bash
# Construye dist/infranettone-ec2-connect_<versión>_all.deb. Uso: packaging/build-deb.sh [versión]
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION="${1:-0.0.0}"
VERSION="${VERSION#v}"
PKG=infranettone-ec2-connect
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

# Código: en dist-packages para que /usr/bin/python3 -m ec2_connect funcione.
LIB="$ROOT/usr/lib/python3/dist-packages/ec2_connect"
install -d "$LIB"
install -m 644 ec2_connect/*.py "$LIB/"
echo "VERSION = \"$VERSION\"" > "$LIB/_version.py"  # la que enseña la app (version.py)

install -D -m 755 /dev/stdin "$ROOT/usr/bin/$PKG" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 -m ec2_connect "$@"
EOF

install -D -m 644 packaging/com.infranettone.Ec2Connect.desktop \
  "$ROOT/usr/share/applications/com.infranettone.Ec2Connect.desktop"
install -D -m 644 README.md "$ROOT/usr/share/doc/$PKG/README.md"

install -d "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: Raul Adamuz <radamuzc@gmail.com>
Depends: python3 (>= 3.12), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), python3-boto3
Recommends: freerdp-x11 | freerdp3-x11, ptyxis | gnome-terminal | x-terminal-emulator
Installed-Size: $(du -sk "$ROOT/usr" | cut -f1)
Homepage: https://github.com/infranettone/infranettone-ec2-connect
Description: Conecta por SSM a las instancias de todas las cuentas de AWS
 App GTK4/libadwaita que recorre los perfiles de ~/.aws/config y todas sus
 regiones, lista las instancias con el agente de SSM y abre una terminal,
 un reenvío de puertos o un escritorio remoto por Session Manager.
 Necesita AWS CLI v2 y session-manager-plugin.
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v py3compile >/dev/null && py3compile -p infranettone-ec2-connect /usr/lib/python3/dist-packages/ec2_connect || true
EOF
cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
command -v py3clean >/dev/null && py3clean -p infranettone-ec2-connect || true
find /usr/lib/python3/dist-packages/ec2_connect -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
EOF
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"

find "$ROOT" -type d -exec chmod 755 {} +

mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/${PKG}_${VERSION}_all.deb"
