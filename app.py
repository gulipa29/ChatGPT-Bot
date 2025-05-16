from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import tempfile, os
import datetime
import openai
import time
import traceback
import requests
import threading
import logging

# 設置日誌記錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# 環境變數配置
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# 對話歷史管理
MAX_HISTORY_LENGTH = 10  # 限制對話歷史長度
MAX_HISTORY_AGE = 3600  # 對話歷史過期時間（秒）
conversation_history = {}
last_activity = {}

def clean_expired_conversations():
    """定期清理過期的對話歷史"""
    current_time = time.time()
    expired_users = [user_id for user_id, last_time in last_activity.items()
                    if current_time - last_time > MAX_HISTORY_AGE]
    for user_id in expired_users:
        conversation_history.pop(user_id, None)
        last_activity.pop(user_id, None)

def get_system_prompt(user_id):
    """根據用戶生成個性化系統提示詞"""
    return {
        "role": "system",
        "content": """請以專業且友善的態度用繁體中文回答。
                    回答時請注意以下幾點：
                    1. 保持回答簡潔明瞭
                    2. 使用適當的敬語
                    3. 必要時提供具體的例子"""
    }

def GPT_response_with_history(messages, user_id):
    try:
        # 添加系統提示詞
        messages_with_system = [get_system_prompt(user_id)] + messages[-MAX_HISTORY_LENGTH:]

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages_with_system,
            temperature=0.5,
            max_tokens=500
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error(f"GPT API 錯誤: {str(e)}\n{traceback.format_exc()}")
        raise

@app.route("/callback", methods=['POST'])
def callback():
    try:
        signature = request.headers['X-Line-Signature']
        body = request.get_data(as_text=True)
        logger.info(f"Request body: {body}")
        handler.handle(body, signature)
        return 'OK'
    except InvalidSignatureError:
        logger.error("無效的簽名")
        abort(400)
    except Exception as e:
        logger.error(f"Callback 錯誤: {str(e)}\n{traceback.format_exc()}")
        abort(500)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text

    try:
        # 更新用戶活動時間
        last_activity[user_id] = time.time()

        # 初始化或獲取用戶對話歷史
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # 添加用戶訊息到對話歷史
        conversation_history[user_id].append({"role": "user", "content": msg})

        # 獲取 GPT 回應
        response = GPT_response_with_history(conversation_history[user_id], user_id)

        # 添加 GPT 回應到對話歷史
        conversation_history[user_id].append({"role": "assistant", "content": response})

        # 回覆用戶
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

        # 清理過期對話
        clean_expired_conversations()
    except Exception as e:
        error_msg = "很抱歉，系統暫時無法處理您的請求，請稍後再試。"
        logger.error(f"處理訊息錯誤: {str(e)}\n{traceback.format_exc()}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))

@handler.add(PostbackEvent)
def handle_postback(event):
    logger.info(f"收到 Postback 事件: {event.postback.data}")

@handler.add(MemberJoinedEvent)
def welcome(event):
    try:
        uid = event.joined.members[0].user_id
        gid = event.source.group_id
        profile = line_bot_api.get_group_member_profile(gid, uid)
        name = profile.display_name
        message = TextSendMessage(text=f'歡迎 {name} 加入我們！')
        line_bot_api.reply_message(event.reply_token, message)
    except Exception as e:
        logger.error(f"歡迎訊息錯誤: {str(e)}\n{traceback.format_exc()}")

def keep_alive():
    """保持服務器活躍的功能"""
    retry_count = 0
    max_retries = 3
    retry_delay = 5

    while True:
        try:
            url = "https://chatgpt-bot-uzvv.onrender.com/"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            logger.info(f"Keep Alive 成功: {response.status_code}")
            retry_count = 0  # 重置重試計數
            time.sleep(40)
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logger.error(f"Keep Alive 失敗 (嘗試 {retry_count}/{max_retries}): {str(e)}")
            
            if retry_count >= max_retries:
                logger.error("達到最大重試次數，等待下一輪重試")
                retry_count = 0
                time.sleep(60)  # 較長的等待時間
            else:
                time.sleep(retry_delay)

# 啟動 Keep Alive 執行緒
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()

@app.route("/")
def home():
    return "LINE Bot Server is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
