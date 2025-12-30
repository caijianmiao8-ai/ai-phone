"""
MJPEG 流服务器
提供实时视频流，绕过 Gradio 的事件机制
同时提供点击/滑动等操作的 API
"""
import io
import json
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Callable, Dict, Any
from .screen_stream import get_screen_streamer


# 全局操作回调
_operation_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None


def set_operation_callback(callback: Callable[[str, Dict[str, Any]], None]):
    """设置操作回调函数"""
    global _operation_callback
    _operation_callback = callback


class MJPEGHandler(BaseHTTPRequestHandler):
    """MJPEG 流处理器"""

    def log_message(self, format, *args):
        """禁用日志输出"""
        pass

    def do_GET(self):
        if self.path == '/stream':
            self._handle_stream()
        elif self.path == '/status':
            self._handle_status()
        elif self.path == '/':
            self._handle_test_page()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """处理操作请求"""
        if self.path == '/tap':
            self._handle_operation('tap')
        elif self.path == '/swipe':
            self._handle_operation('swipe')
        elif self.path == '/back':
            self._handle_operation('back')
        elif self.path == '/home':
            self._handle_operation('home')
        elif self.path == '/recent':
            self._handle_operation('recent')
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_stream(self):
        """处理视频流请求"""
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        streamer = get_screen_streamer()
        last_frame_id = 0

        try:
            while True:
                if not streamer.is_running():
                    time.sleep(0.1)
                    continue

                frame_bytes = streamer.get_frame_bytes()
                if frame_bytes:
                    current_id = streamer._frame_id
                    if current_id > last_frame_id:
                        last_frame_id = current_id
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(f'Content-Length: {len(frame_bytes)}\r\n'.encode())
                        self.wfile.write(b'\r\n')
                        self.wfile.write(frame_bytes)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()

                time.sleep(0.04)  # 25fps

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _handle_status(self):
        """返回流状态"""
        streamer = get_screen_streamer()
        status = {
            'running': streamer.is_running(),
            'mode': streamer.get_mode() if streamer.is_running() else None,
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())

    def _handle_operation(self, op_type: str):
        """处理操作请求"""
        global _operation_callback

        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        # 调用回调
        if _operation_callback:
            try:
                _operation_callback(op_type, data)
                self.send_response(200)
            except Exception as e:
                self.send_response(500)
        else:
            self.send_response(503)  # Service Unavailable

        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _handle_test_page(self):
        """测试页面"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<html><body><img src="/stream" /></body></html>')


class MJPEGServer:
    """MJPEG 流服务器管理器"""

    def __init__(self, port: int = 8765):
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        """启动服务器"""
        if self._running:
            return True

        try:
            self._server = HTTPServer(('127.0.0.1', self.port), MJPEGHandler)
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()
            self._running = True
            return True
        except Exception as e:
            print(f"MJPEG 服务器启动失败: {e}")
            return False

    def _serve(self):
        """服务器主循环"""
        try:
            self._server.serve_forever()
        except Exception:
            pass

    def stop(self):
        """停止服务器"""
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server = None

    def get_stream_url(self) -> str:
        """获取流地址"""
        return f"http://127.0.0.1:{self.port}/stream"

    def is_running(self) -> bool:
        return self._running


# 全局实例
_mjpeg_server: Optional[MJPEGServer] = None


def get_mjpeg_server() -> MJPEGServer:
    """获取全局 MJPEG 服务器实例"""
    global _mjpeg_server
    if _mjpeg_server is None:
        _mjpeg_server = MJPEGServer()
    return _mjpeg_server
