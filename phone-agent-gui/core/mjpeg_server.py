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
        loading_sent = False
        wait_start = time.time()

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
                        self._send_frame(frame_bytes)
                        loading_sent = False  # 收到真实帧后重置
                else:
                    # 没有帧时，每秒发送一次加载占位帧
                    if not loading_sent or (time.time() - wait_start) > 1.0:
                        loading_frame = self._create_loading_frame()
                        if loading_frame:
                            self._send_frame(loading_frame)
                            loading_sent = True
                            wait_start = time.time()

                time.sleep(0.04)  # 25fps

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _send_frame(self, frame_bytes: bytes):
        """发送单帧"""
        self.wfile.write(b'--frame\r\n')
        self.wfile.write(b'Content-Type: image/jpeg\r\n')
        self.wfile.write(f'Content-Length: {len(frame_bytes)}\r\n'.encode())
        self.wfile.write(b'\r\n')
        self.wfile.write(frame_bytes)
        self.wfile.write(b'\r\n')
        self.wfile.flush()

    def _create_loading_frame(self) -> Optional[bytes]:
        """创建加载占位帧"""
        try:
            from PIL import Image, ImageDraw
            # 创建一个简单的加载画面
            img = Image.new('RGB', (360, 640), color=(30, 30, 30))
            draw = ImageDraw.Draw(img)
            # 绘制加载文本
            text = "Loading..."
            # 获取文本大小
            bbox = draw.textbbox((0, 0), text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (360 - text_width) // 2
            y = (640 - text_height) // 2
            draw.text((x, y), text, fill=(128, 128, 128))
            # 转为 JPEG
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=50)
            return buffer.getvalue()
        except Exception:
            return None

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

        print(f"[MJPEG] 收到操作请求: {op_type}, 数据: {data}")

        # 调用回调
        if _operation_callback:
            try:
                _operation_callback(op_type, data)
                print(f"[MJPEG] 操作执行成功: {op_type}")
                self.send_response(200)
            except Exception as e:
                print(f"[MJPEG] 操作执行失败: {op_type}, 错误: {e}")
                self.send_response(500)
        else:
            print(f"[MJPEG] 警告: 回调未注册")
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


class ReuseHTTPServer(HTTPServer):
    """允许端口复用的 HTTP 服务器"""
    allow_reuse_address = True


class MJPEGServer:
    """MJPEG 流服务器管理器"""

    def __init__(self, port: int = 8765):
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        """启动服务器，支持端口重试"""
        if self._running:
            return True

        # 尝试多个端口
        ports_to_try = [self.port, self.port + 1, self.port + 2, 8766, 8767, 8768]

        for port in ports_to_try:
            try:
                self._server = ReuseHTTPServer(('127.0.0.1', port), MJPEGHandler)
                self._thread = threading.Thread(target=self._serve, daemon=True)
                self._thread.start()
                self._running = True
                self.port = port  # 更新实际使用的端口
                print(f"MJPEG 服务器已启动: http://127.0.0.1:{port}")
                return True
            except OSError as e:
                print(f"端口 {port} 不可用: {e}")
                continue
            except Exception as e:
                print(f"MJPEG 服务器启动失败: {e}")
                continue

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
            try:
                self._server.shutdown()
            except Exception:
                pass
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
