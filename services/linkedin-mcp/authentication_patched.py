"""
Authentication logic for LinkedIn MCP Server.

Handles LinkedIn session management with persistent browser profile.
Patched to support LINKEDIN_COOKIE env var for headless Docker setups.
"""

import logging
import os
import shutil
from pathlib import Path

from linkedin_mcp_server.drivers.browser import (
    get_profile_dir,
    profile_exists,
)
from linkedin_mcp_server.exceptions import CredentialsNotFoundError

logger = logging.getLogger(__name__)


def get_authentication_source() -> bool:
    """
    Check if authentication is available via persistent profile or LINKEDIN_COOKIE env var.

    Returns:
        True if profile exists or LINKEDIN_COOKIE is set

    Raises:
        CredentialsNotFoundError: If no authentication method available
    """
    # Accept LINKEDIN_COOKIE env var as valid auth
    if os.environ.get("LINKEDIN_COOKIE"):
        logger.info("Using LINKEDIN_COOKIE env var for authentication")
        return True

    profile_dir = get_profile_dir()
    if profile_exists(profile_dir):
        logger.info(f"Using persistent profile from {profile_dir}")
        return True

    raise CredentialsNotFoundError(
        "No LinkedIn authentication found.\n\n"
        "Options:\n"
        "  1. Set LINKEDIN_COOKIE env var with your li_at cookie value\n"
        "  2. Run with --get-session to create a browser profile\n"
        "  3. Run with --no-headless to login interactively\n\n"
        "For Docker users:\n"
        "  Set LINKEDIN_COOKIE in docker-compose.yml environment"
    )


def clear_profile(profile_dir: Path | None = None) -> bool:
    """
    Clear stored browser profile directory.

    Args:
        profile_dir: Path to profile directory

    Returns:
        True if clearing was successful
    """
    if profile_dir is None:
        profile_dir = get_profile_dir()

    if profile_dir.exists():
        try:
            shutil.rmtree(profile_dir)
            logger.info(f"Profile cleared from {profile_dir}")
            return True
        except OSError as e:
            logger.warning(f"Could not clear profile: {e}")
            return False
    return True
