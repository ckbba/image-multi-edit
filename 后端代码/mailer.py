"""Small SMTP adapter for account verification and password recovery."""
import html
import smtplib
from email.message import EmailMessage

import config


def send(to_email, subject, heading, body, action_label, action_url):
    if not config.mail_ready():
        raise RuntimeError('邮件服务尚未配置')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = f'{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>'
    message['To'] = to_email
    message.set_content(f'{heading}\n\n{body}\n\n{action_label}: {action_url}\n\n如果不是你本人操作，请忽略这封邮件。')
    message.add_alternative(f'''<!doctype html><html lang="zh-CN"><body style="margin:0;background:#f6f5f8;font-family:Arial,'Microsoft YaHei',sans-serif;color:#342e3b"><div style="max-width:560px;margin:36px auto;padding:32px;background:white;border-radius:16px"><div style="font-size:24px;color:#6f59d9">↗ 拾影</div><h1 style="font-size:22px">{html.escape(heading)}</h1><p style="line-height:1.8;color:#6f6774">{html.escape(body)}</p><p style="margin:28px 0"><a href="{html.escape(action_url, quote=True)}" style="display:inline-block;padding:12px 20px;border-radius:9px;background:#6f59d9;color:white;text-decoration:none">{html.escape(action_label)}</a></p><p style="font-size:12px;line-height:1.7;color:#99919f">如果按钮无法打开，请复制以下地址：<br>{html.escape(action_url)}<br><br>如果不是你本人操作，请忽略这封邮件。</p></div></body></html>''', subtype='html')
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as client:
        client.ehlo()
        if config.SMTP_USE_TLS:
            client.starttls()
            client.ehlo()
        client.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        client.send_message(message)


def send_code(to_email, subject, heading, code, body):
    if not config.mail_ready():
        raise RuntimeError('邮件服务尚未配置')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = f'{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>'
    message['To'] = to_email
    message.set_content(f'{heading}\n\n你的验证码是：{code}\n\n{body}\n\n如果不是你本人操作，请忽略这封邮件。')
    message.add_alternative(f'''<!doctype html><html lang="zh-CN"><body style="margin:0;background:#f6f5f8;font-family:Arial,'Microsoft YaHei',sans-serif;color:#342e3b"><div style="max-width:560px;margin:36px auto;padding:32px;background:white;border-radius:16px"><div style="font-size:24px;color:#6f59d9">↗ 拾影</div><h1 style="font-size:22px">{html.escape(heading)}</h1><p style="line-height:1.8;color:#6f6774">{html.escape(body)}</p><div style="margin:28px 0;padding:16px;border-radius:10px;background:#f3f0ff;text-align:center;font-size:32px;font-weight:700;letter-spacing:8px;color:#6f59d9">{html.escape(code)}</div><p style="font-size:12px;line-height:1.7;color:#99919f">如果不是你本人操作，请忽略这封邮件。</p></div></body></html>''', subtype='html')
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as client:
        client.ehlo()
        if config.SMTP_USE_TLS:
            client.starttls()
            client.ehlo()
        client.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        client.send_message(message)

