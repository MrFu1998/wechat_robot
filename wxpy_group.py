#!/usr/bin/env python3
# coding: utf-8

"""
wxpy 机器人正在使用的所有代码


可能需要安装开发分支的 wxpy
pip3 install -U git+https://github.com/youfou/wxpy.git@develop

另外，还需要 psutil 模块，用于监控进程状态，例如内存占用情况。请自行安装:
pip3 install -U psutil
"""

import datetime
import logging
import os
import re
import subprocess
import time
from functools import wraps
from pprint import pformat

import psutil

from wxpy import *
from wxpy.utils import get_text_without_at_bot, start_new_thread

# ---------------- 配置开始 ----------------

# Bot 对象初始化时的 console_qr 参数值
console_qr = True

# 机器人昵称 (防止登错账号)
bot_nick_name = 'wxpy 机器人'

# 入群口令
group_code = 'wxpy'

# 管理员，可为多个，用于执行管理
# 首个管理员为"系统管理员"，可接收异常日志和执行服务端操作
# 其他管理员仅执行微信群管理

admin_puids = (
    # 游否
    '79d4848f',
)

# 管理群
# 仅为一个，用于接收心跳上报等次要信息

# 🤖️Admins
admin_group_puid = '053285a4'

# 需管理的微信群
# 可为多个，机器人必须为群主，否则无法执行相应操作

group_puids = (
    # wxpy 交流群 🐰
    '6e321394',
    # wxpy 交流群 🐱
    '1d0e67de',
    # wxpy 交流群 🐨
    '9f867de9',
)

# 自动回答关键词
kw_replies = {
    'wxpy 项目主页:\ngithub.com/youfou/wxpy': (
        '项目', '主页', '官网', '网站', 'github', '地址', 'repo', '版本'
    ),
    'wxpy 在线文档:\nwxpy.readthedocs.io': (
        '请问', '文档', '帮助', '怎么', '如何', '请教', '安装', '说明'
    ),
    '必看: 常见问题 FAQ:\nwxpy.readthedocs.io/faq.html': (
        'faq', '常见', '问题', '问答', '什么'
    )
}

# 新人入群的欢迎语
welcome_text = '''🎉 欢迎 @{} 的加入！
😃 请勿在本群使用机器人
📖 提问前请看 t.cn/R6VkJDy'''

# ---------------- 配置结束 ----------------


logging.basicConfig(level=logging.INFO)

bot = Bot('bot.pkl', console_qr=console_qr)
bot.enable_puid('bot_puid.pkl')

if bot.self.name != bot_nick_name:
    raise ValueError('Wrong User!')

admins = *map(lambda x: bot.friends().search(puid=x)[0], admin_puids), bot.self
admin_group = bot.groups().search(puid=admin_group_puid)[0]
groups = list(map(lambda x: bot.groups().search(puid=x)[0], group_puids))

# 初始化聊天机器人
tuling = Tuling()

# 新人入群通知的匹配正则
rp_new_member_name = (
    re.compile(r'^"(.+)"通过'),
    re.compile(r'邀请"(.+)"加入'),
)

# 远程踢人命令: 移出 @<需要被移出的人>
rp_kick = re.compile(r'^移出\s*@(.+?)(?:\u2005?\s*$)')


def from_admin(msg):
    """
    判断 msg 中的发送用户是否为管理员
    :param msg:
    :return:
    """
    if not isinstance(msg, Message):
        raise TypeError('expected Message, got {}'.format(type(msg)))
    from_user = msg.member if isinstance(msg.chat, Group) else msg.sender
    return from_user in admins


def admin_auth(func):
    """
    装饰器: 验证函数的第 1 个参数 msg 是否来自 admins
    """

    @wraps(func)
    def wrapped(*args, **kwargs):
        msg = args[0]

        if from_admin(msg):
            return func(*args, **kwargs)
        else:
            raise ValueError('Wrong admin:\n{}'.format(msg))

    return wrapped


def send_iter(receiver, iterable):
    """
    用迭代的方式发送多条消息

    :param receiver: 接收者
    :param iterable: 可迭代对象
    """

    if isinstance(iterable, str):
        raise TypeError

    for msg in iterable:
        receiver.send(msg)


def update_groups():
    yield 'updating groups...'
    for _group in groups:
        _group.update_group()
        yield '{}: {}'.format(_group.name, len(_group))


process = psutil.Process()


def status_text():
    uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(process.create_time())
    memory_usage = process.memory_info().rss
    yield '[now] {now:%H:%M:%S}\n[uptime] {uptime}\n[memory] {memory}\n[messages] {messages}'.format(
        now=datetime.datetime.now(),
        uptime=str(uptime).split('.')[0],
        memory='{:.2f} MB'.format(memory_usage / 1024 ** 2),
        messages=len(bot.messages)
    )


# 定时报告进程状态
def heartbeat():
    while bot.alive:
        time.sleep(600)
        # noinspection PyBroadException
        try:
            send_iter(admin_group, status_text())
        except:
            logger.exception('failed to report heartbeat:')


start_new_thread(heartbeat)


def remote_eval(source):
    try:
        ret = eval(source, globals())
    except (SyntaxError, NameError):
        raise ValueError('got SyntaxError or NameError in source')

    logger.info('remote eval executed:\n{}'.format(source))
    yield pformat(ret)


def remote_shell(command):
    logger.info('executing remote shell cmd:\n{}'.format(command))
    r = subprocess.run(
        command, shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    if r.stdout:
        yield r.stdout
    else:
        yield '[OK]'


def restart():
    yield 'restarting bot...'
    bot.dump_login_status()
    os.execv(sys.executable, [sys.executable] + sys.argv)


def latency():
    yield '{:.2f}'.format(bot.messages[-1].latency)


# 远程命令 (单独发给机器人的消息)
remote_orders = {
    'g': update_groups,
    's': status_text,
    'r': restart,
    'l': latency,
}


@admin_auth
def server_mgmt(msg):
    """
    服务器管理:

        若消息文本为为远程命令，则执行对应函数
        若消息文本以 ! 开头，则作为 shell 命令执行
        若不满足以上，则尝试直接将 msg.text 作为 Python 代码执行
    """
    order = remote_orders.get(msg.text.strip())
    if order:
        logger.info('executing remote order: {}'.format(order.__name__))
        send_iter(msg.chat, order())
    elif msg.text.startswith('!'):
        command = msg.text[1:]
        send_iter(msg.chat, remote_shell(command))
    else:
        send_iter(msg.chat, remote_eval(msg.text))


def reply_by_keyword(msg):
    for reply, keywords in kw_replies.items():
        for kw in keywords:
            if kw in msg.text.lower():
                logger.info('reply by keyword: \n{}: "{}"\nreplied: "{}"'.format(
                    (msg.member or msg.chat).name, msg.text, reply))
                msg.reply(reply)
                return reply


# 验证入群口令
def valid(msg):
    return group_code in msg.text.lower()


# 自动选择未满的群
def get_group():
    groups.sort(key=len, reverse=True)

    for _group in groups:
        if len(_group) < 495:
            return _group
    else:
        logger.warning('群都满啦！')
        return groups[-1]


# 邀请入群
def invite(user):
    joined = list()
    for group in groups:
        if user in group:
            joined.append(group)
    if joined:
        joined_nick_names = '\n'.join(map(lambda x: x.nick_name, joined))
        logger.info('{} is already in\n{}'.format(user, joined_nick_names))
        user.send('你已加入了\n{}'.format(joined_nick_names))
    else:
        group = get_group()
        user.send('验证通过 [嘿哈]')
        group.add_members(user, use_invitation=True)


# 限制频率: 指定周期内超过消息条数，直接回复 "🙊"
def freq_limit(period_secs=10, limit_msgs=3):
    def decorator(func):
        @wraps(func)
        def wrapped(msg):
            now = datetime.datetime.now()
            period = datetime.timedelta(seconds=period_secs)
            recent_received = 0
            for m in msg.bot.messages[::-1]:
                if m.sender == msg.sender:
                    if now - m.create_time > period:
                        break
                    recent_received += 1

            if recent_received > limit_msgs:
                if not isinstance(msg.chat, Group) or msg.is_at:
                    return '🙊'
            return func(msg)

        return wrapped

    return decorator


def get_new_member_name(msg):
    # itchat 1.2.32 版本未格式化群中的 Note 消息
    from itchat.utils import msg_formatter
    msg_formatter(msg.raw, 'Text')

    for rp in rp_new_member_name:
        match = rp.search(msg.text)
        if match:
            return match.group(1)


def remote_kick(msg):
    if msg.type is TEXT:
        match = rp_kick.search(msg.text)
        if match:
            name_to_kick = match.group(1)

            if not from_admin(msg):
                logger.warning('{} tried to kick {}'.format(
                    msg.member.name, name_to_kick))
                return '感觉有点不对劲… @{}'.format(msg.member.name)

            member_to_kick = ensure_one(list(filter(
                lambda x: x.name == name_to_kick, msg.chat)))

            if member_to_kick in admins:
                logger.error('{} tried to kick {} whom was an admin'.format(
                    msg.member.name, member_to_kick.name))
                return '无法移出 @{}'.format(member_to_kick.name)

            member_to_kick.remove()
            return '成功移出 @{}'.format(member_to_kick.name)


def semi_sync(msg, _groups):
    if msg.is_at:
        msg.raw['Text'] = get_text_without_at_bot(msg)
        if msg.text:
            sync_message_in_groups(
                msg, _groups, suffix='↑隔壁消息↑回复请@机器人')


# 判断消息是否为支持回复的消息类型
def supported_msg_type(msg, reply_unsupported=False):
    supported = (TEXT,)
    ignored = (SYSTEM, NOTE, FRIENDS)

    fallback_replies = {
        RECORDING: '🙉',
        PICTURE: '🙈',
        VIDEO: '🙈',
    }

    if msg.type in supported:
        return True
    elif msg.type not in ignored and reply_unsupported:
        msg.reply(fallback_replies.get(msg.type, '🐒'))


# 响应好友请求
@bot.register(msg_types=FRIENDS)
def new_friends(msg):
    user = msg.card.accept()
    if valid(msg):
        invite(user)
    else:
        user.send('Hello {}，你忘了填写加群口令，快回去找找口令吧'.format(user.name))


# 响应好友消息，限制频率
@bot.register(Friend)
@freq_limit()
def exist_friends(msg):
    if supported_msg_type(msg, reply_unsupported=True):
        if isinstance(msg.chat, User) and valid(msg):
            invite(msg.sender)
            return
        elif reply_by_keyword(msg):
            return

        tuling.do_reply(msg)


# 在其他群中回复被 @ 的消息
@bot.register(Group, TEXT)
def reply_other_group(msg):
    if msg.chat not in groups and msg.is_at:
        if supported_msg_type(msg, reply_unsupported=True):
            tuling.do_reply(msg)


# wxpy 群的消息处理
@bot.register(groups, except_self=False)
def wxpy_group(msg):
    ret_msg = remote_kick(msg)
    if ret_msg:
        return ret_msg
    elif msg.is_at:
        semi_sync(msg, groups)


@bot.register((*admins, admin_group), msg_types=TEXT, except_self=False)
def reply_admins(msg):
    """
    响应远程管理员

    内容解析方式优先级：
    1. 若为远程命令，则执行远程命令 (额外定义，一条命令对应一个函数)
    2. 若消息文本以 ! 开头，则作为 shell 命令执行
    3. 尝试作为 Python 代码执行 (可执行大部分 Python 代码)
    4. 若以上不满足或尝试失败，则作为普通聊天内容回复
    """

    try:
        # 上述的 1. 2. 3.
        server_mgmt(msg)
    except ValueError:
        # 上述的 4.
        if isinstance(msg.chat, User):
            return exist_friends(msg)


# 新人欢迎消息
@bot.register(groups, NOTE)
def welcome(msg):
    name = get_new_member_name(msg)
    if name:
        return welcome_text.format(name)


def get_logger(level=logging.DEBUG, file='bot.log', mode='a'):
    log_formatter = logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    log_formatter_lite = logging.Formatter('%(name)s:%(levelname)s:%(message)s')

    _logger = logging.getLogger()

    for hdlr in _logger.handlers:
        _logger.removeHandler(hdlr)

    # 输出到文件
    if file:
        file_hdlr = logging.FileHandler(file, mode)
        file_hdlr.setFormatter(log_formatter)
        _logger.addHandler(file_hdlr)

    # 输出到屏幕
    console_hdlr = logging.StreamHandler()
    console_hdlr.setLevel(logging.WARNING)
    console_hdlr.setFormatter(log_formatter)
    _logger.addHandler(console_hdlr)

    # 输出到远程管理员微信
    wechat_hdlr = WeChatLoggingHandler(admins[0])
    wechat_hdlr.setLevel(logging.WARNING)
    wechat_hdlr.setFormatter(log_formatter_lite)
    _logger.addHandler(wechat_hdlr)

    # 将未捕捉异常也发送到日志中
    sys.excepthook = lambda *args: logger.critical(
        'UNCAUGHT EXCEPTION:', exc_info=args)

    for m in 'requests', 'urllib3':
        logging.getLogger(m).setLevel(logging.WARNING)

    _logger.setLevel(level)
    return _logger


logger = get_logger()
send_iter(admin_group, status_text())
bot.dump_login_status()

# embed()
bot.join()