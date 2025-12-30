"""
MJPEG 流服务器
提供实时视频流，绕过 Gradio 的事件机制
"""
import io
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from .screen_stream import get_screen_streamer


class MJPEGHandler(BaseHTTPRequestHandler):
    """MJPEG 流处理器"""

    def log_message(self, format, *args):
        """禁用日志输出"""
        pass

    def do_GET(self):
        if self.path == '/stream':
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

                    # 获取帧
                    frame_bytes = streamer.get_frame_bytes()
                    if frame_bytes:
                        # 检查是否是新帧
                        current_id = streamer._frame_id
                        if current_id > last_frame_id:
                            last_frame_id = current_id
                            # 发送 MJPEG 帧
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

        elif self.path == '/':
            # 简单的测试页面
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><img src="/stream" /></body></html>')

        else:
            self.send_response(404)
            self.end_headers()


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
