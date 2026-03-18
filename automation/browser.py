"""
公共浏览器上下文创建 — 消除 open_browser / auto_cmd / antigravity_login 中的重复代码
"""

import glob
import logging
import os
import signal

from config import (
    BROWSER_CHANNEL, BROWSER_HEADLESS, BROWSER_SLOW_MO, BROWSER_USER_DATA_DIR,
)

logger = logging.getLogger(__name__)


def _cleanup_profile_lock(profile_dir: str):
    """清理 Chrome Profile 的 SingletonLock / SingletonCookie / SingletonSocket 残留"""
    for pattern in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_file = os.path.join(profile_dir, pattern)
        if os.path.exists(lock_file) or os.path.islink(lock_file):
            try:
                os.remove(lock_file)
                logger.info("清理残留锁文件: %s", lock_file)
            except OSError:
                try:
                    os.unlink(lock_file)
                    logger.info("unlink 残留锁文件: %s", lock_file)
                except OSError as e:
                    logger.warning("清理锁文件失败: %s -> %s", lock_file, e)


def _kill_stale_chrome(profile_dir: str):
    """尝试杀掉占用此 profile 的残留 Chrome 进程"""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", profile_dir],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            for pid_str in result.stdout.strip().split("\n"):
                pid = int(pid_str.strip())
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info("已终止残留 Chrome 进程: pid=%s", pid)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    logger.warning("无权终止进程: pid=%s", pid)
    except Exception:
        pass


async def launch_parent_context(playwright, parent_id):
    """
    为指定家长启动独立 Chrome Profile 的持久化浏览器上下文。

    返回 (context, page) 元组。调用方负责关闭 context。
    """
    profile_dir = os.path.join(BROWSER_USER_DATA_DIR, f"parent_{parent_id}")
    os.makedirs(profile_dir, exist_ok=True)
    _kill_stale_chrome(profile_dir)
    _cleanup_profile_lock(profile_dir)

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=BROWSER_HEADLESS,
        slow_mo=BROWSER_SLOW_MO,
        channel=BROWSER_CHANNEL,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
        ],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page


async def launch_member_context(playwright, member_id):
    """
    为指定成员启动独立 Chrome Profile 的持久化浏览器上下文。

    返回 (context, page) 元组。调用方负责关闭 context。
    """
    profile_dir = os.path.join(BROWSER_USER_DATA_DIR, f"member_{member_id}")
    os.makedirs(profile_dir, exist_ok=True)
    _kill_stale_chrome(profile_dir)
    _cleanup_profile_lock(profile_dir)

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=BROWSER_HEADLESS,
        slow_mo=BROWSER_SLOW_MO,
        channel=BROWSER_CHANNEL,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
        ],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page
