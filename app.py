from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import openai
import time
import traceback
import requests
import threading
import re

app = Flask(__name__)

# 設定環境變數
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"  # 免費API端點

# 對話歷史管理
conversation_history = {}

# 搜尋相關函式
def clean_html(raw_html):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', raw_html)

def get_duckduckgo_summary(query):
    try:
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "no_redirect": 1,
            "t": "linebot"
        }
        response = requests.get("https://api.duckduckgo.com/", params=params, timeout=10)
        data = response.json()
        
        # 優先解析摘要
        if data.get('AbstractText'):
            return clean_html(data['AbstractText'])
        # 次選相關主題
        elif data.get('RelatedTopics'):
            for topic in data['RelatedTopics']:
                if topic.get('Text'):
                    return clean_html(topic['Text'])[:300]
        return None
    except Exception as e:
        print(f"DuckDuckGo 搜尋失敗: {e}")
        return None

def yahoo_tw_search(query):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = f"https://tw.search.yahoo.com/search?p={requests.utils.quote(query)}"
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        # 解析搜尋結果
        pattern = re.compile(
            r'<div class="compTitle options-toggle".*?<h3><a.*?>(.*?)</a>.*?<div class="compText">(.*?)</div>',
            re.DOTALL
        )
        results = pattern.findall(response.text)
        
        if results:
            title = clean_html(results[0][0]).strip()
            snippet = clean_html(results[0][1]).strip()
            return f"{title}: {snippet[:250]}..."
        return None
    except Exception as e:
        print(f"Yahoo 搜尋失敗: {e}")
        return None

# GPT 整合函式
def get_ai_response(messages):
    system_msg = {"role": "system", "content": "用繁體中文回答，若資訊不確定或超過2023年，請說『讓我幫您查詢最新資訊』"}
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[system_msg] + messages,
            temperature=0.6,
            max_tokens=400
        )
        return response['choices'][0]['message']['content'].strip()
    except:
        return None

# LINE 處理邏輯
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text
    
    try:
        # 管理對話歷史
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        conversation_history[user_id].append({"role": "user", "content": user_msg})

        # 判斷是否為查詢指令
        if user_msg.startswith("查詢"):
            # 提取查詢關鍵字
            search_query = user_msg[2:].strip()  # 去除"查詢"兩字
            
            # 嘗試搜尋 DuckDuckGo
            search_result = get_duckduckgo_summary(search_query)
            
            # 次選 Yahoo 台灣
            if not search_result:
                search_result = yahoo_tw_search(search_query)
            
            # 組合最終回應
            if search_result:
                final_response = f"📢 最新查詢結果：\n{search_result}\n\n(資料來源：網路即時資訊)"
            else:
                final_response = "暫時無法取得最新資訊，建議調整關鍵字後再試。"
            
            # 保留搜尋結果在對話歷史
            conversation_history[user_id].append({"role": "assistant", "content": final_response})
        else:
            # 如果不是查詢指令，則繼續處理 GPT 回應
            gpt_response = get_ai_response(conversation_history[user_id])
            
            if not gpt_response or '查詢最新資訊' in gpt_response:
                final_response = "如果您想查詢最新資訊，請輸入「查詢【查詢關鍵字】」。"
            else:
                final_response = gpt_response
                conversation_history[user_id].append({"role": "assistant", "content": final_response})
        
        # 避免歷史對話過長
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-8:]
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_response))
        
    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="處理訊息時發生錯誤，請稍後再試。"))

# 保持伺服器喚醒
def keep_alive():
    while True:
        try:
            requests.get("https://your-render-app.onrender.com")  # 替換成你的伺服器URL
            time.sleep(50)
        except:
            time.sleep(60)

threading.Thread(target=keep_alive, daemon=True).start()

@app.route("/")
def home():
    return "ChatBot is Running"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
