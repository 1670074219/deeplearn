import yaml
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def load_config():
    """加载配置文件"""
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置文件失败：{str(e)}")
        return None

def test_email():
    """测试邮件发送功能"""
    config = load_config()
    if not config:
        return
    
    try:
        print("=== 开始测试邮件功能 ===")
        
        # 获取邮件配置
        email_settings = config['email_settings']
        print(f"\n当前邮件配置：")
        print(f"SMTP服务器：{email_settings['smtp_server']}")
        print(f"SMTP端口：{email_settings['smtp_port']}")
        print(f"发件人邮箱：{email_settings['sender_email']}")
        
        # 创建测试邮件
        msg = MIMEMultipart()
        msg['From'] = email_settings['sender_email']
        msg['To'] = email_settings['sender_email']  # 发送给自己进行测试
        msg['Subject'] = "实验室服务器管理系统 - 邮件功能测试"
        
        body = """
这是一封测试邮件。

如果您收到这封邮件，说明邮件功能配置正确。

此邮件为系统自动发送，请勿回复。
"""
        msg.attach(MIMEText(body, 'plain'))
        
        print("\n正在连接SMTP服务器...")
        server = smtplib.SMTP(email_settings['smtp_server'], email_settings['smtp_port'])
        server.starttls()
        
        print("正在登录...")
        server.login(email_settings['sender_email'], email_settings['sender_password'])
        
        print("正在发送测试邮件...")
        server.send_message(msg)
        server.quit()
        
        print("\n测试邮件发送成功！")
        print(f"请检查邮箱 {email_settings['sender_email']} 是否收到测试邮件")
        
    except Exception as e:
        print(f"\n发送测试邮件失败：{str(e)}")
        print("\n可能的原因：")
        print("1. SMTP服务器配置错误")
        print("2. 邮箱密码（授权码）错误")
        print("3. 网络连接问题")
        print("4. 邮箱安全设置限制")

if __name__ == "__main__":
    test_email() 