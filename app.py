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

app = Flask(__name__)

# === LINE Bot 設定 ===
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# === OpenAI GPT 設定 ===
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# === API Key 設定 ===
OPENWEATHER_API_KEY = os.getenv('491e5700c3cc79cccfe5c2435c8a9b94')  # 天氣 API
AVIATIONSTACK_API_KEY = os.getenv('83caaac8d473b8b58b13fb9a5b0752cd')  # 航班 API
HF_API_KEY = os.getenv('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')  # 文本生圖 API

# === 存儲用戶請求時間（限制天氣查詢頻率）===
weather_request_time = {}

# === 儲存對話歷史（每個使用者最多存 10 則）===
conversation_history = {}

translator = Translator()

# === GPT 回應（記錄對話歷史）===
def GPT_response_with_history(user_id, msg):
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # 加入使用者訊息
    conversation_history[user_id].append({"role": "user", "content": msg})

    system_prompt = {"role": "system", "content": "請用繁體中文回答。"}
    messages_with_system = [system_prompt] + conversation_history[user_id]

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages_with_system,
            temperature=0.5,
            max_tokens=500
        )

        # 取得 AI 回應
        answer = response['choices'][0]['message']['content'].strip()
        conversation_history[user_id].append({"role": "assistant", "content": answer})

        # 限制對話歷史長度（最多存 10 則，避免記憶體爆掉）
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]

        return answer
    except Exception as e:
        print(f"GPT API 錯誤: {e}")
        return "❌ GPT 無法回應，請稍後再試"

# === 天氣查詢（翻譯城市名稱）===
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

# === 新聞查詢（Yahoo 奇摩）===
def get_news(keyword):
    search_url = f"https://tw.news.yahoo.com/search?p={keyword}"
    return f"🔍 這裡是 Yahoo 奇摩的搜尋結果: {search_url}"

# === 航班查詢（AviationStack API）===
def get_flight_info(flight_number):
    url = f"http://api.aviationstack.com/v1/flights?access_key={AVIATIONSTACK_API_KEY}&flight_iata={flight_number}"
    response = requests.get(url).json()

    if "data" not in response or not response["data"]:
        return "找不到該航班資訊，請確認輸入是否正確。"

    flight = response["data"][0]
    airline = flight["airline"]["name"]
    departure = flight["departure"]["airport"]
    arrival = flight["arrival"]["airport"]
    status = flight["flight_status"]

    return f"✈ 航班資訊\n🛫 航空公司: {airline}\n📍 出發機場: {departure}\n🎯 目的機場: {arrival}\n🚦 狀態: {status}"

# === 文本生圖（Hugging Face API）===
def generate_image(description):
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    response = requests.post(
        "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2",
        headers=headers,
        json={"inputs": description}
    )
    if response.status_code == 200:
        return response.json()["image_url"]
    return "圖片生成失敗，請稍後再試。"

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
            # 🌟 **這裡加入 GPT 對話功能**
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

@app.route("/")
def home():
    return "Server is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

