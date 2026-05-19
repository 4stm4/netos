from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class BrandingConfig(BaseModel):
    name: str = "4stm4 netOS"
    id: str = "4stm4-netos"
    version: str = "0.1.0"
    hostname: str = "4stm4-netos"

    @field_validator("id")
    @classmethod
    def id_slug(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("id must match ^[a-z0-9-]+$")
        return v


class Eth0Config(BaseModel):
    mode: Literal["dhcp", "static", "disabled"] = "dhcp"
    address: str = ""
    gateway: str = ""
    dns: str = ""


class WifiConfig(BaseModel):
    country: str = "US"
    ssid: str = ""
    psk: str = ""
    bootstrap: bool = True


class NetworkConfig(BaseModel):
    eth0: Eth0Config = Eth0Config()
    wifi: WifiConfig = WifiConfig()


class PackagesConfig(BaseModel):
    enabled: list[str] = []
    custom: list[str] = []


class WebUIConfig(BaseModel):
    source: Literal["git", "local", "runtime"] = "git"
    git_url: str = "https://github.com/4stm4/testum.git"
    git_ref: str = "main"
    source_dir: str = ""
    port: int = 8080
    data_dir: str = "/opt/testum"
    database_url: str = "sqlite:////opt/testum/testum.db"
    pip_mode: Literal["never", "auto"] = "never"
    admin_username: str = "admin"
    admin_password: str = ""
    health_path: str = "/health"
    app_module: str = "app.main:app"


class ImageConfig(BaseModel):
    size_mb: int = 512
    boot_mb: int = 64


class Profile(BaseModel):
    name: str
    target: str = "qemu-virt"
    branding: BrandingConfig = BrandingConfig()
    network: NetworkConfig = NetworkConfig()
    packages: PackagesConfig = PackagesConfig()
    webui: WebUIConfig = WebUIConfig()
    image: ImageConfig = ImageConfig()


class BuildEvent(BaseModel):
    build_id: str
    event: str  # log | stage | progress | done | error
    data: str
    stage: str = ""
