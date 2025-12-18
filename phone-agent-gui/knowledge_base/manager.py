"""
知识库管理模块
支持知识条目的增删改查、关键词匹配检索
"""
import json
import os
import sys
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime


def get_user_data_path() -> str:
    """获取用户数据目录（用于存储配置、知识库等可写数据）"""
    if getattr(sys, 'frozen', False):
        # 打包后使用 exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境使用项目目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class KnowledgeItem:
    """知识库条目"""
    id: str
    title: str
    keywords: List[str]
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeItem":
        return cls(**data)

    def matches(self, query: str) -> bool:
        """检查查询是否匹配此条目（双向匹配：关键词和内容）"""
        query_lower = query.lower()

        # 1. 关键词在查询中（原逻辑）
        for keyword in self.keywords:
            if keyword.lower() in query_lower:
                return True

        # 2. 查询词在关键词中（反向匹配）
        query_words = self._extract_words(query_lower)
        for word in query_words:
            if len(word) >= 2:  # 忽略单字符
                for keyword in self.keywords:
                    if word in keyword.lower():
                        return True

        # 3. 查询词在标题中
        title_lower = self.title.lower()
        for word in query_words:
            if len(word) >= 2 and word in title_lower:
                return True

        # 4. 查询词在内容中（模糊匹配）
        content_lower = self.content.lower()
        for word in query_words:
            if len(word) >= 2 and word in content_lower:
                return True

        return False

    def _extract_words(self, text: str) -> List[str]:
        """提取文本中的词语（支持中英文）"""
        # 英文单词
        english_words = re.findall(r'[a-zA-Z]+', text)
        # 中文词语（简单分词：连续中文字符，2-4字为词）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        chinese_words = []
        for chars in chinese_chars:
            # 提取2-4字的中文词
            if len(chars) >= 2:
                for i in range(len(chars) - 1):
                    chinese_words.append(chars[i:i+2])
                    if i + 3 <= len(chars):
                        chinese_words.append(chars[i:i+3])
                    if i + 4 <= len(chars):
                        chinese_words.append(chars[i:i+4])
        return english_words + chinese_words

    def get_relevance_score(self, query: str) -> float:
        """计算查询与此条目的相关度分数（加权算法）"""
        query_lower = query.lower()
        query_words = self._extract_words(query_lower)
        score = 0.0

        # 1. 关键词精确匹配（权重最高：10分/个）
        for keyword in self.keywords:
            if keyword.lower() in query_lower:
                score += 10.0

        # 2. 标题匹配（权重高：5分/词）
        title_lower = self.title.lower()
        for word in query_words:
            if len(word) >= 2 and word in title_lower:
                score += 5.0

        # 3. 内容匹配（权重中：1分/词，上限10分）
        content_lower = self.content.lower()
        content_score = 0.0
        for word in query_words:
            if len(word) >= 2 and word in content_lower:
                content_score += 1.0
        score += min(content_score, 10.0)

        # 4. 查询词被关键词包含（权重中：3分/个）
        for word in query_words:
            if len(word) >= 2:
                for keyword in self.keywords:
                    if word in keyword.lower():
                        score += 3.0
                        break

        return score


class KnowledgeManager:
    """知识库管理器"""

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            # 默认存储在用户数据目录下
            storage_path = os.path.join(get_user_data_path(), "knowledge_base", "data")
        self.storage_path = storage_path
        self.data_file = os.path.join(storage_path, "knowledge_base.json")
        self._items: List[KnowledgeItem] = []
        self._ensure_storage()
        self._load()

    def _ensure_storage(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_path, exist_ok=True)
        if not os.path.exists(self.data_file):
            self._save()

    def _load(self):
        """从文件加载知识库"""
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._items = [KnowledgeItem.from_dict(item) for item in data]
        except (FileNotFoundError, json.JSONDecodeError):
            self._items = []

    def _save(self):
        """保存知识库到文件"""
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump([item.to_dict() for item in self._items], f,
                     ensure_ascii=False, indent=2)

    def _generate_id(self) -> str:
        """生成唯一ID"""
        import uuid
        return str(uuid.uuid4())[:8]

    def create(self, title: str, keywords: List[str], content: str) -> KnowledgeItem:
        """创建新的知识条目"""
        item = KnowledgeItem(
            id=self._generate_id(),
            title=title,
            keywords=keywords,
            content=content
        )
        self._items.append(item)
        self._save()
        return item

    def get(self, item_id: str) -> Optional[KnowledgeItem]:
        """根据ID获取知识条目"""
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def get_all(self) -> List[KnowledgeItem]:
        """获取所有知识条目"""
        return self._items.copy()

    def update(self, item_id: str, title: str = None,
               keywords: List[str] = None, content: str = None) -> Optional[KnowledgeItem]:
        """更新知识条目"""
        item = self.get(item_id)
        if item is None:
            return None

        if title is not None:
            item.title = title
        if keywords is not None:
            item.keywords = keywords
        if content is not None:
            item.content = content
        item.updated_at = datetime.now().isoformat()

        self._save()
        return item

    def delete(self, item_id: str) -> bool:
        """删除知识条目"""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                self._items.pop(i)
                self._save()
                return True
        return False

    def search(self, query: str) -> List[KnowledgeItem]:
        """根据关键词搜索匹配的知识条目"""
        matches = []
        for item in self._items:
            if item.matches(query):
                matches.append(item)

        # 按相关度排序
        matches.sort(key=lambda x: x.get_relevance_score(query), reverse=True)
        return matches

    def get_best_match(self, query: str) -> Optional[KnowledgeItem]:
        """获取最匹配的知识条目"""
        matches = self.search(query)
        return matches[0] if matches else None

    def export_to_file(self, filepath: str):
        """导出知识库到文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([item.to_dict() for item in self._items], f,
                     ensure_ascii=False, indent=2)

    def import_from_file(self, filepath: str) -> int:
        """从文件导入知识库，返回导入的条目数"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            for item_data in data:
                # 生成新ID避免冲突
                item_data["id"] = self._generate_id()
                item_data["created_at"] = datetime.now().isoformat()
                item_data["updated_at"] = datetime.now().isoformat()
                item = KnowledgeItem.from_dict(item_data)
                self._items.append(item)
                count += 1

            self._save()
            return count
        except Exception as e:
            raise ValueError(f"导入失败: {str(e)}")

    def create_default_templates(self):
        """创建默认知识库模板"""
        templates = [
            {
                "title": "淘宝购物流程",
                "keywords": ["淘宝", "购物", "买东西", "购买", "下单"],
                "content": """淘宝购物操作指南：
1. 打开淘宝APP
2. 点击顶部搜索框
3. 输入想要购买的商品关键词
4. 点击搜索按钮
5. 在搜索结果中浏览商品
6. 点击感兴趣的商品查看详情
7. 选择商品规格（颜色、尺寸等）
8. 点击"加入购物车"或"立即购买"
9. 如需购买，确认收货地址
10. 选择支付方式完成支付

注意事项：
- 注意查看商品评价和销量
- 比较多家店铺的价格
- 确认是否有优惠券可用"""
            },
            {
                "title": "微信发消息",
                "keywords": ["微信", "发消息", "聊天", "发信息", "微信聊天"],
                "content": """微信发消息操作指南：
1. 打开微信APP
2. 在首页消息列表中找到目标联系人
   - 如果最近聊过，直接点击进入
   - 如果没找到，点击右上角搜索图标
3. 在搜索框输入联系人名称
4. 点击搜索结果中的联系人
5. 进入聊天界面
6. 点击底部输入框
7. 输入要发送的消息内容
8. 点击发送按钮

发送其他内容：
- 发图片：点击输入框旁的"+"号，选择"相册"
- 发语音：长按输入框旁的麦克风图标
- 发表情：点击输入框旁的表情图标"""
            },
            {
                "title": "美团点外卖",
                "keywords": ["美团", "外卖", "点餐", "订餐", "吃的"],
                "content": """美团点外卖操作指南：
1. 打开美团APP
2. 点击首页"外卖"入口
3. 确认或修改收货地址
4. 浏览推荐商家或使用搜索
5. 点击想要的商家进入店铺
6. 浏览菜单，点击"+"添加菜品
7. 选择菜品规格（如有）
8. 点击底部购物车查看已选
9. 点击"去结算"
10. 确认订单信息（地址、餐具等）
11. 选择支付方式
12. 点击"提交订单"完成

省钱技巧：
- 查看店铺满减活动
- 使用红包或优惠券
- 关注会员专享价"""
            },
            {
                "title": "高德地图导航",
                "keywords": ["高德", "导航", "地图", "路线", "怎么走", "去哪里"],
                "content": """高德地图导航操作指南：
1. 打开高德地图APP
2. 点击搜索框
3. 输入目的地名称或地址
4. 在搜索结果中选择正确的地点
5. 点击"路线"按钮
6. 选择出行方式（驾车/公交/步行/骑行）
7. 查看推荐路线和预计时间
8. 点击"开始导航"
9. 按语音提示行驶

实用功能：
- 点击"途经点"可添加中途停靠
- 选择"避开拥堵"获取更快路线
- 可设置"回家""去公司"快捷导航"""
            },
            {
                "title": "抖音刷视频",
                "keywords": ["抖音", "视频", "刷视频", "看视频", "短视频"],
                "content": """抖音使用操作指南：
1. 打开抖音APP
2. 自动进入推荐视频流
3. 上滑切换下一个视频
4. 下滑返回上一个视频

互动操作：
- 双击屏幕：点赞
- 点击右侧爱心：点赞
- 点击右侧评论图标：查看/发表评论
- 点击右侧分享图标：分享视频
- 点击右侧头像：进入作者主页
- 长按屏幕：收藏/不感兴趣

搜索特定内容：
1. 点击右上角搜索图标
2. 输入关键词
3. 选择"视频""用户"等分类查看"""
            }
        ]

        for template in templates:
            # 检查是否已存在同名条目
            exists = any(item.title == template["title"] for item in self._items)
            if not exists:
                self.create(
                    title=template["title"],
                    keywords=template["keywords"],
                    content=template["content"]
                )
