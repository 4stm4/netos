from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class BrandingConfig(BaseModel):
    name: str = "4stm4 netOS"
    id: str = "4stm4-netos"
    version: str = "0.1.0"
    hostname: str = "4stm4-netos"
    root_password: str = ""
    ssh_authorized_key: str = ""
    console: Literal["ttyAMA0", "ttyS0", "tty1", "both"] = "ttyAMA0"

    @field_validator("id")
    @classmethod
    def id_slug(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("id must match ^[a-z0-9-]+$")
        return v

    @field_validator("hostname")
    @classmethod
    def hostname_valid(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$", v):
            raise ValueError("hostname must match ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")
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
    enabled: list[str] = []   # BR2_PACKAGE_* keys (without =y) — from catalogue checkboxes
    custom:  list[str] = []   # raw BR2_PACKAGE_*=y lines — from custom modal

    def extra_packages(self) -> list[str]:
        """Return deduplicated list of extra BR2_PACKAGE_*=y lines for the builder.

        Converts enabled keys (``BR2_PACKAGE_FOO``) to ``BR2_PACKAGE_FOO=y``
        and appends custom raw lines, preserving order and removing duplicates.
        """
        lines = [f"{k}=y" for k in self.enabled] + list(self.custom)
        return list(dict.fromkeys(lines))


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


class NervumConfig(BaseModel):
    enabled: bool = True
    source: Literal["git", "local"] = "git"
    git_url: str = "https://github.com/4stm4/nervum.git"
    git_ref: str = "main"
    source_dir: str = ""


class ApplianceConfig(BaseModel):
    type: Literal["netos", "tinywifi"] = "netos"


class ImageConfig(BaseModel):
    size_mb: int = 512
    boot_mb: int = 64


class PathsConfig(BaseModel):
    """Configurable filesystem paths for the build pipeline.

    Empty string means "use the project default".
    All paths are absolute on the build host.
    """
    # Where Buildroot unpacks, compiles, and stores its output tree.
    # Default: <project_root>/temp
    temp_dir: str = ""

    # Where toolchain and rootfs cache archives are stored.
    # Default: <temp_dir>/cache
    cache_dir: str = ""

    # Directory where the final .img file is written.
    # Default: <project_root>
    image_output_dir: str = ""

    # Override the image filename (e.g. "myos-v2.img").
    # Default: target's image_name (e.g. "netos-arm64.img")
    image_filename: str = ""


class KernelConfig(BaseModel):
    """Kernel version overrides. Empty string = use compiled-in default."""
    # For RPi targets (kernel_source="rpi"): branch name, e.g. "rpi-6.12.y"
    rpi_branch: str = ""
    # For mainline/QEMU targets (kernel_source="mainline"): version, e.g. "6.12.27"
    mainline_version: str = ""
    # CONFIG_*=y lines (subsystems/features)
    options: list[str] = []
    # CONFIG_*=m lines (loadable modules)
    modules: list[str] = []
    # CONFIG_*=y/m lines (hardware drivers)
    drivers: list[str] = []


class Profile(BaseModel):
    name: str
    target: str = "qemu-virt"
    branding: BrandingConfig = BrandingConfig()
    network: NetworkConfig = NetworkConfig()
    packages: PackagesConfig = PackagesConfig()
    webui: WebUIConfig = WebUIConfig()
    nervum: NervumConfig = NervumConfig()
    image: ImageConfig = ImageConfig()
    paths: PathsConfig = PathsConfig()
    appliance: ApplianceConfig = ApplianceConfig()
    kernel: KernelConfig = KernelConfig()


class BuildEvent(BaseModel):
    build_id: str
    event: str  # log | stage | progress | done | error
    data: str
    stage: str = ""
