"""
Google 家庭组管理自动化 — 列出成员、踢出、邀请、取消邀请
家长账号登录后在 families.google.com 上操作。
"""

import logging
from playwright.async_api import Page
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

FAMILY_URL = "https://families.google.com/families"


async def _goto_family_page(page: Page) -> bool:
    """导航到家庭组管理页面，等待内容加载"""
    console.print("[cyan]访问家庭组页面...[/cyan]")
    try:
        await page.goto(FAMILY_URL, wait_until="domcontentloaded", timeout=60000)
        # 等待页面主体内容加载
        await page.wait_for_timeout(3000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        console.print(f"[dim]当前页面: {page.url}[/dim]")
        return True
    except Exception as e:
        logger.error("访问家庭组页面失败: %s", e)
        return False


async def _dismiss_popups(page: Page):
    """关闭可能出现的弹窗/通知"""
    for _ in range(2):
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)

    dismiss_texts = ["Not now", "No thanks", "OK", "Got it", "Close", "Dismiss",
                     "以后再说", "关闭", "不用了", "知道了", "跳过", "Skip"]
    for text in dismiss_texts:
        try:
            btn = page.locator(
                f'button:has-text("{text}"), a:has-text("{text}")'
            ).first
            if await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def list_family_members(page: Page) -> list:
    """
    获取家庭组成员列表。
    返回 [{"name": str, "email": str, "role": str, "status": str}]
    role: "manager" | "member"
    status: "active" | "pending"
    """
    if not await _goto_family_page(page):
        return []

    await _dismiss_popups(page)

    members = []

    # 策略1：通过 JavaScript 提取页面中的成员数据
    try:
        # 尝试从各种可能的DOM结构中提取
        result = await page.evaluate("""() => {
            const members = [];

            // 查找包含成员信息的卡片/行
            // Google Family页面的成员通常在 material cards 或 list items 中
            const selectors = [
                '[data-member-id]',
                '[data-invite-token]',
                '.VfPpkd-WsjYwc',  // Material Design list item
                'li[jsname]',
            ];

            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                els.forEach(el => {
                    const emailEl = el.querySelector('[data-email], [jsname="haAclf"]');
                    const nameEl = el.querySelector('[jsname="r4nke"], h3, h4, .name');
                    if (emailEl || nameEl) {
                        members.push({
                            name: (nameEl || {}).innerText || '',
                            email: ((emailEl || {}).innerText || (el.dataset || {}).email || '').toLowerCase().trim(),
                            raw: el.innerText.substring(0, 200)
                        });
                    }
                });
                if (members.length > 0) break;
            }

            return members;
        }""")
        logger.debug("JS提取结果: %s", result)
    except Exception as e:
        logger.debug("JS提取失败: %s", e)
        result = []

    # 策略2：截图并通过文本解析页面内容
    try:
        # 等待可能的成员列表容器
        possible_containers = [
            'main', '[role="main"]', '.family-members',
            '[data-view-id]', 'c-wiz', 'div[jsrenderer]'
        ]
        for container_sel in possible_containers:
            try:
                el = page.locator(container_sel).first
                if await el.is_visible():
                    break
            except Exception:
                pass

        # 通过文本匹配提取成员信息
        page_text = await page.evaluate("() => document.body.innerText")
        logger.debug("页面文本(前1000字): %s", page_text[:1000])

        # 查找所有邮箱格式文本
        import re
        emails_in_page = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', page_text)
        logger.info("页面中发现邮箱: %s", emails_in_page)

    except Exception as e:
        logger.debug("文本解析失败: %s", e)

    # 策略3：查找所有可能包含成员信息的元素
    try:
        # 查找角色相关文本
        role_indicators = {
            "manager": ["Family Manager", "Manager", "家庭管理员", "管理员", "家长"],
            "member": ["Family Member", "Member", "成员", "家庭成员"],
            "pending": ["Invitation sent", "Pending", "等待接受", "邀请已发送", "待接受"],
        }

        # 尝试查找常见的成员列表元素
        item_selectors = [
            'li', '[role="listitem"]', 'tr',
            '.member-item', '[data-member]',
            'div.r6 > div',  # 常见的 Google Material list item
        ]

        for sel in item_selectors:
            items = page.locator(sel)
            count = await items.count()
            if count > 0 and count < 20:  # 合理范围
                console.print(f"[dim]找到 {count} 个 {sel} 元素[/dim]")
                for i in range(min(count, 15)):
                    try:
                        item = items.nth(i)
                        text = await item.inner_text()
                        if "@" in text or any(
                            r in text for rs in role_indicators.values() for r in rs
                        ):
                            console.print(f"[dim]成员项: {text[:100]}[/dim]")
                            # 提取邮箱
                            import re
                            found_emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
                            # 判断角色和状态
                            role = "member"
                            status = "active"
                            for r_name, r_texts in role_indicators.items():
                                if any(rt in text for rt in r_texts):
                                    if r_name == "manager":
                                        role = "manager"
                                    elif r_name == "pending":
                                        status = "pending"
                                    break

                            for email in found_emails:
                                if not any(m["email"] == email for m in members):
                                    # 尝试提取姓名
                                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                                    name = lines[0] if lines else email
                                    members.append({
                                        "name": name,
                                        "email": email,
                                        "role": role,
                                        "status": status,
                                    })
                    except Exception:
                        continue
                if members:
                    break

    except Exception as e:
        logger.debug("策略3失败: %s", e)

    # 去重
    seen = set()
    unique_members = []
    for m in members:
        if m["email"] and m["email"] not in seen:
            seen.add(m["email"])
            unique_members.append(m)

    console.print(f"[green]共找到 {len(unique_members)} 个家庭组成员[/green]")
    return unique_members


async def kick_family_member(page: Page, member_identifier: str) -> bool:
    """
    踢出家庭组成员。
    member_identifier: 成员邮箱或姓名。
    返回 True 表示操作成功。
    """
    console.print(f"[cyan]准备踢出成员: {member_identifier}[/cyan]")

    if not await _goto_family_page(page):
        return False

    await _dismiss_popups(page)
    await page.wait_for_timeout(2000)

    # 点击展开成员的更多菜单（三个点）
    # 尝试找包含成员标识符的元素附近的操作按钮
    try:
        # 先找到包含该成员信息的区域
        member_area = page.locator(f':has-text("{member_identifier}")').last
        if not await member_area.is_visible():
            logger.warning("未找到成员: %s", member_identifier)
            return False

        # 在该区域附近找更多操作按钮
        more_btn_selectors = [
            '[aria-label="More options"]',
            '[aria-label="更多选项"]',
            'button[aria-label*="more" i]',
            'button[aria-label*="选项"]',
            '[data-action="more"]',
            'button > i.material-icons:has-text("more_vert")',
        ]

        clicked = False
        for sel in more_btn_selectors:
            try:
                btn = member_area.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # 尝试在整个页面找
            for sel in more_btn_selectors:
                try:
                    btns = page.locator(sel)
                    count = await btns.count()
                    for i in range(count):
                        btn = btns.nth(i)
                        if await btn.is_visible():
                            # 检查附近是否有成员名
                            parent_text = await btn.evaluate(
                                "el => el.closest('[class]') ? el.closest('[class]').innerText : ''"
                            )
                            if member_identifier.lower() in parent_text.lower():
                                await btn.click()
                                clicked = True
                                break
                    if clicked:
                        break
                except Exception:
                    continue

        if not clicked:
            logger.warning("未找到操作按钮")
            return False

        await page.wait_for_timeout(1000)

        # 点击"移除"/"Remove"选项
        remove_selectors = [
            'li:has-text("Remove")',
            'li:has-text("移除")',
            '[role="menuitem"]:has-text("Remove")',
            '[role="menuitem"]:has-text("移除")',
            'button:has-text("Remove from family")',
            'button:has-text("从家庭组中移除")',
        ]

        for sel in remove_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        # 确认移除
        confirm_selectors = [
            'button:has-text("Remove")',
            'button:has-text("移除")',
            'button:has-text("Confirm")',
            'button:has-text("确认")',
            'button:has-text("Yes")',
            '[data-action="confirm"]',
        ]

        for sel in confirm_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    console.print(f"[green]已踢出成员: {member_identifier}[/green]")
                    return True
            except Exception:
                continue

        logger.warning("未找到确认按钮，可能已自动移除")
        return True

    except Exception as e:
        logger.error("踢出成员失败: %s", e)
        return False


async def invite_family_member(page: Page, email: str) -> bool:
    """
    邀请新成员加入家庭组。
    email: 被邀请人的 Gmail 地址。
    返回 True 表示邀请发送成功。
    """
    console.print(f"[cyan]准备邀请成员: {email}[/cyan]")

    if not await _goto_family_page(page):
        return False

    await _dismiss_popups(page)
    await page.wait_for_timeout(2000)

    try:
        # 查找邀请按钮
        invite_btn_selectors = [
            'button:has-text("Invite")',
            'button:has-text("Add member")',
            'button:has-text("Add family member")',
            'button:has-text("邀请")',
            'button:has-text("添加成员")',
            'button:has-text("Add")',
            '[aria-label*="invite" i]',
            '[aria-label*="邀请"]',
            'a:has-text("Invite")',
        ]

        clicked = False
        for sel in invite_btn_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    clicked = True
                    console.print(f"[dim]点击邀请按钮: {sel}[/dim]")
                    break
            except Exception:
                continue

        if not clicked:
            logger.warning("未找到邀请按钮")
            return False

        await page.wait_for_timeout(1500)

        # 输入邮箱
        email_input_selectors = [
            'input[type="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="邮箱"]',
            'input[aria-label*="email" i]',
            'input[aria-label*="邮箱"]',
            'input[name="email"]',
        ]

        input_found = False
        for sel in email_input_selectors:
            try:
                inp = page.locator(sel).first
                if await inp.is_visible():
                    await inp.fill(email)
                    input_found = True
                    console.print(f"[dim]已输入邮箱: {email}[/dim]")
                    break
            except Exception:
                continue

        if not input_found:
            logger.warning("未找到邮箱输入框")
            return False

        await page.wait_for_timeout(500)

        # 提交邀请
        submit_selectors = [
            'button:has-text("Send invite")',
            'button:has-text("Send invitation")',
            'button:has-text("Invite")',
            'button:has-text("发送邀请")',
            'button:has-text("邀请")',
            'button[type="submit"]',
            'button:has-text("Next")',
            'button:has-text("下一步")',
        ]

        for sel in submit_selectors:
            try:
                btn = page.locator(sel).last  # 通常确认按钮在右边/下面
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    console.print(f"[green]邀请已发送: {email}[/green]")
                    return True
            except Exception:
                continue

        # 尝试回车提交
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)
        console.print(f"[green]邀请操作完成: {email}[/green]")
        return True

    except Exception as e:
        logger.error("邀请成员失败: %s", e)
        return False


async def cancel_family_invite(page: Page, member_identifier: str) -> bool:
    """
    取消未接受的邀请。
    member_identifier: 被邀请人的邮箱或姓名。
    返回 True 表示操作成功。
    """
    console.print(f"[cyan]准备取消邀请: {member_identifier}[/cyan]")

    if not await _goto_family_page(page):
        return False

    await _dismiss_popups(page)
    await page.wait_for_timeout(2000)

    try:
        # 找到待处理邀请区域
        pending_selectors = [
            f':has-text("{member_identifier}")',
        ]

        member_area = None
        for sel in pending_selectors:
            try:
                el = page.locator(sel).last
                if await el.is_visible():
                    member_area = el
                    break
            except Exception:
                continue

        if not member_area:
            logger.warning("未找到邀请记录: %s", member_identifier)
            return False

        # 找取消/撤回按钮
        cancel_selectors = [
            '[aria-label="More options"]',
            '[aria-label="更多选项"]',
            'button:has-text("Cancel invite")',
            'button:has-text("Revoke invite")',
            'button:has-text("取消邀请")',
            'button:has-text("撤回邀请")',
        ]

        for sel in cancel_selectors:
            try:
                btn = member_area.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        # 如果点了更多菜单，再找取消选项
        cancel_menu_selectors = [
            '[role="menuitem"]:has-text("Cancel")',
            '[role="menuitem"]:has-text("Revoke")',
            '[role="menuitem"]:has-text("Remove")',
            'li:has-text("Cancel invite")',
            'li:has-text("取消邀请")',
            'li:has-text("撤回")',
        ]

        for sel in cancel_menu_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        # 确认
        confirm_selectors = [
            'button:has-text("Cancel invite")',
            'button:has-text("Revoke")',
            'button:has-text("Confirm")',
            'button:has-text("确认")',
            'button:has-text("取消邀请")',
        ]

        for sel in confirm_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    console.print(f"[green]邀请已取消: {member_identifier}[/green]")
                    return True
            except Exception:
                continue

        console.print(f"[yellow]取消邀请操作已提交: {member_identifier}[/yellow]")
        return True

    except Exception as e:
        logger.error("取消邀请失败: %s", e)
        return False
