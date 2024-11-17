import paramiko
import select
import sys
import time
import signal
import os
from threading import Thread, Event

class TerminalManager:
    def __init__(self, ssh):
        self.ssh = ssh
        self.chan = None
        self.stop_event = Event()
        
    def start_terminal_session(self, container_name):
        """启动终端会话"""
        try:
            # 创建交互式会话
            self.chan = self.ssh.invoke_shell()
            
            # 等待shell准备就绪
            time.sleep(1)
            
            # 发送docker exec命令
            cmd = f'docker exec -it {container_name} /bin/bash\n'
            self.chan.send(cmd)
            
            # 设置信号处理
            signal.signal(signal.SIGWINCH, self.handle_window_resize)
            signal.signal(signal.SIGINT, self.handle_interrupt)
            
            # 创建读写线程
            read_thread = Thread(target=self._read_terminal)
            write_thread = Thread(target=self._write_terminal)
            
            read_thread.daemon = True
            write_thread.daemon = True
            
            read_thread.start()
            write_thread.start()
            
            # 等待任意线程结束
            while read_thread.is_alive() and write_thread.is_alive():
                read_thread.join(0.1)
                write_thread.join(0.1)
                if self.stop_event.is_set():
                    break
            
        except Exception as e:
            print(f"\n终端会话错误：{str(e)}")
        finally:
            if self.chan:
                self.chan.close()
            print("\n终端会话已结束")
    
    def handle_window_resize(self, signum, frame):
        """处理终端窗口大小改变"""
        if self.chan:
            try:
                term_size = os.get_terminal_size()
                self.chan.resize_pty(width=term_size.columns, height=term_size.lines)
            except:
                pass
    
    def handle_interrupt(self, signum, frame):
        """处理Ctrl+C中断"""
        self.stop_event.set()
        if self.chan:
            try:
                self.chan.send('\x03')  # 发送Ctrl+C
            except:
                pass
    
    def _read_terminal(self):
        """从SSH通道读取数据并输出到终端"""
        try:
            while not self.stop_event.is_set():
                if self.chan.recv_ready():
                    data = self.chan.recv(1024)
                    if not data:
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                time.sleep(0.01)
        except:
            self.stop_event.set()
    
    def _write_terminal(self):
        """从终端读取输入并写入SSH通道"""
        try:
            while not self.stop_event.is_set():
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    data = sys.stdin.buffer.read1(1024)
                    if not data:
                        break
                    self.chan.send(data)
        except:
            self.stop_event.set() 