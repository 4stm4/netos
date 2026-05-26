"""Maps a Profile model to NETOS_* environment variables for main.py."""
from __future__ import annotations

from src.configurator.models import Profile


def profile_to_env(profile: Profile) -> dict[str, str]:
    env: dict[str, str] = {}

    # branding
    env["NETOS_VERSION"] = profile.branding.version
    env["NETOS_HOSTNAME"] = profile.branding.hostname
    if profile.branding.root_password:
        env["NETOS_ROOT_PASSWORD"] = profile.branding.root_password
    if profile.branding.ssh_authorized_key:
        env["NETOS_SSH_AUTHORIZED_KEY"] = profile.branding.ssh_authorized_key
    env["NETOS_CONSOLE"] = profile.branding.console

    # image sizes
    env["NETOS_IMAGE_SIZE_MB"] = str(profile.image.size_mb)
    env["NETOS_BOOT_SIZE_MB"] = str(profile.image.boot_mb)

    # network eth0
    if profile.network.eth0.mode == "static":
        env["NETOS_ETH0_ADDRESS"] = profile.network.eth0.address
        env["NETOS_ETH0_GATEWAY"] = profile.network.eth0.gateway
        env["NETOS_ETH0_DNS"] = profile.network.eth0.dns

    # wifi
    if profile.network.wifi.ssid:
        env["NETOS_WIFI_SSID"] = profile.network.wifi.ssid
        env["NETOS_WIFI_PSK"] = profile.network.wifi.psk
        env["NETOS_WIFI_COUNTRY"] = profile.network.wifi.country
    env["NETOS_WIFI_BOOTSTRAP"] = "1" if profile.network.wifi.bootstrap else "0"

    # webui source
    if profile.webui.source == "local":
        env["NETOS_WEBUI_SOURCE_DIR"] = profile.webui.source_dir
    elif profile.webui.source == "runtime":
        env["NETOS_WEBUI_EMBED"] = "0"

    env["NETOS_WEBUI_GIT_URL"] = profile.webui.git_url
    env["NETOS_WEBUI_GIT_REF"] = profile.webui.git_ref
    env["NETOS_WEBUI_PORT"] = str(profile.webui.port)
    env["NETOS_WEBUI_DATA_DIR"] = profile.webui.data_dir
    env["NETOS_WEBUI_DATABASE_URL"] = profile.webui.database_url
    env["NETOS_WEBUI_PIP_MODE"] = profile.webui.pip_mode
    env["NETOS_WEBUI_ADMIN_USERNAME"] = profile.webui.admin_username
    if profile.webui.admin_password:
        env["NETOS_WEBUI_ADMIN_PASSWORD"] = profile.webui.admin_password
    env["NETOS_WEBUI_HEALTH_PATH"] = profile.webui.health_path
    env["NETOS_WEBUI_APP_MODULE"] = profile.webui.app_module

    # nervum SDN controller
    if profile.nervum.enabled:
        env["NETOS_NERVUM_GIT_URL"] = profile.nervum.git_url
        env["NETOS_NERVUM_GIT_REF"] = profile.nervum.git_ref
        if profile.nervum.source == "local":
            env["NETOS_NERVUM_SOURCE_DIR"] = profile.nervum.source_dir

    # paths
    if profile.paths.temp_dir:
        env["NETOS_TEMP_DIR"] = profile.paths.temp_dir
    if profile.paths.cache_dir:
        env["NETOS_CACHE_DIR"] = profile.paths.cache_dir
    if profile.paths.image_output_dir:
        env["NETOS_IMAGE_OUTPUT_DIR"] = profile.paths.image_output_dir
    if profile.paths.image_filename:
        env["NETOS_IMAGE_FILENAME"] = profile.paths.image_filename

    return env
