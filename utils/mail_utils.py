#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lacus-Log主播管理系统 - 邮件发送工具

提供统一的邮件发送功能，支持HTML和纯文本格式
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import html2text
import markdown
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_local_time

load_dotenv()

logger = get_logger('mail')

SMTP_SERVER = os.getenv('SES_SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SES_SMTP_PORT', '587'))
SMTP_USER = os.getenv('SES_SMTP_USER')  # SMTP服务器登录用户名
SMTP_PASSWORD = os.getenv('SES_SMTP_PASSWORD')  # SMTP服务器登录密码
SENDER_EMAIL = os.getenv('SENDER_EMAIL')  # 发件人邮箱（From字段）
MAIL_DEBUG = os.getenv('MAIL_DEBUG', 'false').lower() == 'true'


def _apply_inline_table_styles(html: str) -> str:
    """
    为<table>/<th>/<td>添加内联样式以增强邮件客户端的表格显示效果。
    使用HTML解析器安全地内联样式，避免正则误改。

    注意：Markdown 渲染可能会在 th/td 上预先设置 `text-align` 样式，
    这里在保留原有 `style` 的基础上按需补齐缺失的边框/内边距/背景等。
    """
    if not html:
        return html

    soup = BeautifulSoup(html, "html.parser")

    table_style = "border-collapse: collapse; width: 100%; margin: 10px 0;"
    th_defaults = {
        "border": "1px solid #ddd",
        "padding": "8px",
        "text-align": "left",
        "vertical-align": "top",
        "background": "#f7f7f7",
    }
    td_defaults = {
        "border": "1px solid #ddd",
        "padding": "8px",
        "text-align": "left",
        "vertical-align": "top",
    }

    def _merge_style(existing: str, defaults: dict) -> str:
        style_map = {}
        if existing:
            parts = [p.strip() for p in existing.split(';') if p.strip()]
            for p in parts:
                if ':' in p:
                    k, v = p.split(':', 1)
                    style_map[k.strip().lower()] = v.strip()

        for k, v in defaults.items():
            if k not in style_map:
                style_map[k] = v

        ordered_keys = list(defaults.keys()) + [k for k in style_map.keys() if k not in defaults]
        return "; ".join(f"{k}: {style_map[k]}" for k in ordered_keys if k in style_map)

    for table in soup.find_all("table"):
        if not table.get("style"):
            table["style"] = table_style
        for th in table.find_all("th"):
            th["style"] = _merge_style(th.get("style", ""), th_defaults)
        for td in table.find_all("td"):
            td["style"] = _merge_style(td.get("style", ""), td_defaults)

    return str(soup)


def _create_html_template(content: str) -> str:
    """
    创建HTML邮件模板
    
    Args:
        content: 邮件正文内容
        
    Returns:
        完整的HTML邮件内容
    """
    send_time = get_current_local_time().strftime('%Y-%m-%d %H:%M:%S')

    content = _apply_inline_table_styles(content)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Lacus-Log 拉克斯日志</title>
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                🎯 Lacus-Log 拉克斯日志
            </h2>
            
            {content}
            
            <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
            
            <p style="font-size: 12px; color: #666; text-align: center;">
                此邮件由Lacus-Log 拉克斯日志自动发送<br>
                发送时间：{send_time}
            </p>
        </div>
    </body>
    </html>
    """


def _create_text_template(content: str) -> str:
    """
    创建纯文本邮件模板
    
    Args:
        content: 邮件正文内容
        
    Returns:
        完整的纯文本邮件内容
    """
    send_time = get_current_local_time().strftime('%Y-%m-%d %H:%M:%S')

    return f"""
Lacus-Log主播管理系统

{content}

---
此邮件由Lacus-Log主播管理系统自动发送
发送时间：{send_time}
    """


def send_email(recipients: List[str], subject: str, content: str, html_content: Optional[str] = None) -> bool:
    """
    发送邮件
    
    Args:
        recipients: 收件人邮箱列表
        subject: 邮件主题
        content: 纯文本邮件正文内容
        html_content: HTML邮件正文内容（可选，如果不提供则使用content）
        
    Returns:
        发送成功返回True，失败返回False
    """
    try:
        if not SMTP_USER:
            logger.error("SMTP_USER环境变量未配置")
            return False

        if not SMTP_PASSWORD:
            logger.error("SMTP_PASSWORD环境变量未配置")
            return False

        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_EMAIL
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject

        text_body = _create_text_template(content)
        text_part = MIMEText(text_body, 'plain', 'utf-8')
        msg.attach(text_part)

        if html_content:
            html_body = _create_html_template(html_content)
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)
        else:
            html_body = _create_html_template(content)
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)

        if MAIL_DEBUG:
            try:
                os.makedirs('log/mail', exist_ok=True)
                ts = get_current_local_time().strftime('%Y%m%d_%H%M%S')
                safe_subject = ''.join(ch if ch.isalnum() else '_' for ch in subject)[:60]
                filename = os.path.join('log', 'mail', f"{safe_subject}_{ts}.html")
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(html_body)
                logger.info("[DEBUG] 邮件未发送（MAIL_DEBUG=true），已落盘: %s; 收件人: %s", filename, ', '.join(recipients))
                return True
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("[DEBUG] 邮件落盘失败: %s", str(exc))
                return False

        context = ssl.create_default_context()

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)  # 启用TLS加密
            server.login(SMTP_USER, SMTP_PASSWORD)

            text = msg.as_string()
            server.sendmail(SENDER_EMAIL, recipients, text)

        logger.info(f"邮件发送成功！收件人: {', '.join(recipients)}, 主题: {subject}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP认证失败: {str(e)}")
        return False

    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"收件人被拒绝: {str(e)}")
        return False

    except smtplib.SMTPServerDisconnected as e:
        logger.error(f"SMTP服务器连接断开: {str(e)}")
        return False

    except Exception as e:
        logger.error(f"发送邮件时发生未知错误: {str(e)}")
        return False


def send_email_md(recipients: List[str], subject: str, md_content: str) -> bool:
    """
    使用Markdown内容发送邮件。

    会将Markdown渲染为HTML，并同时生成纯文本内容，随后复用现有的send_email进行发送。

    Args:
        recipients: 收件人邮箱列表
        subject: 邮件主题
        md_content: Markdown格式的邮件正文

    Returns:
        发送成功返回True，失败返回False
    """
    try:
        rendered_html_body = markdown.markdown(
            md_content or "",
            extensions=[
                'extra',  # 支持表格、定义列表等
                'sane_lists',
                'smarty'
            ])

        plain_text_body = html2text.html2text(rendered_html_body)

        return send_email(recipients=recipients, subject=subject, content=plain_text_body, html_content=rendered_html_body)
    except Exception as e:
        logger.error(f"Markdown邮件处理失败: {str(e)}")
        return False


def __send_test_email(recipient: str) -> bool:
    """
    发送测试邮件
    
    Args:
        recipient: 收件人邮箱
        
    Returns:
        发送成功返回True，失败返回False
    """
    subject = "Lacus-Log主播管理系统 - 服务开通确认"

    content = """
尊敬的用户，

您好！这是一封来自Lacus-Log主播管理系统的邮件。

✅ 服务开通确认
我们确认您已经成功开通了Lacus-Log主播管理系统的服务。

这是一封测试邮件，目的是确保您能够正常收到来自系统的通知邮件。

📋 系统功能概览
- 主播管理和招募
- 通告计划和记录
- 开播地点管理
- 分成管理
- 作战日报统计

如果您有任何问题或需要技术支持，请随时联系我们的技术团队。
    """

    html_content = """
    <p>尊敬的用户，</p>
    
    <p>您好！这是一封来自<strong>Lacus-Log主播管理系统</strong>的邮件。</p>
    
    <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #3498db; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #2c3e50;">✅ 服务开通确认</h3>
        <p style="margin-bottom: 0;">我们确认您已经成功开通了Lacus-Log主播管理系统的服务。</p>
    </div>
    
    <p>这是一封<strong>测试邮件</strong>，目的是确保您能够正常收到来自系统的通知邮件。</p>
    
    <div style="background-color: #e8f5e8; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <h4 style="margin-top: 0; color: #27ae60;">📋 系统功能概览</h4>
        <ul style="margin-bottom: 0;">
            <li>主播管理和招募</li>
            <li>通告计划和记录</li>
            <li>开播地点管理</li>
            <li>分成管理</li>
            <li>作战日报统计</li>
        </ul>
    </div>
    
    <p>如果您有任何问题或需要技术支持，请随时联系我们的技术团队。</p>
    """

    return send_email([recipient], subject, content, html_content)


def __send_test_email_by_md(recipient: str) -> bool:
    """
    使用Markdown内容发送测试邮件。

    Args:
        recipient: 收件人邮箱

    Returns:
        发送成功返回True，失败返回False
    """
    subject = "Lacus-Log主播管理系统 - Markdown 测试邮件"
    md_content = ("# 尊敬的用户\n\n"
                  "您好！这是一封来自 **Lacus-Log主播管理系统** 的 _Markdown_ 测试邮件。\n\n"
                  "## ✅ 服务开通确认\n"
                  "我们确认您已经成功开通了系统服务。\n\n"
                  "## 📋 系统功能概览\n"
                  "- 主播管理和招募\n"
                  "- 通告计划和记录\n"
                  "- 开播地点管理\n"
                  "- 分成管理\n"
                  "- 作战日报统计\n\n"
                  "## 📊 表格展示（Markdown）\n\n"
                  "| 模块 | 功能 | 状态 |\n"
                  "| --- | --- | --- |\n"
                  "| 主播管理 | 招募与档案 | 已上线 |\n"
                  "| 通告计划 | 日历与冲突检查 | 已上线 |\n"
                  "| 开播记录 | 日报与统计 | 已上线 |\n"
                  "| 分成管理 | 分成计算与变更记录 | 已上线 |\n\n"
                  "> 如有任何问题，请联系技术团队。\n")

    return send_email_md([recipient], subject, md_content)


def main():
    """
    CLI接口，用于本地调试发送测试邮件
    """
    print("🚀 启动Lacus-Log主播管理系统邮件发送工具")
    print("=" * 50)

    if not SMTP_USER:
        print("⚠️  请先在.env文件中配置SMTP信息！")
        print("需要配置的环境变量：")
        print("- SES_SMTP_SERVER")
        print("- SES_SMTP_PORT")
        print("- SES_SMTP_USER")
        print("- SES_SMTP_PASSWORD")
        print("- SENDER_EMAIL")
        return

    if not SMTP_PASSWORD:
        print("⚠️  请配置正确的SMTP密码！")
        print("注意：如果使用Gmail，请使用应用专用密码而不是普通密码")
        return

    if not SENDER_EMAIL:
        print("⚠️  请配置发件人邮箱！")
        print("需要在.env文件中配置SENDER_EMAIL环境变量")
        return

    try:
        recipient = input("请输入收件人邮箱地址: ").strip()
        if not recipient:
            print("❌ 收件人邮箱不能为空！")
            return

        if "@" not in recipient or "." not in recipient.split("@")[-1]:
            print("❌ 邮箱格式不正确！")
            return

    except KeyboardInterrupt:
        print("\n\n👋 用户取消操作")
        return
    except Exception as e:
        print(f"❌ 输入错误: {str(e)}")
        return

    print("\n请选择测试方式：")
    print("1) 普通模板（纯文本+HTML）")
    print("2) Markdown（md 渲染为HTML，同时生成纯文本）")
    choice = input("请输入选项数字(默认为1): ").strip() or "1"

    if choice not in {"1", "2"}:
        print("❌ 非法选项！仅支持 1 或 2")
        return

    print(f"\n📧 准备发送测试邮件到: {recipient}")
    if choice == "2":
        success = __send_test_email_by_md(recipient)
    else:
        success = __send_test_email(recipient)

    if success:
        print("✅ 邮件发送成功！")
        print(f"📧 收件人: {recipient}")
        print("📝 主题: Lacus-Log主播管理系统 - 服务开通确认")
        print(f"📤 发件人: {SENDER_EMAIL}")
        print("\n🎉 邮件发送完成！")
    else:
        print("\n💥 邮件发送失败，请检查配置和网络连接。")


if __name__ == "__main__":
    main()
