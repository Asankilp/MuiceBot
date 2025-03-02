from nonebot import logger,get_plugin_config
from .llm import BasicModel
from .llm.utils.thought import process_thoughts
from .config import config,Config,get
from .database import Database
import time
import importlib

class Muice:
    '''
    Muice交互类
    '''
    def __init__(self, model_config = config.model):
        self.model_config = model_config
        self.think = self.model_config.get('think', 0)
        self.model_loader = self.model_config.get('loader', '')
        self.multimodal = self.model_config.get('multimodal', False)
        self.database = Database()
        self.__load_model()

    def __load_model(self):
        '''
        初始化模型类
        '''
        module_name = f"nonebot_plugin_muicebot.llm.{self.model_loader}"
        module = importlib.import_module(module_name)
        ModelClass = getattr(module, self.model_loader, None)
        self.model: BasicModel|None = ModelClass() if ModelClass else None

    def load_model(self) -> bool:
        '''
        加载模型

        return: 是否加载成功
        '''
        logger.info('正在加载模型...')
        if not self.model:
            logger.error('模型加载失败')
            return False
        if not self.model.load(self.model_config):
            logger.error('模型加载失败')
            return False
        logger.info('模型加载成功')
        return True

    def change_model_config(self, config_name:str) -> str:
        '''
        更换模型配置文件并重新加载模型
        '''
        if not hasattr(config, config_name):
            logger.error('指定的模型配置不存在')
            return '指定的模型配置不存在'
        
        model_config = getattr(config, config_name)
        new_config = get()
        new_config.update({'model':model_config})
        try:
            Config(**new_config) # 校验模型配置可用性
        except:
            return '指定的模型加载器不存在，请检查配置文件'

        self.model_config = model_config
        self.think = self.model_config.get('think', 0)
        self.model_loader = self.model_config.get('loader', '')
        self.multimodal = self.model_config.get('multimodal', False)
        self.__load_model()
        self.load_model()

        return f'已成功加载 {config_name}'

    def ask(self, message: str, username: str, userid:str, groupid: str = '-1', image_paths:list = []) -> str:
        '''
        调用模型

        :param message: 消息内容
        :param image_paths: 图片URL列表（仅在多模态启用时生效）
        :param user_id: 用户ID
        :param group_id: 群组ID
        :return: 模型回复
        '''
        if not (self.model and self.model.is_running):
            logger.error('模型未加载')
            return '(模型未加载)'

        logger.info('正在调用模型...')

        history = self.get_chat_memory(userid)

        start_time = time.time()
        logger.debug(f'模型调用参数：Prompt: {message}, History: {history}')
        if self.multimodal:
            reply = self.model.ask_vision(message, image_paths, history).strip()
        else:
            reply = self.model.ask(message, history).strip()
        end_time = time.time()
        logger.info(f'模型调用时长: {end_time - start_time} s')

        thought, result = process_thoughts(reply, self.think)
        reply = "".join([thought,result])

        self.database.add_item(username, userid, message, result, groupid, image_paths)

        return reply
    
    def get_chat_memory(self, userid:str) -> list:
        '''
        获取记忆
        '''
        history = self.database.get_history(userid)
        if not history:
            return []
        
        history = [[item[5], item[6]] for item in history]
        return history

    def create_a_new_topic(self, last_time:int) -> str:
        '''
        主动发起对话

        :param last_time: 上次对话时间
        '''
        ...

    def get_recent_chat_memory(self) -> list:
        '''
        获取最近一条记忆
        '''
        ...

    def image_query(self, image_path:str) -> str:
        ...

    def refresh(self, userid:str) -> str:
        '''
        刷新对话
        '''
        logger.info(f'用户 {userid} 请求刷新')

        last_item = self.database.get_last_item(userid)

        if not last_item:
            logger.error('用户对话数据不存在，拒绝刷新')
            return '你都还没和我说过一句话呢，得和我至少聊上一段才能刷新哦'
        if not (self.model and self.model.is_running):
            logger.error('模型未加载')
            return '(模型未加载)'

        username, userid, groupid, message, = set(last_item[0][2:6])
        image_paths = last_item[0][8]
        self.database.remove_last_item(userid)
        history = self.get_chat_memory(userid)

        start_time = time.time()
        logger.debug(f'模型调用参数：Prompt: {message}, History: {history}')
        if self.multimodal and image_paths:
            reply = self.model.ask_vision(message, image_paths, history).strip()
        else:
            reply = self.model.ask(message, history).strip()
        end_time = time.time()
        logger.info(f'模型调用时长: {end_time - start_time} s')
        logger.info(f"模型返回：{reply}")


        thought, result = process_thoughts(reply, self.think)
        reply = "".join([thought,result])

        self.database.add_item(username, userid, message, result, groupid, image_paths)

        return reply

    def reset(self, userid:str) -> str:
        '''
        清空历史对话（将用户对话历史记录标记为不可用）
        '''
        self.database.mark_history_as_unavailable(userid)
        return '已成功移除对话历史~'
    
    def undo(self, userid:str) -> str:
        self.database.remove_last_item(userid)
        return '已成功撤销上一段对话~'