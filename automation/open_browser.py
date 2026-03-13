import logging

from playwright.async_api import async_playwright
from rich.console import Console

from automation.browser import launch_member_context, launch_parent_context
from automation.google_login import google_login
from db.database import get_session
from db.models import Member, Parent
from utils.crypto import decrypt_safe

console = Console()
logger = logging.getLogger(__name__)


async def open_browser_for_member(member_id: int):
    """启动成员独立 Chrome，自动登录 Google，等待用户手动关闭浏览器"""
    with get_session() as session:
        member = session.get(Member, member_id)
        if not member:
            console.print(f"[red]成员 ID {member_id} 不存在[/red]")
            return False
        email = member.email
        password = decrypt_safe(member.password)
        totp_secret = decrypt_safe(member.totp_secret) if member.totp_secret else ""

    console.print(f"[cyan]打开浏览器: {email}[/cyan]")

    async with async_playwright() as p:
        context, page = await launch_member_context(p, member_id)
        await google_login(page, email, password, totp_secret)
        console.print(f"[green]浏览器已就绪，等待用户关闭: {email}[/green]")
        await context.wait_for_event("close", timeout=0)

    return True


async def open_browser_for_parent(parent_id: int):
    """启动家长独立 Chrome，自动登录 Google，等待用户手动关闭浏览器"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            console.print(f"[red]家长 ID {parent_id} 不存在[/red]")
            return False
        email = parent.email
        password = decrypt_safe(parent.password) if parent.password else ""
        totp_secret = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

    if not password:
        console.print(f"[red]家长 {email} 未设置密码[/red]")
        return False

    console.print(f"[cyan]打开家长浏览器: {email}[/cyan]")

    async with async_playwright() as p:
        context, page = await launch_parent_context(p, parent_id)
        await google_login(page, email, password, totp_secret)
        console.print(f"[green]家长浏览器已就绪，等待用户关闭: {email}[/green]")
        await context.wait_for_event("close", timeout=0)

    return True
