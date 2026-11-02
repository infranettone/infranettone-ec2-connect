"""Interfaz GTK4/libadwaita: todas las instancias por perfil, buscador y botones de conexión por SSM."""

import shlex
import threading
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import inventory, session  # noqa: E402
from .config import Config  # noqa: E402
from .inventory import Instance, ProfileError  # noqa: E402
from .version import version as app_version  # noqa: E402

APP_ID = "com.infranettone.Ec2Connect"


class Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="EC2 por SSM", default_width=1000, default_height=860)
        self.cfg = Config.load()
        self.busy = False
        self.instances: list[Instance] = inventory.cached()
        self.errors: list[ProfileError] = []
        # Fila → instancia, y grupo → sus filas: el buscador solo cambia la visibilidad, no reconstruye.
        self.rows: list[tuple[Adw.ActionRow, Instance]] = []
        self.groups: list[tuple[Adw.PreferencesGroup, list[Adw.ActionRow]]] = []

        self.toasts = Adw.ToastOverlay()
        self.search = Gtk.SearchEntry(placeholder_text="Buscar por nombre, id, IP, cuenta, región…", hexpand=True,
                                      width_request=420)
        self.search.connect("search-changed", lambda *_: self._filter())
        self.online_only = Gtk.ToggleButton(icon_name="network-transmit-receive-symbolic", active=True,
                                            tooltip_text="Solo las que tienen el agente de SSM en línea")
        self.online_only.connect("toggled", lambda *_: self._filter())

        header = Adw.HeaderBar(title_widget=self.search)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                      tooltip_text="Recorrer todas las cuentas y regiones")
        self.refresh_btn.connect("clicked", lambda *_: self.scan())
        prefs = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Preferencias")
        prefs.connect("clicked", lambda *_: self._preferences())
        header.pack_end(self.refresh_btn)
        header.pack_end(prefs)
        header.pack_start(self.online_only)
        about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text=f"Acerca de · versión {app_version()}")
        about.connect("clicked", lambda *_: self._about())
        header.pack_start(about)

        self.page = Adw.PreferencesPage()
        self.summary = Gtk.Label(css_classes=["dim-label"], margin_top=6, wrap=True)
        self.progress_bar = Gtk.ProgressBar(show_text=True, margin_start=16, margin_end=16)
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                     wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, left_margin=8)
        log_box = Gtk.Expander(label="Registro", margin_start=16, margin_end=16,
                               child=Gtk.ScrolledWindow(child=self.log_view, min_content_height=140,
                                                        css_classes=["card"]))
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_bottom=12)
        for w in (self.summary, self.progress_bar, log_box):
            bottom.append(w)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.page.set_vexpand(True)
        content.append(self.page)
        content.append(bottom)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        # Ctrl+F y escribir directamente van al buscador.
        self.search.set_key_capture_widget(self)

        self._build()
        missing = session.missing_tools()
        if missing:
            self.log(f"✖ Falta {', '.join(missing)}: sin eso no se puede abrir ninguna sesión (ver README)")
        # Con la caché se ve todo al momento; la lista buena llega cuando termina el recorrido.
        self.scan()

    # --- trabajo en segundo plano ---

    def log(self, msg: str) -> None:
        def append():
            buf = self.log_view.get_buffer()
            buf.insert(buf.get_end_iter(), msg + "\n")
            self.log_view.scroll_to_mark(buf.get_insert(), 0, False, 0, 0)
        GLib.idle_add(append)

    def toast(self, msg: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=msg, timeout=4))

    def scan(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.refresh_btn.set_sensitive(False)
        self.progress_bar.set_text("Recorriendo cuentas y regiones…")
        pulse = GLib.timeout_add(150, lambda: self.progress_bar.pulse() or True)

        def worker():
            try:
                result = inventory.scan(self.cfg, self.log)
                GLib.idle_add(self._set_instances, *result)
            except Exception as e:  # noqa: BLE001 - lo mostramos en la UI
                self.log(traceback.format_exc())
                GLib.idle_add(self.toast, f"No se ha podido recorrer AWS: {e}")
            finally:
                GLib.idle_add(self._done, pulse)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, pulse: int) -> None:
        GLib.source_remove(pulse)
        self.busy = False
        self.refresh_btn.set_sensitive(True)
        self.progress_bar.set_text("")
        self.progress_bar.set_fraction(0)

    def _set_instances(self, instances: list[Instance], errors: list[ProfileError]) -> None:
        self.instances, self.errors = instances, errors
        self._build()

    # --- lista ---

    def _build(self) -> None:
        for g, _ in self.groups:
            self.page.remove(g)
        self.rows, self.groups = [], []

        if self.errors:
            g = Adw.PreferencesGroup(title="Perfiles sin acceso",
                                     description="Sin credenciales válidas: no se ven sus instancias")
            for e in self.errors:
                row = Adw.ActionRow(title=e.profile, subtitle=GLib.markup_escape_text(e.message[:200]),
                                    subtitle_lines=2)
                row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
                if e.sso:
                    row.add_suffix(self._button("Iniciar sesión", lambda p=e.profile: self._login(p),
                                                "suggested-action"))
                row.add_suffix(self._button("", lambda p=e.profile: self._skip(p), "flat",
                                            icon="list-remove-symbolic", tooltip="No recorrer este perfil"))
                g.add(row)
            self.page.add(g)
            self.groups.append((g, []))

        by_profile: dict[str, list[Instance]] = {}
        for i in self.instances:
            by_profile.setdefault(i.profile, []).append(i)
        for profile, items in by_profile.items():
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(profile),
                                     description=f"Cuenta {items[0].account}")
            rows = []
            for i in items:
                row = self._instance_row(i)
                g.add(row)
                rows.append(row)
                self.rows.append((row, i))
            self.page.add(g)
            self.groups.append((g, rows))
        self._filter()

    def _instance_row(self, i: Instance) -> Adw.ActionRow:
        details = [i.id, i.region, i.private_ip, i.instance_type, i.platform,
                   i.state if i.state != "running" else "", i.ping if i.ping != "Online" else ""]
        row = Adw.ActionRow(title=GLib.markup_escape_text(i.name or i.id),
                            subtitle=GLib.markup_escape_text(" · ".join(d for d in details if d)),
                            activatable=i.online)
        row.add_prefix(Gtk.Image(icon_name="computer-symbolic" if i.online else "network-offline-symbolic",
                                 css_classes=[] if i.online else ["dim-label"]))
        if i.windows:
            rdp = self._button("", lambda: self._rdp(i), "flat", icon="preferences-desktop-remote-desktop-symbolic",
                               tooltip="Escritorio remoto por un túnel de SSM")
            rdp.set_sensitive(i.online)
            row.add_suffix(rdp)
        shell = self._button("", lambda: self._open(session.open_shell, i), "flat",
                             icon="utilities-terminal-symbolic", tooltip="Terminal por SSM")
        shell.set_sensitive(i.online)
        row.add_suffix(shell)
        row.add_suffix(self._menu(i))
        if i.online:
            row.connect("activated", lambda *_: self._open(session.open_shell, i))
        return row

    def _menu(self, i: Instance) -> Gtk.MenuButton:
        items = [("Reenviar un puerto…", lambda: self._forward(i)),
                 ("Copiar la orden de SSM", lambda: self._copy(shlex.join(session.shell_command(i)))),
                 ("Copiar el id", lambda: self._copy(i.id))]
        if i.private_ip:
            items.append(("Copiar la IP privada", lambda: self._copy(i.private_ip)))
        if i.public_ip:
            items.append(("Copiar la IP pública", lambda: self._copy(i.public_ip)))
        if i.id.startswith("i-"):
            items.append(("Abrir en la consola de AWS", lambda: Gtk.UriLauncher.new(
                f"https://{i.region}.console.aws.amazon.com/ec2/home?region={i.region}"
                f"#InstanceDetails:instanceId={i.id}").launch(self, None, None, None)))
        menu, group = Gio.Menu(), Gio.SimpleActionGroup()
        for n, (label, cb) in enumerate(items):
            action = Gio.SimpleAction(name=f"a{n}")
            action.connect("activate", lambda *_, cb=cb: cb())
            group.add_action(action)
            menu.append(label, f"inst.a{n}")
        button = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text="Más")
        button.insert_action_group("inst", group)
        return button

    def _filter(self) -> None:
        text = self.search.get_text().strip()
        online = self.online_only.get_active()
        shown = 0
        for row, i in self.rows:
            visible = (not online or i.online) and (not text or i.matches(text))
            row.set_visible(visible)
            shown += visible
        for g, rows in self.groups:
            g.set_visible(not rows or any(r.get_visible() for r in rows))
        total = len(self.instances)
        self.summary.set_label(f"{shown} de {total} instancias · {sum(i.online for i in self.instances)} en línea · "
                               f"{len({i.account for i in self.instances})} cuentas"
                               + (f" · {len(self.errors)} perfiles sin acceso" if self.errors else ""))

    # --- acciones ---

    def _button(self, label: str, cb, *classes: str, icon: str = "", tooltip: str = "") -> Gtk.Button:
        b = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=list(classes), tooltip_text=tooltip or None)
        if icon:
            b.set_icon_name(icon)
        else:
            b.set_label(label)
        b.connect("clicked", lambda *_: cb())
        return b

    def _copy(self, text: str) -> None:
        Gdk.Display.get_default().get_clipboard().set(text)
        self.toast(f"Copiado: {text}")

    def _open(self, fn, *args) -> None:
        try:
            fn(*args)
        except (RuntimeError, ValueError, OSError) as e:
            self.toast(str(e))

    def _login(self, profile: str) -> None:
        self._open(session.open_login, profile)
        self.toast("Inicia sesión en el navegador y pulsa Actualizar")

    def _skip(self, profile: str) -> None:
        self.cfg.skip_profiles = sorted({*self.cfg.skip_profiles, profile})
        self.cfg.save()
        self.errors = [e for e in self.errors if e.profile != profile]
        self._build()

    def _dialog(self, heading: str, body: str, rows: list[Gtk.Widget], label: str, on_ok) -> None:
        box = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for r in rows:
            box.append(r)
        d = Adw.AlertDialog(heading=heading, body=body, extra_child=box)
        d.add_response("cancel", "Cancelar")
        d.add_response("ok", label)
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("ok")
        d.connect("response", lambda _d, r: r == "ok" and on_ok())
        d.present(self)

    def _forward(self, i: Instance) -> None:
        remote = Adw.EntryRow(title="Puerto remoto", text="22")
        local = Adw.EntryRow(title="Puerto local", text=str(session.free_port()))
        host = Adw.EntryRow(title="Otro equipo (opcional: RDS, balanceador…)")

        def ok():
            try:
                rp, lp = int(remote.get_text()), int(local.get_text())
                if not (0 < rp < 65536 and 0 < lp < 65536):
                    raise ValueError
            except ValueError:
                self.toast("Puertos no válidos")
                return
            self._open(session.open_forward, i, rp, lp, host.get_text().strip())
            self._copy(f"127.0.0.1:{lp}")

        self._dialog(f"Reenviar un puerto de {i.name or i.id}",
                     "El túnel se queda abierto mientras esté la ventana de la terminal.",
                     [remote, local, host], "Abrir túnel", ok)

    def _rdp(self, i: Instance) -> None:
        user = Adw.EntryRow(title="Usuario (DOMINIO\\usuario, opcional)", text="Administrator")
        self._dialog(f"Escritorio remoto a {i.name or i.id}",
                     "Abre un túnel de SSM al 3389 y FreeRDP contra él. La contraseña se pide ahí.",
                     [user], "Conectar", lambda: self._open(session.open_rdp, i, user.get_text().strip()))

    def _preferences(self) -> None:
        d = Adw.PreferencesDialog(title="Preferencias")
        page = Adw.PreferencesPage()
        d.add(page)

        general = Adw.PreferencesGroup(title="Recorrido")
        unmanaged = Adw.SwitchRow(title="Instancias sin agente de SSM",
                                  subtitle="Verlas también (no se puede conectar)", active=self.cfg.show_unmanaged)
        regions = Adw.EntryRow(title="Regiones (separadas por comas; vacío = todas las habilitadas)",
                               text=", ".join(self.cfg.regions))
        for w in (unmanaged, regions):
            general.add(w)
        page.add(general)

        profiles = Adw.PreferencesGroup(title="Perfiles de ~/.aws/config",
                                        description="Los repetidos de una misma cuenta se recorren una vez")
        switches = {}
        for p in inventory.profiles():
            switches[p] = Adw.SwitchRow(title=GLib.markup_escape_text(p), active=p not in self.cfg.skip_profiles)
            profiles.add(switches[p])
        page.add(profiles)

        def closed(*_):
            self.cfg.show_unmanaged = unmanaged.get_active()
            self.cfg.regions = [r.strip() for r in regions.get_text().split(",") if r.strip()]
            self.cfg.skip_profiles = sorted(p for p, s in switches.items() if not s.get_active())
            self.cfg.save()
            self.scan()

        d.connect("closed", closed)
        d.present(self)

    def _about(self) -> None:
        Adw.AboutDialog(application_name="EC2 por SSM", application_icon="utilities-terminal",
                        version=app_version(), developer_name="Raul Adamuz",
                        website="https://github.com/infranettone/infranettone-ec2-connect",
                        license_type=Gtk.License.CUSTOM).present(self)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()
