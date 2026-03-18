"""Google 家庭组管理自动化

支持：查看成员、邀请成员、踢出成员、打开家庭组页面
所有操作复用家长独立 Chrome Profile，确保已登录状态
"""

import logging

from playwright.async_api import async_playwright, Page
from rich.console import Console

from automation.browser import launch_parent_context
from automation.google_login import google_login
from db.database import get_session
from db.models import Parent
from utils.crypto import decrypt_safe

console = Console()
logger = logging.getLogger(__name__)

FAMILY_DETAILS_URL = "https://myaccount.google.com/family/details"
FAMILY_INVITE_URL = "https://myaccount.google.com/family/invite/send"
FAMILY_SETTINGS_URL = "https://myaccount.google.com/family"


async def _login_parent(playwright, parent_id):
    """启动家长浏览器并确保已登录"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            raise ValueError(f"家长 ID {parent_id} 不存在")
        email = parent.email
        password = decrypt_safe(parent.password) if parent.password else ""
        totp = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

    if not password:
        raise ValueError(f"家长 {email} 未设置密码，无法自动登录")

    context, page = await launch_parent_context(playwright, parent_id)
    await google_login(page, email, password, totp)
    return context, page


async def open_family_page(parent_id: int, page_type: str = "settings") -> bool:
    """打开家庭组页面，浏览器保持打开等待用户手动关闭"""
    url_map = {
        "members": FAMILY_DETAILS_URL,
        "invite": FAMILY_INVITE_URL,
        "settings": FAMILY_SETTINGS_URL,
    }
    url = url_map.get(page_type, FAMILY_SETTINGS_URL)
    console.print(f"[cyan]打开家庭组页面: {page_type} -> {url}[/cyan]")

    async with async_playwright() as p:
        context, page = await _login_parent(p, parent_id)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        console.print("[green]家庭组页面已打开，等待用户关闭浏览器[/green]")
        await context.wait_for_event("close", timeout=0)

    return True


async def invite_family_member(parent_id: int, invite_email: str) -> bool:
    """自动邀请邮箱加入家庭组"""
    console.print(f"[cyan]邀请成员加入家庭组: {invite_email}[/cyan]")

    async with async_playwright() as p:
        context, page = await _login_parent(p, parent_id)
        try:
            await page.goto(FAMILY_INVITE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            email_input = page.locator(
                'input[type="email"], input[aria-label*="mail"], '
                'input[placeholder*="mail"], input[placeholder*="Mail"]'
            ).first

            try:
                await email_input.wait_for(state="visible", timeout=10000)
                await email_input.fill(invite_email)
                console.print(f"[dim]已填入邮箱: {invite_email}[/dim]")
            except Exception:
                inputs = page.locator("input[type='text'], input[type='email'], input:not([type])")
                filled = False
                for i in range(await inputs.count()):
                    inp = inputs.nth(i)
                    if await inp.is_visible():
                        await inp.fill(invite_email)
                        filled = True
                        break
                if not filled:
                    logger.warning("未找到邮箱输入框")
                    return False

            await page.wait_for_timeout(1000)

            send_texts = [
                "Send", "Invite", "Add", "发送", "邀请", "添加",
            ]
            clicked = False
            for text in send_texts:
                btn = page.locator(f'button:has-text("{text}")').first
                try:
                    if await btn.is_visible():
                        await btn.click()
                        clicked = True
                        console.print(f"[dim]已点击: {text}[/dim]")
                        break
                except Exception:
                    continue

            if not clicked:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(3000)
            console.print(f"[green]邀请发送完成: {invite_email}[/green]")
            return True
        finally:
            await context.close()


async def kick_family_member(parent_id: int, member_email: str) -> bool:
    """踢出家庭组成员（打开成员详情页，自动操作移除）"""
    console.print(f"[cyan]踢出家庭组成员: {member_email}[/cyan]")

    async with async_playwright() as p:
        context, page = await _login_parent(p, parent_id)
        try:
            await page.goto(FAMILY_DETAILS_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            target = page.locator(f'text="{member_email}"').first
            try:
                await target.wait_for(state="visible", timeout=10000)
            except Exception:
                logger.warning("未在家庭组页面找到成员: %s", member_email)
                console.print(f"[red]未找到成员: {member_email}[/red]")
                return False

            await target.click()
            await page.wait_for_timeout(2000)

            remove_texts = [
                "Remove member", "Remove from family group",
                "Remove", "移除成员", "从家庭群组中移除", "移除",
            ]
            clicked = False
            for text in remove_texts:
                btn = page.locator(
                    f'button:has-text("{text}"), [role="menuitem"]:has-text("{text}"), '
                    f'a:has-text("{text}")'
                ).first
                try:
                    if await btn.is_visible():
                        await btn.click()
                        clicked = True
                        console.print(f"[dim]已点击移除: {text}[/dim]")
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("未找到移除按钮")
                return False

            await page.wait_for_timeout(1000)

            confirm_texts = ["Remove", "Confirm", "Yes", "OK", "确认", "移除"]
            for text in confirm_texts:
                btn = page.locator(f'button:has-text("{text}")').first
                try:
                    if await btn.is_visible():
                        await btn.click()
                        console.print(f"[dim]已确认移除: {text}[/dim]")
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(3000)
            console.print(f"[green]已踢出成员: {member_email}[/green]")
            return True
        finally:
            await context.close()
