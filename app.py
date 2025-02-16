from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import time
import openai
import requests
import traceback
from googletrans import Translator
import threading
import datetime

app = Flask(__name__)

# === LINE Bot 設定 ===
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# === OpenAI GPT 設定 ===
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

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

# === API Key 設定 ===
OPENWEATHER_API_KEY = os.getenv('491e5700c3cc79cccfe5c2435c8a9b94')  # 天氣 API
AVIATIONSTACK_API_KEY = os.getenv('96e60ba1d1be1bc54d624788433ed993')  # 航班 API
HF_API_KEY = os.getenv('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')  # 文本生圖 API

# === 存儲用戶請求時間（用來限制天氣查詢頻率）===
weather_request_time = {}

# === GPT 對話歷史 ===
conversation_history = {}

translator = Translator()


# === GPT 回應 ===
def GPT_response_with_history(user_id, msg):
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": msg})

    system_prompt = {"role": "system", "content": "請用繁體中文回答。"}
    messages_with_system = [system_prompt] + conversation_history[user_id]

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=messages_with_system,
        temperature=0.5,
        max_tokens=500
    )

    answer = response['choices'][0]['message']['content'].strip()
    conversation_history[user_id].append({"role": "assistant", "content": answer})

    return answer


# === 天氣查詢 ===
def get_weather(city, user_id):
    current_time = time.time()

    # 檢查是否在 1 分鐘內查詢過
    if user_id in weather_request_time and current_time - weather_request_time[user_id] < 60:
        return "不好意思，每分鐘只能請求一次，不然太燒錢了 QQ"

    weather_request_time[user_id] = current_time  # 更新請求時間

    # 翻譯地名
    translated_city = translator.translate(city, dest="en").text

    url = f"http://api.openweathermap.org/data/2.5/weather?q={translated_city}&appid={OPENWEATHER_API_KEY}&lang=zh_tw&units=metric"
    response = requests.get(url).json()

    if response.get("cod") != 200:
        return "找不到該地區的天氣資訊，請確認輸入是否正確。"

    weather = response["weather"][0]["description"]
    temp = response["main"]["temp"]
    humidity = response["main"]["humidity"]
    wind_speed = response["wind"]["speed"]

    return f"🌤 {city} 天氣\n🌡 溫度: {temp}°C\n💧 濕度: {humidity}%\n💨 風速: {wind_speed}m/s\n☁ 天氣: {weather}"


# === 新聞查詢 ===
def get_news(keyword):
    search_url = f"https://tw.news.yahoo.com/search?p={keyword}"
    return f"🔍 這裡是 Yahoo 奇摩的搜尋結果: {search_url}"


# === 航班查詢 ===
def get_flight_info(flight_number):
    url = f"http://api.aviationstack.com/v1/flights?access_key={AVIATIONSTACK_API_KEY}&flight_iata={flight_number}"
    response = requests.get(url)

    # 測試 API 回應
    if response.status_code == 200:
        print(response.json())  # 顯示 API 回應

    if response.status_code == 200:
        data = response.json()
        if "data" not in data or not data["data"]:
            return "找不到該航班資訊，請確認輸入是否正確。"

        flight = data["data"][0]
        airline = flight["airline"]["name"]
        departure = flight["departure"]["airport"]
        arrival = flight["arrival"]["airport"]
        status = flight["flight_status"]

        return f"✈ 航班資訊\n🛫 航空公司: {airline}\n📍 出發機場: {departure}\n🎯 目的機場: {arrival}\n🚦 狀態: {status}"

    return f"無法查詢航班，錯誤代碼: {response.status_code}"


# === 文本生圖 ===
def generate_image(description):
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    response = requests.post(
        "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2",
        headers=headers,
        json={"inputs": description}
    )
    if response.status_code == 200:
        return response.json().get("image_url", "圖片生成失敗")
    return f"圖片生成失敗，錯誤代碼: {response.status_code}"


# === 訊息處理 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text

    try:
        if msg.startswith("天氣"):
            city = msg.replace("天氣", "").strip()
            response = get_weather(city, user_id)

        elif msg.startswith("新聞"):
            keyword = msg.replace("新聞", "").strip()
            response = get_news(keyword)

        elif msg.startswith("班機查詢"):
            flight_number = msg.replace("班機查詢", "").strip()
            response = get_flight_info(flight_number)

        elif msg.startswith("畫"):
            description = msg.replace("畫", "").strip()
            response = generate_image(description)

        elif msg.startswith("提醒"):
            response = "🔔 提醒功能開發中..."

        elif msg.startswith("附近"):
            response = "待開發功能，開發完畢即可使用"

        elif msg.startswith("http") or "youtube.com" in msg or "youtu.be" in msg:
            response = "待開發功能，開發完畢即可使用"

        else:
            response = GPT_response_with_history(user_id, msg)

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試。"))


# === Keep Alive ===
def keep_alive():
    while True:
        try:
            url = "https://chatgpt-bot-uzvv.onrender.com/"
            requests.get(url)
        except Exception as e:
            print(f"Keep Alive 失敗: {e}")
        time.sleep(40)


threading.Thread(target=keep_alive, daemon=True).start()


@app.route("/callback", methods=['POST'])
def callback():
    # Get the signature header
    signature = request.headers['X-Line-Signature']
    
    # Get the request body as text
    body = request.get_data(as_text=True)
    
    app.logger.info(f"Request body: {body}")
    
    try:
        # Process the webhook body
        handler.handle(body, signature)
    except InvalidSignatureError:
        # If the signature is invalid, return 400 error
        abort(400)
    
    return 'OK'


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
