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
from deep_translator import GoogleTranslator
from openweather import OpenWeatherMap  # 假设你已经封装了 OpenWeatherMap API
from yahoo_news import YahooNews  # 假设你已经封装了 Yahoo 新闻 API
from aviationstack import AviationStack  # 假设你已经封装了 AviationStack API

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://free.v36.cm/v1"

# 初始化 API 客户端
weather_api = OpenWeatherMap(api_key=os.getenv('491e5700c3cc79cccfe5c2435c8a9b94'))
news_api = YahooNews()
aviation_api = AviationStack(api_key=os.getenv('96e60ba1d1be1bc54d624788433ed993'))

# 用来储存每个用户的对话历史
conversation_history = {}

# 用来储存每个用户最后一次查询天气的时间
user_last_weather_query = {}

def GPT_response_with_history(messages):
    # 在对话历史前加上系统提示，确保 GPT 用繁体中文回答
    system_prompt = {"role": "system", "content": "请用繁体中文回答。"}
    messages_with_system = [system_prompt] + messages

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",  # 使用 GPT-4 模型
        messages=messages_with_system,
        temperature=0.5,
        max_tokens=500
    )
    answer = response['choices'][0]['message']['content'].strip()
    return answer

def translate_to_english(text):
    """将非英文地名翻译成英文"""
    translator = GoogleTranslator(source='auto', target='en')
    return translator.translate(text)

def get_weather(location):
    """查询天气"""
    try:
        weather_data = weather_api.get_weather(location)
        return f"{location} 的天气：{weather_data['description']}，温度：{weather_data['temp']}°C"
    except Exception as e:
        return f"无法获取 {location} 的天气信息，请稍后再试。"

def get_news(query):
    """查询新闻"""
    try:
        news_results = news_api.search(query)
        if news_results:
            return "\n".join([f"{news['title']}: {news['link']}" for news in news_results[:3]])
        else:
            return f"没有找到关于 {query} 的新闻。"
    except Exception as e:
        return f"无法获取新闻，请稍后再试。"

def get_flight_info(flight_number):
    """查询航班信息"""
    try:
        flight_data = aviation_api.get_flight_info(flight_number)
        return f"航班 {flight_number} 的信息：{flight_data['status']}，起飞时间：{flight_data['departure']}"
    except Exception as e:
        return f"无法获取航班 {flight_number} 的信息，请稍后再试。"

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
    user_id = event.source.user_id  # 获取用户的 LINE 用户 ID
    msg = event.message.text

    try:
        # 初始化用户的对话历史（如果尚未存在）
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # 处理天气查询
        if msg.startswith("天气"):
            location = msg[2:].strip()
            if location:
                # 检查用户是否在一分钟内重复查询
                last_query_time = user_last_weather_query.get(user_id, 0)
                current_time = time.time()
                if current_time - last_query_time < 60:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不好意思，每分钟只能请求一次，不然太烧钱了 QQ"))
                    return
                user_last_weather_query[user_id] = current_time

                # 翻译地名
                location_en = translate_to_english(location)
                weather_info = get_weather(location_en)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=weather_info))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="请输入有效的地名。"))

        # 处理新闻查询
        elif msg.startswith("新闻"):
            query = msg[2:].strip()
            if query:
                news_info = get_news(query)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=news_info))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="请输入有效的查询内容。"))

        # 处理航班查询
        elif msg.startswith("班机查询"):
            flight_number = msg[4:].strip()
            if flight_number:
                flight_info = get_flight_info(flight_number)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=flight_info))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="请输入有效的航班编号。"))

        # 处理待开发功能
        elif msg.startswith("附近") or msg.startswith("画") or msg.startswith("提醒"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="待开发功能，开发完毕即可使用"))

        # 处理一般对话
        else:
            # 将用户的新消息加入对话历史
            conversation_history[user_id].append({"role": "user", "content": msg})

            # 将对话历史传递给 GPT
            response = GPT_response_with_history(conversation_history[user_id])

            # 将 GPT 的回应加入对话历史
            conversation_history[user_id].append({"role": "assistant", "content": response})

            # 回复用户
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))
    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="发生错误，请稍后再试。"))

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}欢迎加入')
    line_bot_api.reply_message(event.reply_token, message)

# === Keep Alive 功能 ===
def keep_alive():
    while True:
        try:
            url = "https://chatgpt-bot-uzvv.onrender.com/"  # 请替换为你的 Render 服务器网址
            response = requests.get(url)
            print(f"Keep Alive: {response.status_code}")
        except Exception as e:
            print(f"Keep Alive 失败: {e}")
        time.sleep(40)  # 每 40 秒发送一次请求

# 启动 Keep Alive 在独立线程中运行
threading.Thread(target=keep_alive, daemon=True).start()

@app.route("/")
def home():
    return "Server is running!", 200  # 让 Render 服务器知道它还活着

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
