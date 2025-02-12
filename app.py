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

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# 用來儲存每個用戶的對話歷史
conversation_history = {}

def GPT_response_with_history(messages):
    # 在對話歷史前加上系統提示，確保 GPT 用繁體中文回答
    system_prompt = {"role": "system", "content": "請用繁體中文回答。"}
    messages_with_system = [system_prompt] + messages

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",  # 使用 GPT-4 模型
        messages=messages_with_system,
        temperature=0.5,
        max_tokens=500
    )
    answer = response['choices'][0]['message']['content'].strip()
    return answer

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id  # 獲取用戶的 LINE 用戶 ID
    msg = event.message.text

    try:
        # 初始化用戶的對話歷史（如果尚未存在）
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # 將用戶的新訊息加入對話歷史
        conversation_history[user_id].append({"role": "user", "content": msg})

        # 將對話歷史傳遞給 GPT
        response = GPT_response_with_history(conversation_history[user_id])

        # 將 GPT 的回應加入對話歷史
        conversation_history[user_id].append({"role": "assistant", "content": response})

        # 回覆用戶
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))
    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試。"))

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)

# === Keep Alive 功能 ===
def keep_alive():
    while True:
        try:
            url = "https://chatgpt-bot-uzvv.onrender.com/"  # 請替換為你的 Render 伺服器網址
            response = requests.get(url)
            print(f"Keep Alive: {response.status_code}")
        except Exception as e:
            print(f"Keep Alive 失敗: {e}")
        time.sleep(40)  # 每 40 秒發送一次請求

# 啟動 Keep Alive 在獨立執行緒中運行
threading.Thread(target=keep_alive, daemon=True).start()

@app.route("/")
def home():
    return "Server is running!", 200  # 讓 Render 伺服器知道它還活著

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

