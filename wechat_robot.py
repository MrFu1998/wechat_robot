# coding: utf-8
from wxpy import *

# 扫码登陆
robot = Bot()

# 初始化图灵机器人
tl = Tuling(api_key='********************')

# 自动回复所有文字消息
@robot.register(msg_types=TEXT)
def auto_reply_all(msg):
    tl.do_reply(msg)

# 开始运行
robot.join()

