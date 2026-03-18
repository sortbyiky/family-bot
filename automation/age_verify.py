import logging

from playwright.async_api import async_playwright
from rich.console import Console

from automation.browser import launch_member_context
from automation.google_login import google_login
from db.database import get_session
from db.models import Member
from utils.crypto import decrypt_safe

console = Console()
logger = logging.getLogger(__name__)

AGE_VERIFY_URL = "https://myaccount.google.com/age-verification?utm_source=p0"


async def age_verify_member(member_id: int) -> dict:
    """
    登录成员 Google 账号，跳转到年龄认证页面，保持浏览器打开等待手动操作。
    """
    with get_session() as session:
        member = session.get(Member, member_id)
        if not member:
            return {"success": False, "message": f"成员 ID {member_id} 不存在"}
        email = member.email
        password = decrypt_safe(member.password)
        totp_secret = decrypt_safe(member.totp_secret) if member.totp_secret else ""

    console.print(f"[cyan]年龄认证: 登录 {email} 并跳转认证页面[/cyan]")

    async with async_playwright() as p:
        context, page = await launch_member_context(p, member_id)

        login_ok = await google_login(page, email, password, totp_secret)
        if not login_ok:
            await context.close()
            return {"success": False, "message": "Google 登录失败"}

        console.print(f"[cyan]登录成功，跳转年龄认证页面: {email}[/cyan]")
        await page.goto(AGE_VERIFY_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        console.print(f"[green]浏览器已就绪，请手动完成年龄认证: {email}[/green]")
        await context.wait_for_event("close", timeout=0)

    return {"success": True, "message": "浏览器已关闭"}
