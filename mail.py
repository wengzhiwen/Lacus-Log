#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lacus-Log主播管理系统 - 邮件发送脚本

使用SMTP服务发送系统通知邮件
"""

import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('log/mail.log', encoding='utf-8'),
                              logging.StreamHandler()])
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# SMTP 配置信息 - 从环境变量读取
SMTP_SERVER = os.getenv('SES_SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SES_SMTP_PORT', '587'))
SMTP_USER = os.getenv('SES_SMTP_USER')  # SMTP服务器登录用户名
SMTP_PASSWORD = os.getenv('SES_SMTP_PASSWORD')  # SMTP服务器登录密码
SENDER_EMAIL = "report@tpnet.cc"  # 发件人邮箱（From字段）
RECIPIENT_EMAIL = "wengzhiwen@gmail.com"  # 收件人邮箱


def send_email():
    """
    使用SMTP发送系统通知邮件
    """
    try:
        # 创建邮件对象
        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = "Lacus-Log主播管理系统 - 服务开通确认"

        # 邮件内容
        subject = "Lacus-Log主播管理系统 - 服务开通确认"

        # HTML格式的邮件内容
        html_body = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Lacus-Log主播管理系统</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                    🎯 Lacus-Log主播管理系统
                </h2>
                
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
                        <li>机师管理和征召</li>
                        <li>作战计划和记录</li>
                        <li>战斗区域管理</li>
                        <li>分成管理</li>
                        <li>作战日报统计</li>
                    </ul>
                </div>
                
                <p>如果您有任何问题或需要技术支持，请随时联系我们的技术团队。</p>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                
                <p style="font-size: 12px; color: #666; text-align: center;">
                    此邮件由Lacus-Log主播管理系统自动发送<br>
                    发送时间：{send_time}
                </p>
            </div>
        </body>
        </html>
        """.format(send_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 纯文本格式的邮件内容
        text_body = """
Lacus-Log主播管理系统 - 服务开通确认

尊敬的用户，您好！

这是一封来自Lacus-Log主播管理系统的邮件。

✅ 服务开通确认
我们确认您已经成功开通了Lacus-Log主播管理系统的服务。

这是一封测试邮件，目的是确保您能够正常收到来自系统的通知邮件。

📋 系统功能概览
- 机师管理和征召
- 作战计划和记录  
- 战斗区域管理
- 分成管理
- 作战日报统计

如果您有任何问题或需要技术支持，请随时联系我们的技术团队。

---
此邮件由Lacus-Log主播管理系统自动发送
发送时间：{send_time}
        """.format(send_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 创建邮件部分
        text_part = MIMEText(text_body, 'plain', 'utf-8')
        html_part = MIMEText(html_body, 'html', 'utf-8')

        # 添加邮件部分
        msg.attach(text_part)
        msg.attach(html_part)

        # 创建SSL上下文
        context = ssl.create_default_context()

        # 连接SMTP服务器并发送邮件
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)  # 启用TLS加密
            server.login(SMTP_USER, SMTP_PASSWORD)

            # 发送邮件
            text = msg.as_string()
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, text)

        logger.info("邮件发送成功！")
        print("✅ 邮件发送成功！")
        print(f"📧 收件人: {RECIPIENT_EMAIL}")
        print(f"📝 主题: {subject}")
        print(f"📤 发件人: {SENDER_EMAIL}")

        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP认证失败: {str(e)}")
        print("❌ 邮件发送失败: SMTP认证失败，请检查邮箱和密码")
        return False

    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"收件人被拒绝: {str(e)}")
        print("❌ 邮件发送失败: 收件人邮箱被拒绝")
        return False

    except smtplib.SMTPServerDisconnected as e:
        logger.error(f"SMTP服务器连接断开: {str(e)}")
        print("❌ 邮件发送失败: SMTP服务器连接断开")
        return False

    except Exception as e:
        logger.error(f"发送邮件时发生未知错误: {str(e)}")
        print(f"❌ 发送邮件时发生错误: {str(e)}")
        return False


def main():
    """
    主函数
    """
    print("🚀 启动Lacus-Log主播管理系统邮件发送脚本")
    print("=" * 50)

    # 检查配置
    if not SMTP_USER:
        print("⚠️  请先在.env文件中配置SMTP信息！")
        print("需要配置的环境变量：")
        print("- SES_SMTP_SERVER")
        print("- SES_SMTP_PORT")
        print("- SES_SMTP_USER")
        print("- SES_SMTP_PASSWORD")
        return

    if not SMTP_PASSWORD:
        print("⚠️  请配置正确的SMTP密码！")
        print("注意：如果使用Gmail，请使用应用专用密码而不是普通密码")
        return

    # 发送邮件
    success = send_email()

    if success:
        print("\n🎉 邮件发送完成！")
    else:
        print("\n💥 邮件发送失败，请检查配置和网络连接。")


if __name__ == "__main__":
    main()
