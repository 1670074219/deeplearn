from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import paramiko
import threading
import time
import pty
import os
import select
import subprocess

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

class WebTerminal:
    def __init__(self):
        self.processes = {}
        self.fd_maps = {}
        self.input_buffers = {}  # 添加输入缓冲区
        
    def create_terminal(self, session_id):
        """创建一个伪终端并运行 Python 程序"""
        try:
            # 创建伪终端
            master_fd, slave_fd = pty.openpty()
            
            # 启动 Python 程序
            process = subprocess.Popen(
                ["python3", "main.py"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                text=True
            )
            
            # 保存进程和文件描述符
            self.processes[session_id] = process
            self.fd_maps[session_id] = (master_fd, slave_fd)
            self.input_buffers[session_id] = ""  # 初始化输入缓冲区
            
            return True
            
        except Exception as e:
            print(f"创建终端失败: {str(e)}")
            return False

    def read_terminal(self, session_id):
        """读取终端输出"""
        if session_id not in self.fd_maps:
            return
            
        master_fd = self.fd_maps[session_id][0]
        
        while True:
            try:
                r, w, e = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    data = os.read(master_fd, 1024).decode('utf-8', 'ignore')
                    if data:
                        # 检查是否是回显的输入
                        if session_id in self.input_buffers:
                            input_buffer = self.input_buffers[session_id]
                            if input_buffer and data.startswith(input_buffer):
                                # 跳过回显的输入
                                data = data[len(input_buffer):]
                                self.input_buffers[session_id] = ""
                        
                        if data:  # 如果还有剩余数据
                            socketio.emit('terminal_output', {'data': data}, room=session_id)
                    else:
                        break
            except Exception as e:
                print(f"读取终端输出错误: {str(e)}")
                break

    def write_terminal(self, session_id, data):
        """向终端写入数据"""
        if session_id not in self.fd_maps:
            return
            
        master_fd = self.fd_maps[session_id][0]
        try:
            # 保存输入到缓冲区
            if data.get('input', '').strip():
                self.input_buffers[session_id] = data['input'].strip()
            
            os.write(master_fd, data['input'].encode())
        except Exception as e:
            print(f"写入终端错误: {str(e)}")

    def cleanup(self, session_id):
        """清理终端会话"""
        if session_id in self.processes:
            try:
                self.processes[session_id].terminate()
                del self.processes[session_id]
            except:
                pass
                
        if session_id in self.fd_maps:
            try:
                os.close(self.fd_maps[session_id][0])
                os.close(self.fd_maps[session_id][1])
                del self.fd_maps[session_id]
            except:
                pass
                
        if session_id in self.input_buffers:
            del self.input_buffers[session_id]

web_terminal = WebTerminal()

@app.route('/')
def index():
    return render_template('terminal.html')

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    session_id = request.sid
    if web_terminal.create_terminal(session_id):
        # 启动读取线程
        thread = threading.Thread(
            target=web_terminal.read_terminal,
            args=(session_id,)
        )
        thread.daemon = True
        thread.start()

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    session_id = request.sid
    web_terminal.cleanup(session_id)

@socketio.on('terminal_input')
def handle_terminal_input(data):
    """处理终端输入"""
    session_id = request.sid
    web_terminal.write_terminal(session_id, data)

if __name__ == '__main__':
    # 获取本机IP地址
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print(f"Server running at http://{local_ip}:5000")
    # 使用 host='0.0.0.0' 允许外部访问
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 