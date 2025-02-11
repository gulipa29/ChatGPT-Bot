from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *

#======python函數庫======
import tempfile, os
import datetime
import openai
import time
import traceback
import requests
import threading
#========================

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

###
# 強制要求繁體中文
def force_traditional_chinese(text):
    cc = opencc.OpenCC('s2t.json')  # 使用簡體到繁體的轉換
    return cc.convert(text)

# 偵測語言
def detect_language(text):
    try:
        language = detect(text)
        return language
    except:
        return "en"  # 假設無法偵測時使用英文

# 記憶功能
user_memory = {}

def get_user_memory(user_id, key):
    if user_id not in user_memory:
        user_memory[user_id] = {}
    return user_memory[user_id].get(key, None)

def update_user_memory(user_id, key, value):
    if user_id not in user_memory:
        user_memory[user_id] = {}
    user_memory[user_id][key] = value

# 記憶功能加強版
def GPT_response_with_memory(user_id, text):
    # 偵測語言
    language = detect_language(text)
    
    # 根據語言進行處理
    if language == "zh-cn":
        # 如果是簡體中文，轉為繁體中文
        prompt = force_traditional_chinese(text)
    elif language == "zh-tw":
        # 如果是繁體中文，直接處理
        prompt = text
    else:
        # 其他語言不轉換，直接處理
        prompt = text

    # 檢查用戶是否有記憶（即歷史對話）
    conversation_history = get_user_memory(user_id, "conversation_history")  # 獲取用戶的對話記錄
    if conversation_history:
        prompt = "\n".join(conversation_history) + "\n" + prompt

    # 呼叫 OpenAI API
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=500
    )
    
    # 擷取回應訊息
    answer = response['choices'][0]['message']['content'].strip()

    # 儲存對話歷史
    updated_conversation = conversation_history + [text, answer] if conversation_history else [text, answer]
    update_user_memory(user_id, "conversation_history", updated_conversation)

    return answer

    ####

def GPT_response(text):
    # 使用 Chat API 來獲取回應
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",  # 改為適用 Chat API 的模型
        messages=[{"role": "user", "content": text}],
        temperature=0.5,
        max_tokens=500
    )
    print(response)
    # 重組回應
    answer = response['choices'][0]['message']['content'].strip()
    return answer

@app.route("/")
def home():
    return "Server is running!", 200  # 讓 Render 伺服器知道它還活著


# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# 處理訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    try:
        GPT_answer = GPT_response(msg)
        print(GPT_answer)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(GPT_answer))
    except:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('OpenAI額度問題，請確認Log訊息。'))
        

@handler.add(PostbackEvent)
def handle_message(event):
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

        
import os
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
