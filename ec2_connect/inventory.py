"""Inventario de instancias: todos los perfiles de ~/.aws/config × regiones, en paralelo.

Por región se cruzan dos llamadas: ssm:DescribeInstanceInformation (qué instancias tienen el agente conectado) y
ec2:DescribeInstances (nombre, estado, IP). El resultado se guarda en ~/.cache para enseñarlo al abrir sin esperar.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .config import Config

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "infranettone-ec2-connect" / "instances.json"


@dataclass
class Instance:
    profile: str
    account: str
    region: str
    id: str
    name: str
    state: str  # running, stopped… (EC2) o «managed» si es un equipo híbrido (mi-…)
    ping: str  # Online, ConnectionLost, Inactive o "" sin agente
    platform: str  # Linux / Windows
    private_ip: str = ""
    public_ip: str = ""
    instance_type: str = ""

    @property
    def online(self) -> bool:
        return self.ping == "Online"

    @property
    def windows(self) -> bool:
        return self.platform.lower().startswith("windows")

    def matches(self, text: str) -> bool:
        text = text.lower()
        return all(w in " ".join((self.name, self.id, self.profile, self.account, self.region, self.private_ip,
                                  self.public_ip, self.platform, self.instance_type)).lower() for w in text.split())


@dataclass
class ProfileError:
    profile: str
    message: str
    sso: bool  # se arregla con aws sso login


def profiles() -> list[str]:
    import botocore.session

    return sorted(botocore.session.Session().available_profiles)


def _session(profile: str):
    import boto3

    return boto3.Session(profile_name=profile)


def _is_sso_error(e: Exception) -> bool:
    name = type(e).__name__
    return name in ("SSOTokenLoadError", "UnauthorizedSSOTokenError", "TokenRetrievalError") or "sso" in str(e).lower()


def _regions(sess, cfg: Config) -> list[str]:
    if cfg.regions:
        return cfg.regions
    ec2 = sess.client("ec2", region_name=sess.region_name or cfg.default_region)
    return sorted(r["RegionName"] for r in ec2.describe_regions()["Regions"])


def _scan_region(sess, profile: str, account: str, region: str, cfg: Config) -> list[Instance]:
    ssm = sess.client("ssm", region_name=region)
    managed: dict[str, dict] = {}
    for page in ssm.get_paginator("describe_instance_information").paginate():
        for i in page["InstanceInformationList"]:
            managed[i["InstanceId"]] = i

    found: list[Instance] = []
    ec2 = sess.client("ec2", region_name=region)
    for page in ec2.get_paginator("describe_instances").paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}]):
        for r in page["Reservations"]:
            for i in r["Instances"]:
                info = managed.pop(i["InstanceId"], {})
                if not info and not cfg.show_unmanaged:
                    continue
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                found.append(Instance(
                    profile, account, region, i["InstanceId"], tags.get("Name", ""), i["State"]["Name"],
                    info.get("PingStatus", ""), info.get("PlatformType") or i.get("PlatformDetails", "Linux"),
                    i.get("PrivateIpAddress", ""), i.get("PublicIpAddress", ""), i.get("InstanceType", "")))
    # Lo que queda son equipos híbridos (mi-…) registrados en SSM: también se puede entrar.
    for iid, info in managed.items():
        found.append(Instance(profile, account, region, iid, info.get("ComputerName", ""), "managed",
                              info.get("PingStatus", ""), info.get("PlatformType", ""), info.get("IPAddress", "")))
    return found


def scan(cfg: Config, log: Callable[[str], None]) -> tuple[list[Instance], list[ProfileError]]:
    """Recorre todos los perfiles; los que fallan (sin credenciales, SSO caducado) van a la lista de errores."""
    instances: list[Instance] = []
    errors: list[ProfileError] = []
    # Varios perfiles pueden ser la misma cuenta con otro rol: se recorre solo el primero de cada cuenta.
    seen_accounts: dict[str, str] = {}
    jobs = []

    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        def prepare(profile: str):
            sess = _session(profile)
            account = sess.client("sts", region_name=sess.region_name or cfg.default_region) \
                .get_caller_identity()["Account"]
            return sess, account, _regions(sess, cfg)

        prepared = {p: pool.submit(prepare, p) for p in profiles() if p not in cfg.skip_profiles}
        for profile, fut in prepared.items():
            try:
                sess, account, regions = fut.result()
            except Exception as e:  # noqa: BLE001 - cada perfil falla por su cuenta
                errors.append(ProfileError(profile, str(e), _is_sso_error(e)))
                log(f"✖ {profile}: {e}")
                continue
            if account in seen_accounts:
                log(f"{profile}: cuenta {account} ya recorrida con {seen_accounts[account]}")
                continue
            seen_accounts[account] = profile
            log(f"{profile} ({account}): {len(regions)} regiones")
            jobs += [(profile, region, pool.submit(_scan_region, sess, profile, account, region, cfg))
                     for region in regions]

        for profile, region, fut in jobs:
            try:
                instances += fut.result()
            except Exception as e:  # noqa: BLE001 - región sin permisos o deshabilitada
                log(f"⚠ {profile} {region}: {e}")

    instances.sort(key=lambda i: (i.profile, i.region, i.name.lower() or "~", i.id))
    save_cache(instances)
    log(f"{len(instances)} instancias, {sum(i.online for i in instances)} con SSM en línea")
    return instances, errors


def save_cache(instances: list[Instance]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps([asdict(i) for i in instances], indent=1) + "\n")


def cached() -> list[Instance]:
    try:
        return [Instance(**d) for d in json.loads(CACHE.read_text())]
    except (OSError, ValueError, TypeError):
        return []
