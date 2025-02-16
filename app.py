from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import datetime
import openai
import time
import traceback
import requests
import threading
from googletrans import Translator  # 用於翻譯地名
import json

app = Flask(__name__)

# Channel Access Token & Secret
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OpenAI API 設定
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# OpenWeather API Key
OPENWEATHER_API_KEY = os.getenv('491e5700c3cc79cccfe5c2435c8a9b94')

# AviationStack API Key
AVIATIONSTACK_API_KEY = os.getenv('83caaac8d473b8b58b13fb9a5b0752cd')

# 紀錄使用者請求時間（限制每分鐘只能請求一次天氣）
weather_request_time = {}

# Google 翻譯工具
translator = Translator()

# === 查詢天氣 ===
def get_weather(location):
    # 如果地名不是英文，先翻譯成英文
    translated_location = translator.translate(location, src="zh-tw", dest="en").text
    url = f"http://api.openweathermap.org/data/2.5/weather?q={translated_location}&appid={OPENWEATHER_API_KEY}&lang=zh_tw&units=metric"
    
    response = requests.get(url).json()
    if response.get("cod") != 200:
        return "查無此地點的天氣資訊，請輸入正確地名。"
    
    weather_desc = response["weather"][0]["description"]
    temp = response["main"]["temp"]
    humidity = response["main"]["humidity"]
    wind_speed = response["wind"]["speed"]
    
    return f"{location} 的天氣：{weather_desc}\n氣溫：{temp}°C\n濕度：{humidity}%\n風速：{wind_speed}m/s"

# === 查詢新聞 ===
def get_news():
    url = "https://tw.news.yahoo.com/rss"
    response = requests.get(url)
    from xml.etree import ElementTree as ET
    root = ET.fromstring(response.content)
    
    news_list = []
    for item in root.findall(".//item")[:5]:
        title = item.find("title").text
        link = item.find("link").text
        news_list.append(f"{title}\n{link}")
    
    return "\n\n".join(news_list)

# === 查詢航班 ===
def get_flight_info(flight_number):
    url = f"http://api.aviationstack.com/v1/flights?access_key={AVIATIONSTACK_API_KEY}&flight_iata={flight_number}"
    response = requests.get(url).json()
    flights = response.get("data", [])

    if not flights:
        return "查無此航班資訊，請檢查航班號碼是否正確。"
    
    flight = flights[0]
    departure = flight["departure"]["airport"]
    arrival = flight["arrival"]["airport"]
    status = flight["flight_status"]
    
    return f"航班號碼：{flight_number}\n起飛地：{departure}\n降落地：{arrival}\n狀態：{status}"

# === 翻譯與語音播放 ===
def translate_text(text, src_lang, dest_lang):
    translated_text = translator.translate(text, src=src_lang, dest=dest_lang).text
    return translated_text

# === 文本生圖 ===
def generate_image(description):
    response = openai.Image.create(
        prompt=description,
        n=1,
        size="1024x1024"
    )
    return response["data"][0]["url"]

# === 瀏覽網站摘要 ===
def summarize_website(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return "無法訪問該網站，請確認網址是否正確。"

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.text, 'html.parser')
    paragraphs = soup.find_all("p")
    
    text = " ".join([p.text for p in paragraphs[:5]])
    return text[:500] + "..."

# === YouTube 影片摘要 ===
def summarize_youtube(url):
    return "YouTube 影片摘要功能尚未實現（受限於免費 API）。"

# === 處理 LINE 訊息事件 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    try:
        if msg.startswith("天氣"):
            location = msg[2:].strip()
            if not location:
                reply_text = "請輸入地名，如：天氣 台北"
            else:
                # 檢查是否短時間內重複查詢
                now = time.time()
                if user_id in weather_request_time and now - weather_request_time[user_id] < 60:
                    reply_text = "不好意思，每分鐘只能請求一次，不然太燒錢了 QQ"
                else:
                    reply_text = get_weather(location)
                    weather_request_time[user_id] = now
        
        elif msg.startswith("新聞"):
            reply_text = get_news()
        
        elif msg.startswith("航班"):
            flight_number = msg[2:].strip()
            reply_text = get_flight_info(flight_number)
        
        elif msg.startswith("譯"):
            parts = msg.split(" ")
            if len(parts) < 4 or parts[2] != "到":
                reply_text = "請輸入正確格式，如：譯 你好 到 英文"
            else:
                text = parts[1]
                src_lang = "auto"
                dest_lang = parts[3]
                translated_text = translate_text(text, src_lang, dest_lang)
                reply_text = f"翻譯結果：{translated_text}"
        
        elif msg.startswith("畫"):
            description = msg[1:].strip()
            image_url = generate_image(description)
            reply_text = ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
        
        elif msg.startswith("網站"):
            url = msg.split(" ", 1)[1]
            reply_text = summarize_website(url)
        
        elif "youtube.com" in msg or "youtu.be" in msg:
            reply_text = summarize_youtube(msg)

        else:
            reply_text = "我不知道怎麼回應，可以試試查詢天氣、新聞、翻譯等。"

        if isinstance(reply_text, str):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        else:
            line_bot_api.reply_message(event.reply_token, reply_text)

    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試。"))

# === LINE Webhook 設定 ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/")
def home():
    return "Server is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
