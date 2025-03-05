import re

from arclet.alconna import Alconna, AllParam, Args
from nonebot import get_adapters, get_bot, get_driver, logger, on_message
from nonebot.adapters import Event
from nonebot.permission import SUPERUSER
from nonebot.rule import to_me
from nonebot_plugin_alconna import (
    AlconnaMatch,
    CommandMeta,
    Match,
    UniMessage,
    on_alconna,
)
from nonebot_plugin_alconna.uniseg import Image, UniMsg

from .config import plugin_config
from .muice import Muice
from .scheduler import setup_scheduler
from .utils import legacy_get_images, save_image_as_file

muice = Muice()
scheduler = None

muice_nicknames = plugin_config.muice_nicknames
regex_patterns = [f"^{re.escape(nick)}\\s*" for nick in muice_nicknames]
combined_regex = "|".join(regex_patterns)

driver = get_driver()
adapters = get_adapters()


@driver.on_startup
async def on_startup():
    if not muice.load_model():
        logger.error("模型加载失败，请检查配置项是否正确")
        exit(1)
    logger.info("MuiceAI 聊天框架已开始运行⭐")


command_help = on_alconna(
    Alconna([".", "/"], "help", meta=CommandMeta("输出帮助信息")),
    priority=90,
    block=True,
)

command_status = on_alconna(
    Alconna([".", "/"], "status", meta=CommandMeta("显示当前状态")),
    priority=90,
    block=True,
)

command_reset = on_alconna(
    Alconna([".", "/"], "reset", meta=CommandMeta("清空对话记录")),
    priority=10,
    block=True,
)

command_refresh = on_alconna(
    Alconna([".", "/"], "refresh", meta=CommandMeta("刷新模型输出")),
    priority=10,
    block=True,
)

command_undo = on_alconna(
    Alconna([".", "/"], "undo", meta=CommandMeta("撤回上一个对话")),
    priority=10,
    block=True,
)

command_load = on_alconna(
    Alconna(
        [".", "/"],
        "load",
        Args["config_name", str, "model"],
        meta=CommandMeta(
            "加载模型", usage="load <config_name>", example="load model.deepseek"
        ),
    ),
    priority=10,
    block=True,
    permission=SUPERUSER,
)

command_schedule = on_alconna(
    Alconna([".", "/"], "schedule", meta=CommandMeta("加载定时任务")),
    priority=10,
    block=True,
    permission=SUPERUSER,
)

command_whoami = on_alconna(
    Alconna([".", "/"], "whoami", meta=CommandMeta("输出当前用户信息")),
    priority=90,
    block=True,
)

nickname_event = on_alconna(
    Alconna(re.compile(combined_regex), Args["text?", AllParam], separators=""),
    priority=99,
    block=True,
)

at_event = on_message(priority=100, rule=to_me(), block=True)


@driver.on_bot_connect
@command_schedule.handle()
async def on_bot_connect():
    global scheduler
    if not scheduler:
        scheduler = setup_scheduler(muice, get_bot())


@driver.on_bot_disconnect
async def on_bot_disconnect():
    global scheduler
    if scheduler:
        scheduler.remove_all_jobs()
        scheduler = None


@command_help.handle()
async def handle_command_help():
    await command_help.finish(
        "基本命令：\n"
        "help 输出此帮助信息\n"
        "status 显示当前状态\n"
        "refresh 刷新模型输出\n"
        "reset 清空对话记录\n"
        "undo 撤回上一个对话\n"
        "whoami 输出当前用户信息\n"
        "load <config_name> 加载模型\n"
        "（支持的命令前缀：“.”、“/”）"
    )


@command_status.handle()
async def handle_command_status():
    model_loader = muice.model_loader
    model_status = "运行中" if muice.model and muice.model.is_running else "未启动"
    multimodal_enable = "是" if muice.multimodal else "否"

    scheduler_status = "运行中" if scheduler and scheduler.running else "未启动"

    if scheduler and scheduler.running:
        job_ids = [job.id for job in scheduler.get_jobs()]
        if job_ids:
            current_scheduler = "、".join(job_ids)
        else:
            current_scheduler = "暂无运行中的调度器"
    else:
        current_scheduler = "调度器引擎未启动！"

    await command_status.finish(
        f"当前模型加载器：{model_loader}\n"
        f"模型加载器状态：{model_status}\n"
        f"多模态模型: {multimodal_enable}\n"
        f"定时任务调度器引擎状态：{scheduler_status}\n"
        f"运行中的运行任务调度器：{current_scheduler}"
    )


@command_reset.handle()
async def handle_command_reset(event: Event):
    userid = event.get_user_id()
    response = await muice.reset(userid)
    await command_reset.finish(response)


@command_refresh.handle()
async def handle_command_refresh(event: Event):
    userid = event.get_user_id()
    response = await muice.refresh(userid)

    paragraphs = response.split("\n")

    for index, paragraph in enumerate(paragraphs):
        if index == len(paragraphs) - 1:
            await command_refresh.finish(paragraph)
        await command_refresh.send(paragraph)


@command_undo.handle()
async def handle_command_undo(event: Event):
    userid = event.get_user_id()
    response = await muice.undo(userid)
    await command_undo.finish(response)


@command_load.handle()
async def handle_command_load(config: Match[str] = AlconnaMatch("config_name")):
    config_name = config.result
    result = muice.change_model_config(config_name)
    await UniMessage(result).finish()


@command_whoami.handle()
async def handle_command_handle(event: Event):
    await command_whoami.finish(
        f"用户 ID: {event.get_user_id()}\n" f"当前会话信息：{event.get_session_id()}"
    )


@at_event.handle()
@nickname_event.handle()
async def handle_supported_adapters(message: UniMsg, event: Event):
    message_text = message.extract_plain_text()
    message_images = message.get(Image)
    userid = event.get_user_id()

    image_paths = []

    if muice.multimodal:
        for img in message_images:

            if not img.url:
                # 部分 Onebot 适配器实现无法直接获取url，尝试回退至传统获取方式
                logger.warning("无法通过通用方式获取图片URL，回退至传统方式...")
                image_paths = list(
                    set(
                        [
                            await legacy_get_images(img.origin, event)
                            for img in message_images
                        ]
                    )
                )
                break

            image_paths.append(save_image_as_file(img.url, img.name))

    logger.info(f"Received a message: {message_text}")

    if not (message_text or image_paths):
        return

    response = await muice.ask(message_text, userid, image_paths=image_paths)
    response.strip()

    logger.info(f"Response: {message_text}")

    paragraphs = response.split("\n")

    for index, paragraph in enumerate(paragraphs):
        if index == len(paragraphs) - 1:
            await UniMessage(paragraph).finish()
        await UniMessage(paragraph).send()


@at_event.handle()
@nickname_event.handle()
async def handle_universal_adapters(event: Event):
    message = event.get_plaintext()
    user_id = event.get_user_id()
    logger.info(f"Received a message: {message}")

    if not message:
        return

    response = await muice.ask(message, user_id)
    response.strip()

    paragraphs = response.split("\n")

    for index, paragraph in enumerate(paragraphs):
        if index == len(paragraphs) - 1:
            await UniMessage(paragraph).finish()
        await UniMessage(paragraph).send()
