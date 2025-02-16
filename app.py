from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import googletrans
import tempfile, os
import datetime
import openai
import time
import traceback
import requests
import threading
from googletrans import Translator
from gtts import gTTS

# 初始化 Flask 应用
app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# LINE Bot 配置
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OpenAI 配置
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# 翻译器初始化
translator = Translator()

# 用户对话历史存储
conversation_history = {}

# 用户日程存储
user_schedules = {}

# === 功能函数 ===

# 1. 天气查询
def get_weather(city):
    api_key = "491e5700c3cc79cccfe5c2435c8a9b94"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&lang=zh_tw&units=metric"
    response = requests.get(url)
    data = response.json()
    if data.get("cod") != 200:
        return "無法獲取天氣資訊。"
    weather = data["weather"][0]["description"]
    temp = data["main"]["temp"]
    return f"{city}的天氣：{weather}，溫度：{temp}°C"

# 2. Google 查询（使用 DuckDuckGo 替代）
def duckduckgo_search(query):
    url = f"https://api.duckduckgo.com/?q={query}&format=json"
    response = requests.get(url)
    data = response.json()
    if "Abstract" in data and data["Abstract"]:
        return data["Abstract"]
    return "未找到相關結果。"

# 3. 日程管理
def add_schedule(user_id, schedule):
    if user_id not in user_schedules:
        user_schedules[user_id] = []
    user_schedules[user_id].append(schedule)
    return "日程已添加。"

def set_reminder(user_id, reminder_time, message):
    def remind():
        line_bot_api.push_message(user_id, TextSendMessage(text=message))
    delay = (reminder_time - datetime.datetime.now()).total_seconds()
    if delay > 0:
        threading.Timer(delay, remind).start()
        return "提醒已設置。"
    return "無效的時間。"

# 4. 翻译功能
def translate_text(text, target_language):
    translation = translator.translate(text, dest=target_language)
    return translation.text

# 5. 生活助手
def get_nearby_places(location, place_type):
    url = f"https://nominatim.openstreetmap.org/search?q={place_type}+near+{location}&format=json"
    response = requests.get(url)
    data = response.json()
    if not data:
        return "未找到附近地點。"
    places = [place["display_name"] for place in data[:5]]  # 取前 5 个结果
    return "附近地點：" + ", ".join(places)

def get_traffic_info(origin, destination):
    api_key = "5b3ce3597851110001cf62486cd0e71805354473ad65cddb9ca396ef"
    url = f"https://api.openrouteservice.org/v2/directions/driving-car?api_key={api_key}&start={origin}&end={destination}"
    response = requests.get(url)
    data = response.json()
    if "routes" not in data:
        return "無法獲取交通資訊。"
    duration = data["routes"][0]["segments"][0]["duration"] / 60  # 转换为分钟
    return f"預計行程時間：{duration:.1f} 分鐘"

def get_flight_info(flight_number):
    api_key = "83caaac8d473b8b58b13fb9a5b0752cd"
    url = f"http://api.aviationstack.com/v1/flights?access_key={api_key}&flight_iata={flight_number}"
    response = requests.get(url)
    data = response.json()
    if "data" not in data:
        return "無法獲取航班資訊。"
    flight = data["data"][0]
    status = flight["flight_status"]
    departure = flight["departure"]["airport"]
    arrival = flight["arrival"]["airport"]
    return f"航班狀態：{status}，起飛機場：{departure}，抵達機場：{arrival}"

# 6. 即时口译
def translate_and_speak(text, target_language):
    translated_text = translate_text(text, target_language)
    tts = gTTS(translated_text, lang=target_language)
    audio_file = os.path.join(static_tmp_path, "translation.mp3")
    tts.save(audio_file)
    return translated_text, audio_file

# 7. GPT 对话
def GPT_response_with_history(messages):
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

# === LINE Bot 事件处理 ===

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
        # 天气查询
        if msg.startswith("天氣 "):
            city = msg[3:].strip()
            weather_info = get_weather(city)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=weather_info))

        # Google 查询
        elif msg.startswith("查詢 "):
            query = msg[3:].strip()
            search_result = duckduckgo_search(query)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=search_result))

        # 翻译功能
        elif msg.startswith("翻譯 "):
            parts = msg[3:].split("到")
            if len(parts) == 2:
                text, target_language = parts[0].strip(), parts[1].strip()
                translated_text = translate_text(text, target_language)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=translated_text))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="格式錯誤，請使用：翻譯 [文字] 到 [語言]"))

        # 日程管理
        elif msg.startswith("添加日程 "):
            schedule = msg[5:].strip()
            result = add_schedule(user_id, schedule)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))

        elif msg.startswith("設置提醒 "):
            parts = msg[5:].split(" ")
            if len(parts) >= 2:
                time_str, message = parts[0], " ".join(parts[1:])
                try:
                    reminder_time = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                    result = set_reminder(user_id, reminder_time, message)
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="時間格式錯誤，請使用：設置提醒 [時間] [訊息]"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="格式錯誤，請使用：設置提醒 [時間] [訊息]"))

        # 生活助手
        elif msg.startswith("附近推薦 "):
            place_type = msg[5:].strip()
            location = "桃園"  # 可以改为从用户输入中获取位置
            result = get_nearby_places(location, place_type)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))

        elif msg.startswith("交通訊息 "):
            parts = msg[5:].split("到")
            if len(parts) == 2:
                origin, destination = parts[0].strip(), parts[1].strip()
                result = get_traffic_info(origin, destination)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="格式錯誤，請使用：交通訊息 [起點] 到 [終點]"))

        elif msg.startswith("航班查詢 "):
            flight_number = msg[5:].strip()
            result = get_flight_info(flight_number)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))

        # 即时口译
        elif msg.startswith("翻譯 "):
            parts = msg[3:].split("到")
            if len(parts) == 2:
                text, target_language = parts[0].strip(), parts[1].strip()
                translated_text, audio_file = translate_and_speak(text, target_language)
                # 发送翻译后的文字和语音
                line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(text=translated_text), AudioSendMessage(original_content_url=audio_file, duration=1000)]
                )
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="格式錯誤，請使用：翻譯 [文字] 到 [語言]"))

        # 其他功能（GPT 对话）
        else:
            if user_id not in conversation_history:
                conversation_history[user_id] = []
            conversation_history[user_id].append({"role": "user", "content": msg})
            response = GPT_response_with_history(conversation_history[user_id])
            conversation_history[user_id].append({"role": "assistant", "content": response})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

    except Exception as e:
        print(f"Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試。"))

# === Keep Alive 功能 ===
def keep_alive():
    while True:
        try:
            url = "https://chatgpt-bot-uzvv.onrender.com/"  # 替換為你的 Render 伺服器網址
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
