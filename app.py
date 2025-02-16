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
from googletrans import Translator

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# 初始化翻譯器
translator = Translator()

# 用來儲存每個用戶的對話歷史
conversation_history = {}
# 紀錄每個用戶的天氣查詢時間
weather_query_time = {}

def GPT_response_with_history(messages):
    system_prompt = {"role": "system", "content": "請用繁體中文回答。"}
    messages_with_system = [system_prompt] + messages

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", 
        messages=messages_with_system,
        temperature=0.5,
        max_tokens=500
    )
    answer = response['choices'][0]['message']['content'].strip()
    return answer

def get_weather(location):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid=491e5700c3cc79cccfe5c2435c8a9b94&lang=zh_tw"
        response = requests.get(url)
        data = response.json()
        if data["cod"] != 200:
            return f"找不到地名 {location} 的天氣資訊。"
        weather = data["weather"][0]["description"]
        temp = data["main"]["temp"] - 273.15  # Kelvin to Celsius
        return f"{location}的天氣是{weather}，溫度是{temp:.2f}°C。"
    except Exception as e:
        return f"無法獲取天氣資訊: {e}"

def get_news(query):
    url = f"https://tw.news.search.yahoo.com/search?p={query}"
    try:
        response = requests.get(url)
        data = response.text
        return data  # 簡化處理，只返回HTML內容
    except Exception as e:
        return f"無法獲取新聞資訊: {e}"

def get_flight_info(flight_number):
    url = f"http://api.aviationstack.com/v1/flights?access_key=83caaac8d473b8b58b13fb9a5b0752cd&flight_iata={flight_number}"
    try:
        response = requests.get(url)
        data = response.json()
        if data["data"]:
            flight = data["data"][0]
            return f"航班 {flight_number} 狀態: {flight['flight_status']}"
        else:
            return f"找不到航班 {flight_number} 的資訊。"
    except Exception as e:
        return f"無法獲取航班資訊: {e}"

def get_image(description):
    url = "https://api-inference.huggingface.co/models/YOUR_MODEL"
    headers = {"Authorization": "Bearer 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"}
    data = {"inputs": description}
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.json()["generated_image"]
    except Exception as e:
        return f"無法生成圖片: {e}"

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
    user_id = event.source.user_id
    msg = event.message.text

    try:
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        conversation_history[user_id].append({"role": "user", "content": msg})

        if msg.startswith("天氣"):
            location = msg[2:].strip()
            if not location.isascii():
                location = translator.translate(location, src='zh-tw', dest='en').text
            
            current_time = time.time()
            if user_id in weather_query_time and current_time - weather_query_time[user_id] < 60:
                response = "不好意思，每分鐘只能請求一次，不然太燒錢了 QQ"
            else:
                weather_query_time[user_id] = current_time
                response = get_weather(location)

        elif msg.startswith("新聞"):
            query = msg[2:].strip()
            response = get_news(query)

        elif msg.startswith("提醒"):
            # 這裡添加日程管理功能的實現
            response = "日程提醒功能還在開發中。"

        elif msg.startswith("附近"):
            place = msg[2:].strip()
            response = f"附近的 {place} 功能還在開發中。"

        elif msg.startswith("班機查詢"):
            flight_number = msg[4:].strip()
            response = get_flight_info(flight_number)

        elif msg.startswith("畫"):
            description = msg[1:].strip()
            response = get_image(description)

        elif msg.startswith("網址"):
            url = msg[2:].strip()
            response = f"瀏覽網址 {url} 功能還在開發中。"

        elif msg.startswith("Youtube"):
            youtube_url = msg[8:].strip()
            response = f"Youtube 影片摘要功能還在開發中。"

        else:
            response = GPT_response_with_history(conversation_history[user_id])

        conversation_history[user_id].append({"role": "assistant", "content": response})
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
            url = "https://chatgpt-bot-uzvv.onrender.com/"
            response = requests.get(url)
            print(f"Keep Alive: {response.status_code}")
        except Exception as e:
            print(f"Keep Alive 失敗: {e}")
        time.sleep(40)

threading.Thread(target=keep_alive, daemon=True).start()

@app.route("/")
def home():
    return "Server is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
