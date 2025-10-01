#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 pytest 的邮件发送工具测试：在 MAIL_DEBUG 模式下验证渲染与落盘。
"""

import glob
import os
import time


def _prepare_env():
    os.environ['MAIL_DEBUG'] = 'true'
    os.environ['SES_SMTP_USER'] = os.environ.get('SES_SMTP_USER', 'user@example.com')
    os.environ['SES_SMTP_PASSWORD'] = os.environ.get('SES_SMTP_PASSWORD', 'secret')
    os.environ['SENDER_EMAIL'] = os.environ.get('SENDER_EMAIL', 'sender@example.com')

    log_mail_dir = os.path.join('log', 'mail')
    os.makedirs(log_mail_dir, exist_ok=True)
    baseline = set(glob.glob(os.path.join(log_mail_dir, '*.html')))
    return log_mail_dir, baseline


def _get_new_filepaths(log_mail_dir: str, baseline: set[str]) -> list[str]:
    time.sleep(0.05)  # 轻微等待，避免与时间戳粒度冲突
    current = set(glob.glob(os.path.join(log_mail_dir, '*.html')))
    return sorted(current - baseline)


def test_send_email_md_mail_debug_creates_html():
    log_mail_dir, baseline = _prepare_env()

    from utils.mail_utils import send_email_md

    md = ("# 标题\n\n"
          "| A | B | C |\n"
          "|---|---|---|\n"
          "| 1 | 2 | 3 |\n")
    ok = send_email_md(["nobody@example.com"], "调试-表格", md)
    assert ok is True

    new_files = _get_new_filepaths(log_mail_dir, baseline)
    assert len(new_files) >= 1

    with open(new_files[-1], 'r', encoding='utf-8') as f:
        html = f.read()
    assert '<table' in html and 'style="border-collapse' in html
    assert '<th' in html and '1px solid' in html
    assert '<td' in html and 'padding: 8px' in html


def test_send_email_mail_debug_creates_html():
    log_mail_dir, baseline = _prepare_env()

    from utils.mail_utils import send_email

    ok = send_email(["nobody@example.com"], "调试-普通", "纯文本内容", "<p>HTML 内容</p>")
    assert ok is True

    new_files = _get_new_filepaths(log_mail_dir, baseline)
    assert len(new_files) >= 1

    with open(new_files[-1], 'r', encoding='utf-8') as f:
        html = f.read()
    assert '<p>HTML 内容</p>' in html
